"""
Utils/Helper
"""

from math import radians, sin, cos, sqrt, asin
from ..gtfs_helper import gtfsHelper
from ..constants import (
    C_MAX,
    DEFAULT_ROUTE_COLOR,
    WALKING_COLOR,
    WALKING_SPEED_KMH,
    WALKING_FALLBACK_MAX_DISTANCE_KM,
    FREE_FARE_CLASSES,
)


def get_boarding_fare(G, node):
    """Return (raw_idr, normalized) boarding fare for the route encoded in `node`.

    `node` is the (stop_name, route_id) tuple at the start of a path. Travel edges
    carry Biayaij=0, so the first-corridor fare must be added separately to keep
    the optimizer's objective and the displayed total honest.
    """
    if not (isinstance(node, tuple) and len(node) > 1):
        return 0.0, 0.0
    route_id = str(node[1])
    route_to_fare_id = G.graph.get('route_to_fare_id', {})
    if route_to_fare_id.get(route_id) in FREE_FARE_CLASSES:
        return 0.0, 0.0
    route_to_price = G.graph.get('route_to_price', {})
    price = float(route_to_price.get(route_id, 0.0))
    return price, price / C_MAX


def haversine(lon1, lat1, lon2, lat2):
    """Straight-line distance in km between two (lon, lat) points."""
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1 
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def build_route_shape_map():
    """Build {route_id: [{shape_id, stop_dist: {stop_name: dist}}]} from GTFS trips/stop_times.

    Multiple entries per route cover different directions (each has a distinct shape_id).
    One representative trip per (route_id, shape_id) pair is enough because all trips
    sharing the same shape have identical shape_dist_traveled values at each stop.
    """
    trips_df = gtfsHelper.trips
    stop_times_df = gtfsHelper.stop_times
    stops_df = gtfsHelper.stops

    if trips_df is None or stop_times_df is None or stops_df is None:
        return {}
    if 'shape_id' not in trips_df.columns:
        return {}

    trips_with_shape = trips_df[trips_df['shape_id'].notna()][['route_id', 'trip_id', 'shape_id']]
    if trips_with_shape.empty:
        return {}

    required_st = {'trip_id', 'stop_id', 'shape_dist_traveled'}
    if not required_st.issubset(stop_times_df.columns) or 'stop_name' not in stops_df.columns:
        return {}

    st_named = (
        stop_times_df[['trip_id', 'stop_id', 'stop_sequence', 'shape_dist_traveled']]
        .merge(stops_df[['stop_id', 'stop_name']], on='stop_id', how='inner')
    )

    result = {}
    for route_id, group in trips_with_shape.groupby('route_id'):
        entries = []
        seen_shapes = set()
        for _, row in group.iterrows():
            shape_id = str(row['shape_id'])
            if shape_id in seen_shapes:
                continue
            seen_shapes.add(shape_id)

            trip_stops = (
                st_named[st_named['trip_id'] == row['trip_id']]
                .dropna(subset=['shape_dist_traveled'])
                .sort_values('stop_sequence')
            )
            if trip_stops.empty:
                continue

            stop_dist = {}
            for _, sr in trip_stops.iterrows():
                name = str(sr['stop_name'])
                if name not in stop_dist:
                    stop_dist[name] = float(sr['shape_dist_traveled'])

            entries.append({'shape_id': shape_id, 'stop_dist': stop_dist})

        if entries:
            result[str(route_id)] = entries

    return result


def _get_shape_segment_coords(shapes_df, shape_id, dist_from, dist_to):
    """Return [[lat, lon], ...] shape points between dist_from and dist_to for shape_id."""
    lo, hi = min(dist_from, dist_to), max(dist_from, dist_to)
    seg = shapes_df[
        (shapes_df['shape_id'] == shape_id) &
        (shapes_df['shape_dist_traveled'] >= lo) &
        (shapes_df['shape_dist_traveled'] <= hi)
    ].sort_values('shape_pt_sequence')

    if dist_from > dist_to:
        seg = seg.iloc[::-1]

    return [
        [float(r['shape_pt_lat']), float(r['shape_pt_lon'])]
        for _, r in seg.iterrows()
    ]


def _find_shape_for_segment(route_id, from_stop, to_stop, route_shape_map):
    """Return (shape_id, dist_from, dist_to) for a travel segment, or (None, None, None)."""
    for entry in route_shape_map.get(str(route_id), []):
        stop_dist = entry['stop_dist']
        dist_from = stop_dist.get(from_stop)
        dist_to = stop_dist.get(to_stop)
        if dist_from is not None and dist_to is not None:
            return entry['shape_id'], dist_from, dist_to
    return None, None, None


