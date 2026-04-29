import numpy as np
from math import radians, sin, cos, sqrt, asin
from ..gtfs_helper import gtfsHelper


def haversine(lon1, lat1, lon2, lat2):
    """Straight-line distance in km between two (lon, lat) points."""
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def build_coord_map():
    """Return {stop_name: (lat, lon)} for all stops in the GTFS feed."""
    coord_map = {}
    stops_df = gtfsHelper.stops
    if stops_df is None:
        return coord_map
    required = {"stop_name", "stop_lat", "stop_lon"}
    if not required.issubset(stops_df.columns):
        return coord_map
    for _, row in stops_df[["stop_name", "stop_lat", "stop_lon"]].dropna().iterrows():
        name = row["stop_name"]
        if name not in coord_map:
            try:
                coord_map[name] = (float(row["stop_lat"]), float(row["stop_lon"]))
            except (ValueError, TypeError):
                pass
    return coord_map


def _select_edge_data(edge_data):
    """Return a single edge-attribute dict for Graph/DiGraph/MultiDiGraph."""
    if not isinstance(edge_data, dict) or not edge_data:
        return {}

    # MultiGraph/MultiDiGraph: {key: {attr: value}}
    sample = next(iter(edge_data.values()), None)
    if isinstance(sample, dict):
        candidates = [v for v in edge_data.values() if isinstance(v, dict)]
        if not candidates:
            return {}
        return min(candidates, key=lambda e: e.get('Waktuij', float('inf')))

    # Graph/DiGraph: {attr: value}
    return edge_data

def parameter_validation():
    
    return None

def build_detailed_journey(G, path):
    """Builds detailed journey steps by grouping travel per corridor and explicit transfers"""
    detailed_route_steps = []
    if not path or len(path) < 2 :
        return detailed_route_steps
    
    travel_segment_nodes = []

    def filter_travel_segment(nodes_segment):
        # "Ubah rangkaian node satu koridor menjadi 1 langkah "travel"
        if len(nodes_segment) < 2: 
            return
            
        start_node = nodes_segment[0]
        end_node = nodes_segment[-1]
        corridor = start_node[1]
        halte_names = [n[0] for n in nodes_segment]

        step = {
            "type": "travel", 
            "koridor": corridor, 
            "from": halte_names[0], 
            "to": halte_names[-1], 
            "via": halte_names[1:-1]
        }
        detailed_route_steps.append(step)

    for u, v in zip(path, path[1:]):
        if not G.has_edge(u, v):
            continue

        edge_data = _select_edge_data(G.get_edge_data(u,v))
        edge_type = edge_data.get('type', 'travel')

        if edge_type == 'travel':
            # Lanjutkan segmen jika masih di koridor yang sama, jika beda koridor maka flush segmen lama
            if not travel_segment_nodes: 
                travel_segment_nodes = [u, v]
                continue

            current_corridor = u[1]
            segment_corridor = travel_segment_nodes[0][1]

            if current_corridor == segment_corridor:
                travel_segment_nodes.append(v)
            else: 
                filter_travel_segment(travel_segment_nodes)
                travel_segment_nodes = [u, v]
        else:  # edge_type == 'transfer'
            # Transfer disimpan sebagai langkah terpisah antar koridor di halte yang sama.
            filter_travel_segment(travel_segment_nodes)
            travel_segment_nodes = []

            step = {
                "type": "transfer",
                "halte": u[0],
                "from_koridor": u[1],
                "to_koridor": v[1]
            }
            detailed_route_steps.append(step)

    filter_travel_segment(travel_segment_nodes)
    return detailed_route_steps

