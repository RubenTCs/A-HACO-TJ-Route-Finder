import random
import numpy as np
from .utils import (
    calculate_final_metrics,
    build_detailed_journey,
    build_path_coordinates,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _edge_cost(edge_data, w_t, w_c, w_p):
    return (
        w_t * edge_data.get('Waktuij_norm', 0) +
        w_c * edge_data.get('Biayaij_norm', 0) +
        w_p * edge_data.get('Transitij', 0)
    )


def _path_z(G, path, w_t, w_c, w_p):
    """Compute the objective Z for a given path (eq 2.1 using normalized values)."""
    z = 0.0
    for u, v in zip(path, path[1:]):
        edict = G.get_edge_data(u, v)
        if not edict:
            continue
        best = min(edict.values(), key=lambda e: _edge_cost(e, w_t, w_c, w_p))
        z += _edge_cost(best, w_t, w_c, w_p)
    return z


def _roulette(probs):
    """Roulette-wheel selection; returns index. Falls back to uniform if total <= 0."""
    total = sum(probs)
    if total <= 0:
        return random.randrange(len(probs))
    r = random.uniform(0, total)
    cumulative = 0.0
    for i, p in enumerate(probs):
        cumulative += p
        if r <= cumulative:
            return i
    return len(probs) - 1


def _grow_path(G, start_node, end_nodes_set, tau, eta, alpha, beta, tau_0,
               w_t, w_c, w_p, max_steps, seed_path=None):
    """
    Construct a path toward end_nodes_set using pheromone + heuristic guidance.

    Tabu: visited_nodes tracks exact (stop, route) tuples already on the path.
    Blocking by stop name is intentionally avoided — (Harmoni, r1) and (Harmoni, r2)
    are different nodes, so the ant can arrive at the same physical stop via a
    different route, which is exactly how transit transfers work.
    """
    if seed_path is not None:
        path = list(seed_path)
        visited_nodes = set(path)
    else:
        path = [start_node]
        visited_nodes = {start_node}

    current = path[-1]

    for _ in range(max_steps):
        if current in end_nodes_set:
            break

        candidates = []
        for neighbor in G.successors(current):
            if neighbor in visited_nodes:
                continue
            edict = G.get_edge_data(current, neighbor)
            if not edict:
                continue
            best_key = min(edict, key=lambda k: _edge_cost(edict[k], w_t, w_c, w_p))
            candidates.append((neighbor, best_key))

        if not candidates:
            break

        probs = [
            tau.get((current, nb, k), tau_0) ** alpha *
            eta.get((current, nb, k), 1.0) ** beta
            for nb, k in candidates
        ]

        next_node, _ = candidates[_roulette(probs)]
        path.append(next_node)
        visited_nodes.add(next_node)
        current = next_node

    return path


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------

def find_route_with_haco(
    G, stop_to_routes, start_stop, end_stop, weights,
    n_ants=10,
    max_iter=50,
    alpha=1.0,      # pheromone exponent
    beta=2.0,       # heuristic exponent
    rho=0.1,        # pheromone evaporation rate
    Q=1.0,          # pheromone deposit strength
    tau_0=0.1,      # initial pheromone on all edges
    max_no_improve_iter=15,  # second stopping criterion: iterations without improvement
    lambda_mut=0.3, # Poisson mutation rate
):
    """
    Find optimal route using Hybrid Ant Colony Optimization.

    Hybrid element: after each construction phase, k ~ Poisson(lambda_mut) mutation
    events are applied per solution — each truncates the path at a random interior
    point and re-grows it, keeping the result only if it improves Z.

    Dual stopping criteria: max_iter OR `max_no_improve_iter` consecutive iterations without
    improvement to the global best.
    """
    print("--- Start find route with HACO ---")

    if start_stop not in stop_to_routes:
        return {"error": f"Halte Asal '{start_stop}' tidak ditemukan."}
    if end_stop not in stop_to_routes:
        return {"error": f"Halte Tujuan '{end_stop}' tidak ditemukan."}

    start_nodes = [n for n in G.nodes() if n[0] == start_stop]
    end_nodes_set = {n for n in G.nodes() if n[0] == end_stop}

    if not start_nodes or not end_nodes_set:
        return {"error": "Node asal atau tujuan tidak terhubung ke graf."}

    w_t = float(weights.get('waktu', 0))
    w_c = float(weights.get('biaya', 0))
    w_p = float(weights.get('transit', 0))

    # Cap path length at 300 steps — far more than any realistic Transjakarta journey.
    max_steps = min(G.number_of_nodes(), 300)

    # Precompute heuristic: η(i,j,k) = 1 / (d_ijk + ε)
    eta = {
        (u, v, key): 1.0 / (_edge_cost(data, w_t, w_c, w_p) + 1e-9)
        for u, v, key, data in G.edges(keys=True, data=True)
    }

    # Initialize pheromone trails uniformly
    tau = {(u, v, key): tau_0 for u, v, key in G.edges(keys=True)}

    best_path = None
    best_z = float('inf')
    no_improvement = 0

    for iteration in range(max_iter):

        # --- Ant construction phase ---
        solutions = []
        for _ in range(n_ants):
            start = random.choice(start_nodes)
            path = _grow_path(G, start, end_nodes_set, tau, eta, alpha, beta,
                              tau_0, w_t, w_c, w_p, max_steps)
            if path and path[-1] in end_nodes_set:
                solutions.append(path)

        # --- Poisson mutation (hybrid element) ---
        # Per solution: k ~ Poisson(lambda_mut) independent mutation attempts.
        improved = []
        for path in solutions:
            z_curr = _path_z(G, path, w_t, w_c, w_p)
            n_mut = int(np.random.poisson(lambda_mut))
            for _ in range(n_mut):
                if len(path) < 3:
                    break
                cut = random.randint(1, len(path) - 1)
                seed = path[:cut]
                mutant = _grow_path(G, seed[-1], end_nodes_set, tau, eta, alpha, beta,
                                    tau_0, w_t, w_c, w_p, max_steps, seed_path=seed)
                if mutant and mutant[-1] in end_nodes_set:
                    z_mut = _path_z(G, mutant, w_t, w_c, w_p)
                    if z_mut < z_curr:
                        path, z_curr = mutant, z_mut
            improved.append(path)
        solutions = improved

        if not solutions:
            no_improvement += 1
            if no_improvement >= max_no_improve_iter:
                print(f"HACO: Konvergen di iterasi {iteration + 1} (no solutions)")
                break
            continue

        # --- Update global best ---
        iter_best = min(solutions, key=lambda p: _path_z(G, p, w_t, w_c, w_p))
        iter_z = _path_z(G, iter_best, w_t, w_c, w_p)

        if iter_z < best_z:
            best_z = iter_z
            best_path = iter_best
            no_improvement = 0
        else:
            no_improvement += 1

        # --- Pheromone evaporation ---
        for key in tau:
            tau[key] = max(tau[key] * (1.0 - rho), 1e-10)

        # --- Global-best deposit ---
        deposit = Q / (best_z + 1e-9)
        for u, v in zip(best_path, best_path[1:]):
            edict = G.get_edge_data(u, v)
            if not edict:
                continue
            best_key = min(edict, key=lambda k: _edge_cost(edict[k], w_t, w_c, w_p))
            if (u, v, best_key) in tau:
                tau[(u, v, best_key)] += deposit

        # --- Dual stopping criteria ---
        if no_improvement >= max_no_improve_iter:
            print(f"HACO: Konvergen di iterasi {iteration + 1} (no_improvement)")
            break

    if best_path is None:
        return {"error": "Jalur tidak ditemukan oleh HACO."}

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