def build_route_color_map():
    """Return {route_id: '#RRGGBB'} from GTFS routes, defaulting to blue."""
    routes_df = gtfsHelper.routes
    DEFAULT = DEFAULT_ROUTE_COLOR
    if routes_df is None or 'route_color' not in routes_df.columns or 'route_id' not in routes_df.columns:
        return {}
    result = {}
    for _, row in routes_df[['route_id', 'route_color']].dropna(subset=['route_id']).iterrows():
        color_val = row.get('route_color')
        s = str(color_val).strip() if color_val is not None else ''
        if s and s.lower() not in ('nan', 'none', ''):
            result[str(row['route_id'])] = '#' + s.lstrip('#')
        else:
            result[str(row['route_id'])] = DEFAULT
    return result


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


def compute_walking_only_route(start_stop, end_stop, walking_speed_kmh=WALKING_SPEED_KMH,
                               max_distance_km=WALKING_FALLBACK_MAX_DISTANCE_KM):
    """Build a walking-only route between two halte if within max_distance_km.

    Used as a fallback when the transit solver finds no path but the two halte
    are close enough that walking is a sensible alternative. Returns a result
    dict shaped like a solver output (so the same UI/render pipeline works), or
    None when walking isn't feasible (halte unknown or too far).
    """
    coord_map = build_coord_map()
    start_coord = coord_map.get(start_stop)
    end_coord = coord_map.get(end_stop)
    if start_coord is None or end_coord is None:
        return None

    # build_coord_map stores (lat, lon); haversine expects (lon, lat).
    dist_km = haversine(start_coord[1], start_coord[0], end_coord[1], end_coord[0])
    if dist_km > max_distance_km:
        return None

    duration_min = (dist_km / walking_speed_kmh) * 60.0
    from_coord = [float(start_coord[0]), float(start_coord[1])]
    to_coord = [float(end_coord[0]), float(end_coord[1])]

    walk_step = {
        "type": "walk",
        "from_halte": start_stop,
        "to_halte": end_stop,
        "from_koridor": "walk",
        "to_koridor": "walk",
        "distance_km": dist_km,
        "duration_min": duration_min,
        "coords_from": from_coord,
        "coords_to": to_coord,
    }

    path_segment = {
        "coords": [from_coord, to_coord],
        "color": WALKING_COLOR,
        "koridor": "walk",
        "dashed": True,
    }

    return {
        "detailed_journey": [walk_step],
        "path_coordinates": [from_coord, to_coord],
        "path_segments": [path_segment],
        "jarak_km": round(dist_km, 2),
        "waktu_tempuh_menit": round(duration_min, 1),
        "total_biaya": 0,
        "jumlah_transit": 0,
        "z_score": 0,
        "is_walking_only": True,
    }


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
        elif edge_type == 'walk':
            # Walk antar halte berbeda — perlu both endpoints supaya peta bisa
            # menggambar garis jalan kaki.
            filter_travel_segment(travel_segment_nodes)
            travel_segment_nodes = []

            step = {
                "type": "walk",
                "from_halte": u[0],
                "to_halte": v[0],
                "from_koridor": u[1],
                "to_koridor": v[1],
                "distance_km": edge_data.get('distance_km', 0),
                "duration_min": edge_data.get('Waktuij', 0),
            }
            detailed_route_steps.append(step)
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
    """Build path coordinates from GTFS shapes/stops and journey steps.

    Returns a dict:
        path_coordinates  - flat [[lat,lon],...] for the whole route (fallback use)
        path_segments     -[{coords, color, koridor},...] one entry per travel step
    """
    path_coordinates = []
    path_segments = []

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
        # Walk steps use from_halte/to_halte instead of from/to.
        from_name = step.get("from") or step.get("from_halte")
        to_name = step.get("to") or step.get("to_halte")
        start_coord = coord_map.get(from_name)
        end_coord = coord_map.get(to_name)
        transfer_coord = coord_map.get(step.get("halte"))

        step["coords_from"] = to_coord_list(start_coord)
        step["coords_to"] = to_coord_list(end_coord)
        step["coords"] = to_coord_list(transfer_coord)

    try:
        # Step 1: Load stop coordinates and GTFS shape data once.
        print("INFO (PathCoords): Building stop coordinate map...")
        coordinates_map = build_coord_map()
        print(f"INFO (PathCoords): Loaded {len(coordinates_map)} stop coordinates")

        print("INFO (PathCoords): Building route shape map...")
        route_shape_map = build_route_shape_map()
        shapes_df = gtfsHelper.shapes
        use_shapes = shapes_df is not None and not shapes_df.empty and bool(route_shape_map)
        print(f"INFO (PathCoords): Shape data available: {use_shapes} ({len(route_shape_map)} routes)")

        route_color_map = build_route_color_map()

        journey_steps = detailed_journey if isinstance(detailed_journey, list) else []

        for step in journey_steps:
            if not isinstance(step, dict):
                continue

            # Step 2: Add coordinates detail to journey detail
            attach_step_coordinates(step, coordinates_map)

            if step.get("type") == "travel":
                from_stop = step.get("from")
                to_stop = step.get("to")
                via_stops = list(step.get("via") or [])
                route_id = step.get("koridor")
                color = route_color_map.get(str(route_id), DEFAULT_ROUTE_COLOR)

                step_coords = []
                shape_used = False
                if use_shapes and route_id:
                    # Step 3a: Use GTFS shape geometry for accurate route geometry.
                    all_stops = [from_stop] + via_stops + [to_stop]
                    segment_ok = True

                    for seg_from, seg_to in zip(all_stops, all_stops[1:]):
                        if not seg_from or not seg_to:
                            segment_ok = False
                            break
                        shape_id, dist_f, dist_t = _find_shape_for_segment(
                            route_id, seg_from, seg_to, route_shape_map
                        )
                        if shape_id is None:
                            segment_ok = False
                            break
                        step_coords.extend(
                            _get_shape_segment_coords(shapes_df, shape_id, dist_f, dist_t)
                        )

                    if segment_ok and step_coords:
                        shape_used = True

                if not shape_used:
                    # Step 3b: Fallback — connect stop coordinates with straight lines.
                    for stop_name in [from_stop] + via_stops + [to_stop]:
                        if not stop_name:
                            continue
                        c = to_coord_list(coordinates_map.get(stop_name))
                        if c:
                            step_coords.append(c)

                valid_step_coords = [
                    c for c in step_coords
                    if isinstance(c, list) and len(c) == 2
                ]
                if valid_step_coords:
                    path_segments.append({
                        "coords": valid_step_coords,
                        "color": color,
                        "koridor": route_id,
                    })
                    for coord in valid_step_coords:
                        append_unique_coord(coord)
                continue

            if step.get("type") == "transfer":
                # Step 3c: Transfer contributes a single stop coordinate.
                append_unique_coord(step.get("coords"))
                continue

            if step.get("type") == "walk":
                # Step 3d: Walk segment connects two different stops with a straight line.
                from_coord = step.get("coords_from")
                to_coord = step.get("coords_to")
                if from_coord and to_coord:
                    path_segments.append({
                        "coords": [from_coord, to_coord],
                        "color": WALKING_COLOR,
                        "koridor": "walk",
                        "dashed": True,
                    })
                    append_unique_coord(from_coord)
                    append_unique_coord(to_coord)

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
        path_segments = []

    valid_coords = [
        c for c in path_coordinates
        if isinstance(c, list) and len(c) == 2 and all(isinstance(v, (int, float)) for v in c)
    ]
    return {"path_coordinates": valid_coords, "path_segments": path_segments}


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
    total_cost = 0.0
    z_score = 0.0

    w_t_input = float(weights.get('waktu', 0))
    w_c_input = float(weights.get('biaya', 0))
    w_p_input = float(weights.get('transit', 0))

    if not path or len(path) < 2:
        return {"waktu_tempuh_menit": 0, "jarak_km": 0, "jumlah_transit": 0, "error": "Path tidak valid"}

    # Boarding fare for the first corridor. travel edges carry Biayaij=0,
    # so without this the displayed cost is 0 for any single-corridor route.
    # Apply it to z_score too so the displayed objective matches what each
    # solver now optimizes (boarding fare is added per start node).
    boarding_raw, boarding_norm = get_boarding_fare(G, path[0])
    total_cost += boarding_raw
    z_score += w_c_input * boarding_norm

    # Track routes actually ridden (from travel edges) to count real transits.
    # A transit is when the ridden route changes — a walk to the final stop
    # without boarding another bus does not count.
    traveled_routes = []

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

        if edge_data.get('type') == 'travel' and isinstance(u, tuple):
            route = u[1]
            if not traveled_routes or traveled_routes[-1] != route:
                traveled_routes.append(route)

        # Z-score uses normalized values to match the MILP/A*/HACO objective (eq 2.1)
        z_score += (
            w_t_input * edge_data.get('Waktuij_norm', 0) +
            w_c_input * edge_data.get('Biayaij_norm', 0) +
            w_p_input * edge_data.get('Transitij_norm', 0)
        )

    # Transit = number of route changes actually ridden (segments - 1)
    total_trans = max(0, len(traveled_routes) - 1)

    return {
        "waktu_tempuh_menit": round(total_time, 1),
        "jarak_km": round(total_dist, 2),
        "total_biaya": round(total_cost, 0),
        "jumlah_transit": total_trans,
        "z_score": round(z_score, 6)
    }
