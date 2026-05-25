import random
from time import perf_counter
import numpy as np

from .utils import (
    calculate_final_metrics,
    build_detailed_journey,
    build_path_coordinates,
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
    """Objective Z for a path (Pers. 2.1, normalized).

    First-ride fare lives on the travel edges leaving the origin (set by
    apply_terminal_walk_policy), so summing edge costs already includes it.
    """
    if not path:
        return 0.0
    z = 0.0
    for u, v in zip(path, path[1:]):
        edict = G.get_edge_data(u, v)
        if edict:
            best = min(edict.values(), key=lambda e: _edge_cost(e, w_t, w_c, w_p))
            z += _edge_cost(best, w_t, w_c, w_p)
    return z


def _roulette(probs):
    """Roulette-wheel selection uniform fallback when total <= 0."""
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
                    w_t, w_c, w_p, jalur_awal=None):
    """
    Construct a path from start_node toward any node in end_nodes_set.

    Dead-end backtracking: on a dead-end pop back and add the node to `forbidden` so it can't be re-chosen later.

    With jalur_awal: potongan jalur (path[:k] sampai node perantara) diwariskan
    sebagai titik mulai mutasi (Bab 2.6.2). Semut melanjutkan dari node perantara
    (jalur_awal[-1]), dan backtracking dibatasi agar bagian jalur awal yang
    dipertahankan tidak bisa diubah.
    """
    if jalur_awal is not None:
        path = list(jalur_awal)
        visited = set(path)
        batas_jalur_awal = len(jalur_awal)
    else:
        path = [start_node]
        visited = {start_node}
        batas_jalur_awal = 1

    forbidden = set()

    while path:
        current = path[-1]
        if current in end_nodes_set:
            break

        candidates = _get_candidates(G, current, visited, forbidden, w_t, w_c, w_p)

        if not candidates:
            # Dead-end. Pop back kecuali sudah di batas jalur awal (node perantara).
            if len(path) <= batas_jalur_awal:
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
    """Probabilistic step using P_ijk ∝ τ^α · η^β (Pers. 2.14)."""
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
    while ant's path exists in tabu list do { pilih node perantara, rebuild }.
    Keep mutating until path is no longer in tabu list (or attempts exhausted)
    Pers. 2.19: posisi node perantara k ~ Poisson(L/3), jalur_awal = path[:k],
    konstruksi ulang dari node perantara hingga tujuan.
    """
    attempts = 0
    while tuple(path) in tabu_paths and attempts < max_attempts:
        if len(path) < 3:
            break
        L = len(path)
        k = int(np.random.poisson(max(L / 3.0, 1e-9)))
        pos_perantara = max(1, min(k, L - 1))
        jalur_awal = path[:pos_perantara]
        # print(f"HACO: Mutasi jalur karena tabu (attempt {attempts+1}, pos_perantara={pos_perantara})")
        mutant = _construct_path(G, jalur_awal[-1], end_nodes_set, tau, eta,
                                 alpha, beta, tau_0, w_t, w_c, w_p, jalur_awal=jalur_awal)
        if mutant and mutant[-1] in end_nodes_set:
            path = mutant
            F_a = _path_z(G, path, w_t, w_c, w_p)
        attempts += 1
    return path, F_a



def _update_trail(G, path, F_a, tau, rho, w_t, w_c, w_p):
    """
    Per-ant local update (ACS-inspired).
    Evaporates all edges with rate rho, then deposits 1/F_a on this ant's path.
    Called once per ant — encourages subsequent ants to explore different edges.
    """
    for key in tau:
        tau[key] = max(tau[key] * (1.0 - rho), 1e-10)

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
    alpha=HACO_ALPHA,                          # pheromone exponent (Pers. 2.14)
    beta=HACO_BETA,                            # heuristic exponent (Pers. 2.14)
    rho=HACO_RHO,                              # evaporation rate (per ant, inside loop)
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
    print(f"HACO params: n_ants={n_ants}, max_iter={max_iter}, alpha={alpha}, beta={beta}, "
          f"rho={rho}, tau_0={tau_0}, max_no_improve_iter={max_no_improve_iter}, tabu_size={tabu_size}")
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

    # η(i,j,k) = 1 / edge_cost — cheaper edges get higher attractiveness (Pers. 2.17-2.18)
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

            # Calculate objective F_a for this path
            F_a = _path_z(G, path, w_t, w_c, w_p)

            # 2. Randomly select tabusize x nAnts solutions for the tabu list
            tabu_paths = _sample_tabu_list(iteration_solutions, tabu_size, n_ants)

            # 3. While ant's path exists in tabu list => mutate
            path, F_a = _mutate_until_unique(
                G, path, F_a, tabu_paths, end_nodes_set,
                tau, eta, alpha, beta, tau_0, w_t, w_c, w_p,
            )

            iteration_solutions.append((path, F_a))

            # 4a. Local trail update (per ant, rho rate — diversifikasi)
            _update_trail(G, path, F_a, tau, rho, w_t, w_c, w_p)

            # 5. Improvement check (per ant)
            if F_a < best_z:
                best_z, best_path = F_a, path
                print(f"HACO: Solusi terbaik di iterasi {iteration+1}, no_improvement={no_improvement}, "
                      f"semut {ant_index+1} (z={best_z:.6f}, "
                      f"t={perf_counter()-t_start:.2f}s)")
                no_improvement = 0
            else:
                no_improvement += 1

            ant_index += 1
            # Early stop, disable 
            if no_improvement >= max_no_improve_iter:
                break

        iteration += 1

    if best_path is None:
        return {"error": "Jalur tidak ditemukan oleh HACO."}

    print(f"HACO: Selesai di iterasi {iteration}, no_improvement {no_improvement}, ant {ant_index} (z_best={best_z:.6f}, "
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