def build_path_coordinates(detailed_journey, path):
    """Build path coordinates from GTFS stop coordinates and journey steps."""
    path_coordinates = []

    def to_coord_list(coord_value):
        # Normalize to [lat, lon] float list; return None for invalid input.
        if not isinstance(coord_value, (tuple, list)) or len(coord_value) != 2:
            return None
        try:
            lat = float(coord_value[0])
            lon = float(coord_value[1])
            return [lat, lon]
        except (ValueError, TypeError):
            return None

    def append_unique_coord(coord):
        # Avoid duplicate consecutive coordinates in the polyline.
        if coord and (not path_coordinates or path_coordinates[-1] != coord):
            path_coordinates.append(coord)

    def attach_step_coordinates(step, coord_map):
        # Attach coordinates directly to each journey step.
        start_coord = coord_map.get(step.get("from"))
        end_coord = coord_map.get(step.get("to"))
        transfer_coord = coord_map.get(step.get("halte"))

        step["coords_from"] = to_coord_list(start_coord)
        step["coords_to"] = to_coord_list(end_coord)
        step["coords"] = to_coord_list(transfer_coord)

    try:
        # Step 1: Load stop coordinates once.
        print("INFO (PathCoords): Building stop coordinate map...")
        coordinates_map = build_coord_map()
        print(f"INFO (PathCoords): Loaded {len(coordinates_map)} stop coordinates")

        journey_steps = detailed_journey if isinstance(detailed_journey, list) else []

        for step in journey_steps:
            if not isinstance(step, dict):
                continue

            # Step 2: Add coordinates detail to journey detail
            attach_step_coordinates(step, coordinates_map)

            if step.get("type") == "travel":
                # Step 3a: Build travel polyline by ordered stops (from -> via -> to).
                travel_stop_names = [step.get("from")] + list(step.get("via") or []) + [step.get("to")]
                for stop_name in travel_stop_names:
                    if not stop_name:
                        continue
                    append_unique_coord(to_coord_list(coordinates_map.get(stop_name)))
                continue

            if step.get("type") == "transfer":
                # Step 3b: Transfer contributes a single stop coordinate.
                append_unique_coord(step.get("coords"))

        if not path_coordinates and isinstance(path, list):
            # Step 4: Fallback to node path sequence when journey polyline is empty.
            print("INFO (PathCoords): Using fallback from node path sequence")
            for node_data in path:
                if isinstance(node_data, tuple) and len(node_data) > 0:
                    stop_name = node_data[0]
                elif isinstance(node_data, str):
                    stop_name = node_data
                else:
                    stop_name = None

                if not stop_name:
                    continue

                append_unique_coord(to_coord_list(coordinates_map.get(stop_name)))

        print(f"INFO (PathCoords): Final coordinate points: {len(path_coordinates)}")

    except Exception as e:
        print(f"ERROR (PathCoords): {type(e).__name__} - {e}")
        path_coordinates = []

    return [
        coord for coord in path_coordinates
        if isinstance(coord, list) and len(coord) == 2 and all(isinstance(value, (int, float)) for value in coord)
    ]

def calculate_final_metrics(G, path, weights):
    """
    Calculate total time, distance, and transit count from a path.

    Parameters:
    -----------
    G : nx.MultiDiGraph
        Transport network graph
    path : list
        Path of nodes

    Returns:
    --------
    dict with metrics (waktu_tempuh_menit, jarak_km, jumlah_transit)
    """
    total_dist = 0.0
    total_time = 0.0  # in minutes (raw, for display)
    total_trans = 0
    total_cost = 0.0
    z_score = 0.0

    w_t_input = float(weights.get('waktu', 0))
    w_c_input = float(weights.get('biaya', 0))
    w_p_input = float(weights.get('transit', 0))

    if not path or len(path) < 2:
        return {"waktu_tempuh_menit": 0, "jarak_km": 0, "jumlah_transit": 0, "error": "Path tidak valid"}

    for u, v in zip(path, path[1:]):
        if not G.has_edge(u, v):
            print(f"WARNING: Edge tidak ditemukan di path: {u} -> {v}")
            continue

        # MultiDiGraph: get_edge_data returns dict of {key: edge_data}
        edge_data_dict = G.get_edge_data(u, v)

        if isinstance(edge_data_dict, dict) and edge_data_dict:
            edge_data = min(edge_data_dict.values(), key=lambda e: e.get('Waktuij', float('inf')))
        else:
            print(f"WARNING: No edge data found for {u} -> {v}")
            continue

        # Accumulate raw metrics for display
        total_time += edge_data.get('Waktuij', 0)
        total_dist += edge_data.get('distance_km', 0)
        total_cost += edge_data.get('Biayaij', 0)

        if edge_data.get('type') == 'transfer':
            total_trans += 1

        # Z-score uses normalized values to match the MILP/A*/HACO objective (eq 2.1)
        z_score += (
            w_t_input * edge_data.get('Waktuij_norm', 0) +
            w_c_input * edge_data.get('Biayaij_norm', 0) +
            w_p_input * edge_data.get('Transitij', 0)
        )

    return {
        "waktu_tempuh_menit": round(total_time, 1),
        "jarak_km": round(total_dist, 2),
        "total_biaya": round(total_cost, 0),
        "jumlah_transit": total_trans,
        "z_score": round(z_score, 6)
    }
