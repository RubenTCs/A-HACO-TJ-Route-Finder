import heapq

from .utils import (
    haversine,
    build_coord_map,
    calculate_final_metrics,
    build_detailed_journey,
    build_path_coordinates,
)
from ..constants import (
    T_MAX,
    DEFAULT_SPEED_KMH,
)


# ==========================================================
# Cost / heuristic primitives
# ==========================================================

def _edge_cost(edge_data, w_t, w_c, w_p):
    return (
        w_t * edge_data.get('Waktuij_norm', 0) +
        w_c * edge_data.get('Biayaij_norm', 0) +
        w_p * edge_data.get('Transitij_norm', 0)
    )


def _make_heuristic(coord_map, end_stop, w_t, speed_kmh):
    """Return h(node) => admissible lower bound on remaining time-cost."""
    end_coords = coord_map.get(end_stop)

    def h(node):
        if end_coords is None:
            return 0.0
        coords = coord_map.get(node[0])
        if coords is None:
            return 0.0
        dist_km = haversine(coords[1], coords[0], end_coords[1], end_coords[0])
        return w_t * dist_km * 60.0 / (speed_kmh * T_MAX)  # 60.0 = seconds per minute

    return h


# ==========================================================
# A* search
# ==========================================================

def _astar_search(G, start_nodes, end_nodes_set, heuristic, w_t, w_c, w_p):
    """Run A* and return (goal_node, came_from). goal_node is None if unreachable."""
    g_score = {}
    came_from = {}
    open_set = []
    counter = 0  # heap tiebreak

    # --- 1. Inisialisasi ---
    # Setiap start node (satu per rute di halte asal) dimasukkan ke open list.
    # g(n) awal = 0; biaya naik bus pertama sudah ditempel ke travel edge yang
    # keluar dari halte asal oleh apply_terminal_walk_policy().
    # f(n) awal = g(n) + h(n), di mana h(n) = estimasi sisa waktu ke tujuan.
    for s in start_nodes:
        g_score[s] = 0.0
        heapq.heappush(open_set, (g_score[s] + heuristic(s), counter, s))  # f(n) = g(n) + h(n)
        counter += 1

    closed_set = set()

    while open_set:
        # --- 2. Pemilihan node ---
        # Ambil node dengan f(n) terkecil dari open list
        # Pindahkan ke closed list agar tidak diproses ulang.
        _, _, current = heapq.heappop(open_set)

        if current in closed_set:
            continue
        closed_set.add(current)

        # --- 3. Pemeriksaan tujuan ---
        # Jika node saat ini adalah halte tujuan, hentikan pencarian.
        # Jalur optimal direkonstruksi via backtracing pada came_from.
        if current in end_nodes_set:
            return current, came_from

        # --- 4. Ekspansi node tetangga ---
        # Evaluasi semua tetangga yang terhubung langsung dari node saat ini.
        g_curr = g_score[current]
        for neighbor in G.successors(current):
            if neighbor in closed_set:
                continue
            edict = G.get_edge_data(current, neighbor)
            if not edict:
                continue
            # Multigraph: pilih edge terkecil/termurah dari semua parallel edge.
            best_edge = min(edict.values(), key=lambda e: _edge_cost(e, w_t, w_c, w_p))
            tentative_g = g_curr + _edge_cost(best_edge, w_t, w_c, w_p)  # g_baru = g_lama + bobot_jalur

            # Jika g_baru lebih kecil, perbarui node tetangga dan masukkan ke open list.
            if tentative_g < g_score.get(neighbor, float('inf')):
                g_score[neighbor] = tentative_g
                came_from[neighbor] = current
                heapq.heappush(open_set, (tentative_g + heuristic(neighbor), counter, neighbor))  # f_baru = g_baru + h(n)
                counter += 1

    # --- 5. Iterasi ---
    # Loop while open_set di atas mengulang langkah 2-4 hingga tujuan ditemukan
    # atau open list kosong (jalur tidak ada).
    return None, came_from


def _reconstruct_path(goal_node, came_from):
    """Backtrack from goal to the original start node via came_from, then reverse to get the full path."""
    path = []
    node = goal_node
    while node in came_from:
        path.append(node)
        node = came_from[node]
    path.append(node)
    path.reverse()
    return path


# ==========================================================
# Main solver
# ==========================================================

def find_path_with_astar(G, stop_to_routes, start_stop, end_stop, weights, speed_kmh=DEFAULT_SPEED_KMH):
    """Find optimal route via A* on the multigraph."""
    print("--- Start find route with A* ---")

    # --- Validate inputs ---
    if start_stop not in stop_to_routes:
        return {"error": f"Halte Asal '{start_stop}' tidak dilayani angkutan pada jam yang dipilih."}
    if end_stop not in stop_to_routes:
        return {"error": f"Halte Tujuan '{end_stop}' tidak dilayani angkutan pada jam yang dipilih."}

    start_nodes = [n for n in G.nodes() if n[0] == start_stop]
    end_nodes_set = {n for n in G.nodes() if n[0] == end_stop} # TODO: Debug/Test this
    if not start_nodes or not end_nodes_set:
        return {"error": "Node asal atau tujuan tidak terhubung ke graf."}

    w_t = float(weights.get('waktu', 0))
    w_c = float(weights.get('biaya', 0))
    w_p = float(weights.get('transit', 0))

    # --- Run search ---
    coord_map = build_coord_map()
    heuristic = _make_heuristic(coord_map, end_stop, w_t, speed_kmh)
    goal_node, came_from = _astar_search(G, start_nodes, end_nodes_set, heuristic, w_t, w_c, w_p)

    if goal_node is None:
        return {"error": "Jalur tidak ditemukan."}

    path = _reconstruct_path(goal_node, came_from)
    if path[0][0] != start_stop or path[-1][0] != end_stop:
        return {"error": "Jalur tidak ditemukan lengkap."}

    final_metrics = calculate_final_metrics(G, path, weights)
    if "error" in final_metrics:
        return final_metrics

    detailed_journey = build_detailed_journey(G, path)
    coord_result = build_path_coordinates(detailed_journey, path)

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
