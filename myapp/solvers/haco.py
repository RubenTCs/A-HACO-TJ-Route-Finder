import random
from time import perf_counter
import numpy as np

from .utils import (
    calculate_final_metrics,
    build_detailed_journey,
    build_path_coordinates,
    get_boarding_fare,
)
from ..constants import (
    HACO_N_ANTS,
    HACO_MAX_ITER,
    HACO_ALPHA,
    HACO_BETA,
    HACO_RHO,
    HACO_TAU_0,
    HACO_MAX_NO_IMPROVE_ITER,
    HACO_TABU_SIZE,
)


# ==========================================================
# region Cost / probability primitives
# ==========================================================

def _edge_cost(edge_data, w_t, w_c, w_p):
    return (
        w_t * edge_data.get('Waktuij_norm', 0) +
        w_c * edge_data.get('Biayaij_norm', 0) +
        w_p * edge_data.get('Transitij_norm', 0)
    )


def _best_edge_key(edict, w_t, w_c, w_p):
    """Pick the cheapest parallel edge between two nodes."""
    return min(edict, key=lambda k: _edge_cost(edict[k], w_t, w_c, w_p))


def _path_z(G, path, w_t, w_c, w_p):
    """Objective Z for a path (eq 2.1, normalized)."""
    if not path:
        return 0.0
    # Boarding fare for first leg travel edges have Biayaij_norm=0,
    # so without this paths starting on different fare classes look equal.
    _, boarding_norm = get_boarding_fare(G, path[0])
    z = w_c * boarding_norm
    for u, v in zip(path, path[1:]):
        edict = G.get_edge_data(u, v)
        if edict:
            best = min(edict.values(), key=lambda e: _edge_cost(e, w_t, w_c, w_p))
            z += _edge_cost(best, w_t, w_c, w_p)
    return z


def _roulette(probs):
    """Roulette-wheel selection; uniform fallback when total <= 0."""
    total = sum(probs)
    if total <= 0:
        return random.randrange(len(probs))
    r = random.uniform(0, total)
    cum = 0.0
    for i, p in enumerate(probs):
        cum += p
        if r <= cum:
            return i
    return len(probs) - 1


# ==========================================================
# Path construction (one ant)
# ==========================================================

def _construct_path(G, start_node, end_nodes_set, tau, eta, alpha, beta, tau_0,
                    w_t, w_c, w_p, seed_path=None):
    """
    Construct a path from start_node toward any node in end_nodes_set.

    Dead-end backtracking: on a dead-end
    we pop back and add the node to `forbidden` so it can't be re-chosen later.
    Without this, an ant locked onto a corridor that doesn't reach the goal
    would simply break and produce no solution.

    With seed_path: an existing partial path is inherited as the starting point for mutation.
    The ant continues from the last node of seed_path, and backtracking is bounded so
    inherited nodes stay pinned and cannot be altered.
    """
    if seed_path is not None:
        path = list(seed_path)
        visited = set(path)
        seed_floor = len(seed_path)
    else:
        path = [start_node]
        visited = {start_node}
        seed_floor = 1

    forbidden = set()

    while path:
        current = path[-1]
        if current in end_nodes_set:
            break

        candidates = _get_candidates(G, current, visited, forbidden, w_t, w_c, w_p)

        if not candidates:
            # Dead-end. Pop back unless we're at the start / seed boundary.
            if len(path) <= seed_floor:
                break
            forbidden.add(current)
            visited.discard(current)
            path.pop()
            continue

        next_node = _sample_next(candidates, current, tau, eta, alpha, beta, tau_0)
        path.append(next_node)
        visited.add(next_node)

    return path


def _get_candidates(G, current, visited, forbidden, w_t, w_c, w_p):
    """Unvisited, non-forbidden successors with their cheapest edge key."""
    out = []
    for neighbor in G.successors(current):
        if neighbor in visited or neighbor in forbidden:
            continue
        edict = G.get_edge_data(current, neighbor)
        if not edict:
            continue
        out.append((neighbor, _best_edge_key(edict, w_t, w_c, w_p)))
    return out


def _sample_next(candidates, current, tau, eta, alpha, beta, tau_0):
    """Probabilistic step using P_ijk ∝ τ^α · η^β (eq 2.14)."""
    probs = [
        tau.get((current, nb, k), tau_0) ** alpha *
        eta.get((current, nb, k), 1.0) ** beta
        for nb, k in candidates
    ]
    nb, _ = candidates[_roulette(probs)]
    return nb


