import heapq
from .utils import (
    haversine,
    build_coord_map,
    calculate_final_metrics,
    build_detailed_journey,
    build_path_coordinates,
)

_T_MAX = 360.0  # normalization constant (minutes), matches graph.py T_MAX

def find_route_with_astar(G, stop_to_routes, start_stop, end_stop, weights, speed_kmh=25.0):
    """
    Find optimal route using A* search on the (stop_name, route_id) multigraph.

    Heuristic: h(n) = w_t * haversine(n, D) * 60 / (speed_kmh * T_MAX)
    Admissible because haversine <= actual route distance.
    """
    print("--- Start find route with A* ---")

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

    coord_map = build_coord_map()

    end_coords = coord_map.get(end_stop)

    def heuristic(node):
        # Admissible lower bound: straight-line time to destination, time-normalized.
        # Ignores cost and transit components (both are >= 0, so omitting them underestimates).
        if end_coords is None:
            return 0.0
        coords = coord_map.get(node[0])
        if coords is None:
            return 0.0
        dist_km = haversine(coords[1], coords[0], end_coords[1], end_coords[0])
        return w_t * dist_km * 60.0 / (speed_kmh * _T_MAX)

    def edge_cost(edge_data):
        return (
            w_t * edge_data.get('Waktuij_norm', 0) +
            w_c * edge_data.get('Biayaij_norm', 0) +
            w_p * edge_data.get('Transitij', 0)
        )

    # g_score[node] = best cost found so far from any start node
    g_score = {}
    # came_from[node] = parent_node (edge key not needed for path reconstruction)
    came_from = {}

    # open_set entries: (f, tiebreak_counter, node)
    open_set = []
    counter = 0

    for s in start_nodes:
        g_score[s] = 0.0
        heapq.heappush(open_set, (heuristic(s), counter, s))
        counter += 1

    closed_set = set()
    goal_node = None

    while open_set:
        _, _, current = heapq.heappop(open_set)

        if current in closed_set:
            continue
        closed_set.add(current)

        if current in end_nodes_set:
            goal_node = current
            break

        g_curr = g_score[current]

        for neighbor in G.successors(current):
            if neighbor in closed_set:
                continue

            edge_data_dict = G.get_edge_data(current, neighbor)
            if not edge_data_dict:
                continue

            # Among parallel edges, pick the one with the lowest normalized cost.
            best_edge = min(edge_data_dict.values(), key=edge_cost)
            tentative_g = g_curr + edge_cost(best_edge)

            if tentative_g < g_score.get(neighbor, float('inf')):
                g_score[neighbor] = tentative_g
                came_from[neighbor] = current
                heapq.heappush(open_set, (tentative_g + heuristic(neighbor), counter, neighbor))
                counter += 1

    if goal_node is None:
        return {"error": "Jalur tidak ditemukan."}

    # Reconstruct path by walking came_from backward from goal to start.
    path = []
    node = goal_node
    while node in came_from:
        path.append(node)
        node = came_from[node]
    path.append(node)
    path.reverse()

    if path[0][0] != start_stop or path[-1][0] != end_stop:
        return {"error": "Jalur tidak ditemukan lengkap."}

    final_metrics = calculate_final_metrics(G, path, weights)
    if "error" in final_metrics:
        return final_metrics

    detailed_journey = build_detailed_journey(G, path)
    halte_coordinates = build_path_coordinates(detailed_journey, path)

    return {
        "detailed_journey": detailed_journey,
        "path_coordinates": halte_coordinates,
        "jarak_km": final_metrics.get("jarak_km", 0),
        "waktu_tempuh_menit": final_metrics.get("waktu_tempuh_menit", 0),
        "total_biaya": final_metrics.get("total_biaya", 0),
        "jumlah_transit": final_metrics.get("jumlah_transit", 0),
        "z_score": final_metrics.get("z_score", 0),
    }