# ==========================================================
# Per-ant operations
# ==========================================================

def _sample_tabu_list(prior_solutions, tabu_size, n_ants):
    """
    Randomly select tabusize x nAnts solutions for the tabu list
    Sampled from solutions generated so far in the current iteration.
    """
    if not prior_solutions:
        return set()
    n_tabu = int(round(tabu_size * n_ants))
    n_tabu = min(n_tabu, len(prior_solutions))
    if n_tabu <= 0:
        return set()
    sampled = random.sample(prior_solutions, n_tabu)
    return {tuple(p) for p, _ in sampled}


def _mutate_until_unique(G, path, F_a, tabu_paths, end_nodes_set,
                         tau, eta, alpha, beta, tau_0,
                         w_t, w_c, w_p, max_attempts=20):
    """
    while ant's path exists in tabu list do { pick node, rebuild }.
    Keep mutating until path is no longer in tabu list (or attempts exhausted)
    Eq 2.19: cut index k ~ Poisson(L/3), seed = path[:k], construct path from there.
    """
    attempts = 0
    while tuple(path) in tabu_paths and attempts < max_attempts:
        if len(path) < 3:
            break
        L = len(path)
        k = int(np.random.poisson(max(L / 3.0, 1e-9)))
        cut = max(1, min(k, L - 1))
        seed = path[:cut]
        mutant = _construct_path(G, seed[-1], end_nodes_set, tau, eta,
                                 alpha, beta, tau_0, w_t, w_c, w_p, seed_path=seed)
        if mutant and mutant[-1] in end_nodes_set:
            path = mutant
            F_a = _path_z(G, path, w_t, w_c, w_p)
        attempts += 1
    return path, F_a


def _update_trail_matrix(G, path, F_a, tau, rho, w_t, w_c, w_p):
    """
    Per-ant trail matrix update — literal eq 2.15 + 2.16 with A_ijk = {this ant}:
        τ_ijk(t) = (1-ρ)·τ_ijk(t-1) + Δτ_ijk
        Δτ_ijk = 1/F_a   if edge (i,j,k) in this ant's path
               = 0        otherwise
    Called after each ant per Fig 2.8 (inside per-ant loop). Note this evaporates
    ALL E edges every ant, so the iteration is O(n_ants · E) — slow on big graphs,
    but faithful to the pseudocode.
    """
    # Evaporation across all edges (eq 2.15 first term)
    for key in tau:
        tau[key] = max(tau[key] * (1.0 - rho), 1e-10)

    # Deposit on edges traversed by this ant (eq 2.16)
    for u, v in zip(path, path[1:]):
        edict = G.get_edge_data(u, v)
        if not edict:
            continue
        key = (u, v, _best_edge_key(edict, w_t, w_c, w_p))
        if key in tau:
            tau[key] += 1.0 / (F_a + 1e-9)


# ==========================================================
# Main solver
# ==========================================================

def find_path_with_haco(
    G, stop_to_routes, start_stop, end_stop, weights,
    n_ants=HACO_N_ANTS,
    max_iter=HACO_MAX_ITER,
    alpha=HACO_ALPHA,                          # pheromone exponent (eq 2.14)
    beta=HACO_BETA,                            # heuristic exponent (eq 2.14) — Table 1 of AlHousrya 2024
    rho=HACO_RHO,                              # evaporation rate (eq 2.15)
    tau_0=HACO_TAU_0,                          # initial pheromone — 2.6.2: τ_ijk(0) = 1
    max_no_improve_iter=HACO_MAX_NO_IMPROVE_ITER,  # per-ant non-improvement count (pseudocode noImprovementIterations)
    tabu_size=HACO_TABU_SIZE,                  # fraction of solutions sampled into Tabu List
):
    """
    Hybrid ACO route search

    Outer loop:
      while iterations < maxIterations AND noImprovementIterations < maxNoImprovement

    Inner loop (per ant):
      1. Create an ant — construct a path from start to end.
      2. Randomly select tabusize x nAnts solutions for the tabu list.
      3. While ant's path exists in the tabu list => pick a node, rebuild (mutation).
      4. Update trail matrix (evaporate all edges + deposit on this ant's edges).
      5. If objective improved => noImprovementIterations = 0, else += 1.

    NOTE: step 4 evaporates every edge once per ant, so each iteration is
    O(n_ants · |E|). Slow on large graphs by design — kept faithful to Fig 2.8.
    """
    print("--- Start find route with HACO ---")

    # --- Validate inputs ---
    if start_stop not in stop_to_routes:
        return {"error": f"Halte Asal '{start_stop}' tidak dilayani angkutan pada jam yang dipilih."}
    if end_stop not in stop_to_routes:
        return {"error": f"Halte Tujuan '{end_stop}' tidak dilayani angkutan pada jam yang dipilih."}

    start_nodes = [n for n in G.nodes() if n[0] == start_stop]
    end_nodes_set = {n for n in G.nodes() if n[0] == end_stop}
    if not start_nodes or not end_nodes_set:
        return {"error": "Node asal atau tujuan tidak terhubung ke graf."}

    w_t = float(weights.get('waktu', 0))
    w_c = float(weights.get('biaya', 0))
    w_p = float(weights.get('transit', 0))

    # η(i,j,k) = 1 / edge_cost — cheaper edges get higher attractiveness (eq 2.17–2.18)
    eta = {}
    for u, v, key, data in G.edges(keys=True, data=True):
        eta[(u, v, key)] = 1.0 / (_edge_cost(data, w_t, w_c, w_p) + 1e-9)
    # Initial pheromone trails —  2.6.2: τ_ijk(0) = matrix of ones
    tau = {(u, v, key): tau_0 for u, v, key in G.edges(keys=True)}

    best_path, best_z = None, float('inf')
    no_improvement = 0
    iteration = 0
    t_start = perf_counter()

    # --- Outer loop (pseudocode: while iterations < maxIter AND noImp < maxNoImp) ---
    while iteration < max_iter and no_improvement < max_no_improve_iter:
        iteration_solutions = []  # prior solutions this iteration, for tabu sampling

        # --- Inner loop: per ant ---
        ant_index = 0
        while ant_index < n_ants:
            # 1. Create an ant — construct a path from a random start node
            start = random.choice(start_nodes)
            path = _construct_path(G, start, end_nodes_set, tau, eta,
                                   alpha, beta, tau_0, w_t, w_c, w_p)

            if not path or path[-1] not in end_nodes_set:
                no_improvement += 1
                ant_index += 1
                continue

            F_a = _path_z(G, path, w_t, w_c, w_p)

            # 2. Randomly select tabusize x nAnts solutions for the tabu list
            tabu_paths = _sample_tabu_list(iteration_solutions, tabu_size, n_ants)

            # 3. While ant's path exists in tabu list => mutate
            path, F_a = _mutate_until_unique(
                G, path, F_a, tabu_paths, end_nodes_set,
                tau, eta, alpha, beta, tau_0, w_t, w_c, w_p,
            )

            iteration_solutions.append((path, F_a))

            # 4. Update trail matrix (per ant)
            _update_trail_matrix(G, path, F_a, tau, rho, w_t, w_c, w_p)

            # 5. Improvement check (per ant)
            if F_a < best_z:
                best_z, best_path = F_a, path
                no_improvement = 0
                print(f"HACO: Solusi terbaik di iterasi {iteration+1}, "
                      f"semut {ant_index+1} (z={best_z:.6f}, "
                      f"t={perf_counter()-t_start:.2f}s)")
            else:
                no_improvement += 1

            ant_index += 1

        iteration += 1

    if best_path is None:
        return {"error": "Jalur tidak ditemukan oleh HACO."}

    print(f"HACO: Selesai di iterasi {iteration} (z_best={best_z:.6f}, "
          f"total t={perf_counter()-t_start:.2f}s)")

    # --- Build response payload ---
    final_metrics = calculate_final_metrics(G, best_path, weights)
    if "error" in final_metrics:
        return final_metrics

    detailed_journey = build_detailed_journey(G, best_path)
    coord_result = build_path_coordinates(detailed_journey, best_path)

    return {
        "detailed_journey": detailed_journey,
        "path_coordinates": coord_result["path_coordinates"],
        "path_segments": coord_result["path_segments"],
        "jarak_km": final_metrics.get("jarak_km", 0),
        "waktu_tempuh_menit": final_metrics.get("waktu_tempuh_menit", 0),
        "total_biaya": final_metrics.get("total_biaya", 0),
        "jumlah_transit": final_metrics.get("jumlah_transit", 0),
        "z_score": final_metrics.get("z_score", 0),
    }
