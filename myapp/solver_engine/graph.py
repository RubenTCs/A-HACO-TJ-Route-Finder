import pandas as pd
import numpy as np
import networkx as nx
from math import radians, sin, cos, sqrt, asin
from datetime import time, datetime
from time import perf_counter
from scipy.spatial import cKDTree
from ..gtfs_helper import gtfsHelper
from ..constants import (
    T_MAX, C_MAX, P_MAX,
    DEFAULT_SPEED_KMH, MAX_WAIT_MIN,
    WALKING_SPEED_KMH, WALKING_RADIUS_M, KM_PER_DEGREE,
    FLAT_FARE_CLASSES, FREE_FARE_CLASSES,
    ECONOMY_FARE_CLASSES, ECONOMY_FARE_PRICE,
    ECONOMY_DISCOUNT_START, ECONOMY_DISCOUNT_END,
)

# Helpers
def _time_to_seconds(value):
    """Converts time to seconds"""
    if pd.isna(value):
        return None

    if isinstance(value, datetime):
        return value.hour * 3600 + value.minute * 60 + value.second

    if isinstance(value, time):
        return value.hour * 3600 + value.minute * 60 + value.second

    if isinstance(value, (int, float, np.integer, np.floating)):
        return int(value)

    parts = str(value).strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid time value: {value}")

    hours, minutes, seconds = map(int, parts)
    return hours * 3600 + minutes * 60 + seconds

# Euclidean distance in earth 
def haversine(lon1, lat1, lon2, lat2):
    """Calculate distance in km between two lon/lat points."""
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return 6371 * c  # in kilometers

def construct_graph_with_costs(depart_date=None,
                               depart_time=None,
                               speed_kmh=DEFAULT_SPEED_KMH,
                               max_wait_min=MAX_WAIT_MIN,
                               walking_speed_kmh=WALKING_SPEED_KMH,
                               walking_radius_m=WALKING_RADIUS_M):
    """
    Build the multigraph from GTFS data.

    speed_kmh: average vehicle speed used to derive Waktuij from shape_dist_traveled.
    max_wait_min: cap on expected boarding wait (headway / 2) applied to all transfer
        and walk edges. Routes with no headway data use this value as the wait.
    walking_speed_kmh: walking speed used to derive Waktuij for inter-stop GTFS transfers.
    walking_radius_m: max haversine distance for auto-generated walking edges between
        nearby stops on different routes (Google Maps-style first/last-mile coverage).
    """

    if depart_date is None:
        depart_date = datetime.now().date()
    if depart_time is None:
        depart_time = datetime.now().time()

    
    _t0 = perf_counter()

    try:
        # Load GTFS data (uses .copy jika ada accidental perubahan data agar cache tidak berubah)
        stops = gtfsHelper.stops.copy()
        stop_times = gtfsHelper.stop_times.copy()
        trips = gtfsHelper.trips.copy()
        calendar = gtfsHelper.calendar.copy()
        frequencies = gtfsHelper.frequencies.copy()
        fare_attributes = gtfsHelper.fare_attributes.copy()
        fare_rules = gtfsHelper.fare_rules.copy()
        transfer = gtfsHelper.transfer.copy()

        # Init Graph
        G = nx.MultiDiGraph()

        # ===============================================
        # region Fare Price
        # ===============================================

        # Build a route_id -> fare_id and route_id -> price lookup from fare_rules joined with fare_attributes.
        route_to_price = {}
        route_to_fare_id = {}
        fare_id_to_price = {}

        # Safety Check apakah kolom fare_id & route_id ada di fare rules 
        if ({"fare_id", "route_id"}.issubset(fare_rules.columns) & 
            {"fare_id", "price"}.issubset(fare_attributes.columns)): # dan kolom fare_id & price di fare_attributes
            
            # Map fare_id dengan price saja, Fallback jika error: 0 (SELECT fare_id, price if .... FROM fare_attribute)
            fare_price_map = (
                fare_attributes[["fare_id", "price"]]
                .dropna(subset=["fare_id"])
                .assign(price=lambda df: pd.to_numeric(df["price"], errors="coerce").fillna(0.0))
            )

            # Buat dict {"FP": 3500.0, "FP2": 3500.0, "GR": 0.0, "PP": 20000.0}
            fare_id_to_price = {str(r["fare_id"]): float(r["price"]) for _, r in fare_price_map.iterrows()}

            # Merge fare rule dengan fare_price (LEFT JOIN)
            fare_rules_enriched = (fare_rules[["fare_id", "route_id"]]
                                   .dropna(subset=["fare_id", "route_id"])
                                   .merge(
                                        fare_price_map,
                                        on="fare_id",
                                        how="left"
                                    )
            )

            # Buat dict {"1": 3500.0, "JAK.10": 0.0, "9D": 3500.0}
            route_to_price = {str(route_id): float(price) for route_id, price in 
                              fare_rules_enriched.groupby("route_id")["price"]
                              .max()
                              .fillna(0.0)
                              .items()}

            # Pick the highest-priced fare_id per route in case of duplicates (tho there isn't).
            for route_id, group in fare_rules_enriched.groupby("route_id"):
                top = group.sort_values("price", ascending=False).iloc[0]
                route_to_fare_id[str(route_id)] = str(top["fare_id"])

        # ------- Discount/Pricing logic ----------
        is_economy_discount_window = ECONOMY_DISCOUNT_START <= depart_time < ECONOMY_DISCOUNT_END
        if is_economy_discount_window:
            for fid in list(fare_id_to_price.keys()): # Ubah 3500 ke 2000 (FP, FP2)
                if fid in ECONOMY_FARE_CLASSES:
                    fare_id_to_price[fid] = ECONOMY_FARE_PRICE
            for rid, fid in route_to_fare_id.items(): # Ubah 3500 ke 2000 (FP, FP2)
                if fid in ECONOMY_FARE_CLASSES:
                    route_to_price[rid] = ECONOMY_FARE_PRICE
            print(f"INFO: Diskon jam pagi aktif ({depart_time}). FP/FP2 = Rp {int(ECONOMY_FARE_PRICE)}")

        # Store Boarding fare in graph, for easier lookup when needed by calculate_final_metrics, and other
        G.graph['route_to_price'] = route_to_price 
        G.graph['route_to_fare_id'] = route_to_fare_id # {"1": "FP", "6A": "FP", "JAK.10": "GR", "9D": "FP"}
        G.graph['fare_id_to_price'] = fare_id_to_price # {"FP": 3500.0, "FP2": 3500.0, "GR": 0.0, "PP": 20000.0}

        def transfer_fare(prev_fare_id, next_fare_id):
            """Cost (IDR) of boarding `next_fare_id` after a leg priced as `prev_fare_id`."""
            if not next_fare_id:
                return 0.0
            if next_fare_id in FREE_FARE_CLASSES: 
                # GR route
                return 0.0
            if next_fare_id in FLAT_FARE_CLASSES and prev_fare_id in FLAT_FARE_CLASSES:
                # Free transfer credit between FP/FP2 routes.
                return 0.0
            # Other route selain (FP, FP2, GR)
            return float(fare_id_to_price.get(next_fare_id, 0.0))
        
        # ===============================================
        # endregion
        # ===============================================

        # ===============================================
        # region Filter Active Route
        # ===============================================

        # Filter trips by service_id (which day is active)
        day_name = depart_date.strftime("%A").lower()
        active_service_ids = calendar.loc[
            calendar[day_name] == 1, "service_id"
        ].values
        
        # Trips berdasarkan service_id (basically yang aktif)
        trips_active_by_day = trips[trips["service_id"].isin(active_service_ids)]
        
        # Filter trips by departure time using frequencies
        depart_seconds = _time_to_seconds(depart_time)
        start_seconds = frequencies["start_time"].apply(_time_to_seconds)
        end_seconds = frequencies["end_time"].apply(_time_to_seconds)
        
        # Cari trip_id in time window
        trip_ids_in_time_window = frequencies.loc[
            (start_seconds <= depart_seconds) & (depart_seconds <= end_seconds),
            "trip_id"
        ].values
        
        # Active trips by trip_id from time window
        trips_active = trips_active_by_day[trips_active_by_day["trip_id"].isin(trip_ids_in_time_window)]
        
        # Merge stop_times with active trips to get route info
        stop_times_full = stop_times.merge(
            trips_active[["trip_id", "route_id"]],
            on="trip_id",
            how="inner"
        )
        
        # Merge stop_times with stops to get stops coordinates
        stop_times_full = stop_times_full.merge(
            stops[["stop_id", "stop_name", "stop_lat", "stop_lon"]],
            on="stop_id",
            how="inner"
        )
        
        # Sort by trip and stop_sequence
        stop_times_full = stop_times_full.sort_values(["trip_id", "stop_sequence"])
        
        # ===============================================
        # endregion
        # ===============================================

        # ===============================================
        # region Waiting time
        # ===============================================

        # untuk waktu tunggu tiap koridor
        # Build route -> min headway (minutes) active at departure time.
        # Used to model expected boarding wait as headway / 2.

        # Find active trips in frequency by using time (bisa pakai trips_active juga)
        freq_in_window = frequencies.loc[
            (start_seconds <= depart_seconds) & (depart_seconds <= end_seconds)
        ]

        route_to_headway_min = {}
        if not freq_in_window.empty:

            # merge freq with trips
            freq_with_route = freq_in_window.merge(
                trips[["trip_id", "route_id"]], 
                on="trip_id", 
                how="inner"
            ).copy()

            # ubah headway_secs ke numeric, fallback: nan
            # gtfs_kit infers headway_secs as Int16, Fix Error: Cast to float first, then recover original by adding 65536 to negatives.
            freq_with_route["headway_secs"] = pd.to_numeric(
                freq_with_route["headway_secs"], errors="coerce"
            ).astype("float64")
            neg_mask = freq_with_route["headway_secs"] < 0
            freq_with_route.loc[neg_mask, "headway_secs"] = (
                freq_with_route.loc[neg_mask, "headway_secs"] + 65536
            )

            # Buat dict route: headway
            min_hw = freq_with_route.groupby("route_id")["headway_secs"].min()
            route_to_headway_min = {
                str(k): float(v) / 60.0 for k, v in min_hw.items() if pd.notna(v)
            }
        
        # Store in Grpah, just incase it is needed for lookup
        G.graph['route_to_headway_min'] = route_to_headway_min

        def boarding_wait_min(route_id):
            """Expected wait for next bus on route_id: min(headway / 2, max_wait_min)."""
            h = route_to_headway_min.get(str(route_id))
            return min((h / 2.0) if h is not None else max_wait_min, max_wait_min)

        # ===============================================
        # endregion
        # ===============================================

        # ===============================================
        # region Construct graph (Connecting edges)
        # ===============================================

        stop_to_routes = {}
        
        # -------------------------------------- 
        # region travel edges 
        # --------------------------------------
        print("Building travel edges from GTFS...")
        
        # Build travel edges (consecutive stops on same trip)
        for trip_id, trip_data in stop_times_full.groupby("trip_id"):
            trip_data = trip_data.sort_values("stop_sequence")
            
            if len(trip_data) < 2:
                continue
            
            route_id = trip_data.iloc[0]["route_id"]
            
            # Track which stops are on which routes (by map "Stop": "list of koridor/route id")
            for stop_name in trip_data["stop_name"]:
                stop_to_routes.setdefault(stop_name, set()).add(route_id)
            
            # Create edges between consecutive stops
            for i in range(len(trip_data) - 1):
                curr_stop = trip_data.iloc[i]
                next_stop = trip_data.iloc[i + 1]
                
                node1 = (curr_stop["stop_name"], route_id)
                node2 = (next_stop["stop_name"], route_id)
                
                # Distance from shape_dist_traveled
                # fall back haversine if missing
                dist_curr = curr_stop.get("shape_dist_traveled")
                dist_next = next_stop.get("shape_dist_traveled")
                if pd.notna(dist_curr) and pd.notna(dist_next) and float(dist_next) > float(dist_curr):
                    dist_km = (float(dist_next) - float(dist_curr)) / 1000 # in meter to km
                else:
                    dist_km = haversine(
                        curr_stop["stop_lon"], curr_stop["stop_lat"],
                        next_stop["stop_lon"], next_stop["stop_lat"]
                    )

                # Travel time derived from distance and speed (Tabel 2.1).
                travel_time_min = (dist_km / speed_kmh) * 60

                G.add_edge(node1, node2, key=route_id,
                          type="travel",
                          Waktuij=travel_time_min,
                          Biayaij=0,
                          Transitij=0,
                          Waktuij_norm=travel_time_min / T_MAX,
                          Biayaij_norm=0.0,
                          Transitij_norm=0.0,
                          distance_km=dist_km)
        
        # -------------------------------------- 
        # endregion
        # --------------------------------------

        # -------------------------------------- 
        # region transfer edges 
        # --------------------------------------

        # Build transfer edges (between different routes at same stop)
        print("Building transfer edges...")
        for stop_name, route_ids in stop_to_routes.items():
            if len(route_ids) > 1:
                routes_list = list(route_ids)
                for i in range(len(routes_list)):
                    for j in range(i + 1, len(routes_list)):
                        node1 = (stop_name, routes_list[i])
                        node2 = (stop_name, routes_list[j])

                        # Charge fare based on the fare class of the destination route,with FP/FP2 free transfer credit and GR always free.
                        route_i = str(routes_list[i])
                        route_j = str(routes_list[j])
                        fare_id_i = route_to_fare_id.get(route_i)
                        fare_id_j = route_to_fare_id.get(route_j)

                        transfer_cost_ij = transfer_fare(fare_id_i, fare_id_j)
                        transfer_cost_ji = transfer_fare(fare_id_j, fare_id_i)
                        
                        # Use unique transfer key
                        transfer_key = f"transfer_{routes_list[i]}_to_{routes_list[j]}"
                        
                        # expected wait for next bus on destination route.
                        wait_ij = boarding_wait_min(routes_list[j])
                        wait_ji = boarding_wait_min(routes_list[i])

                        # Add transfer edge
                        G.add_edge(node1, node2, key=transfer_key,
                                  type="transfer",
                                  Waktuij=wait_ij,
                                  Biayaij=transfer_cost_ij,
                                  Transitij=1,
                                  Waktuij_norm=wait_ij / T_MAX,
                                  Biayaij_norm=transfer_cost_ij / C_MAX,
                                  Transitij_norm=1.0 / P_MAX,
                                  distance_km=0)

                        transfer_key_rev = f"transfer_{routes_list[j]}_to_{routes_list[i]}"
                        G.add_edge(node2, node1, key=transfer_key_rev,
                                  type="transfer",
                                  Waktuij=wait_ji,
                                  Biayaij=transfer_cost_ji,
                                  Transitij=1,
                                  Waktuij_norm=wait_ji / T_MAX,
                                  Biayaij_norm=transfer_cost_ji / C_MAX,
                                  Transitij_norm=1.0 / P_MAX,
                                  distance_km=0)
        # -------------------------------------- 
        # endregion 
        # --------------------------------------

        # -------------------------------------- 
        # region inter stop transfer edges 
        # --------------------------------------
        # Build inter-stop transfer edges from GTFS transfers
        print("Building inter-stop transfer edges from GTFS transfers...")
        inter_stop_transfer_edges = 0
        if {"from_stop_id", "to_stop_id"}.issubset(transfer.columns):
            # Make stop lookup based on stop_id to get name and coordinate of the s
            stop_lookup = (
                stops.drop_duplicates(subset=["stop_id"])
                     .set_index("stop_id")[["stop_name", "stop_lat", "stop_lon"]]
            )

            for _, row in transfer.iterrows():
                from_stop_id = row.get("from_stop_id")
                to_stop_id = row.get("to_stop_id")

                # Check stops null and exists in stop_lookup
                if pd.isna(from_stop_id) or pd.isna(to_stop_id):
                    continue
                if from_stop_id not in stop_lookup.index or to_stop_id not in stop_lookup.index:
                    continue

                # Get more infos
                from_info = stop_lookup.loc[from_stop_id]
                to_info = stop_lookup.loc[to_stop_id]
                from_name = from_info["stop_name"]
                to_name = to_info["stop_name"]

                if from_name == to_name:
                    continue

                # Hitung walking time
                walk_dist_km = haversine(
                    float(from_info["stop_lon"]), float(from_info["stop_lat"]),
                    float(to_info["stop_lon"]), float(to_info["stop_lat"])
                )
                walk_time_min = (walk_dist_km / walking_speed_kmh) * 60.0

                walk_base_min = walk_time_min

                # get the routes on each stop
                from_routes = stop_to_routes.get(from_name, set())
                to_routes = stop_to_routes.get(to_name, set())
                if not from_routes or not to_routes:
                    continue

                for route_a in from_routes:
                    for route_b in to_routes:
                        # Assign as node
                        node1 = (from_name, route_a)
                        node2 = (to_name, route_b)
                        if node1 == node2:
                            continue

                        total_time_min = walk_base_min + boarding_wait_min(route_b)
                        transfer_key = f"gtfs_transfer_{from_stop_id}_{route_a}_to_{to_stop_id}_{route_b}"
                        G.add_edge(node1, node2, key=transfer_key,
                                   type="transfer",
                                   Waktuij=total_time_min,
                                   Biayaij=0.0,
                                   Transitij=1,
                                   Waktuij_norm=total_time_min / T_MAX,
                                   Biayaij_norm=0.0,
                                   Transitij_norm=1.0 / P_MAX,
                                   distance_km=walk_dist_km)
                        inter_stop_transfer_edges += 1

        print(f"Inter-stop transfer edges added: {inter_stop_transfer_edges}")

        # -------------------------------------- 
        # endregion 
        # --------------------------------------

        # -------------------------------------- 
        # region walking edges 
        # --------------------------------------

        # Generate walking edges between stops on different routes within walking distance (walking_radius_m)
        # Similarly to inter-stop.
        print(f"Building walking transfer edges (radius {walking_radius_m:.0f} m)...")
        walking_radius_km = walking_radius_m / 1000.0

        # One coordinate per unique stop_name (graph nodes are keyed by name, not stop_id for easier debuggin).
        stop_coords = {}
        for _, row in stops[["stop_name", "stop_lat", "stop_lon"]].dropna().iterrows():
            name = row["stop_name"]

            # Set coordinate to stop_coords
            if name in stop_to_routes and name not in stop_coords:
                try:
                    stop_coords[name] = (float(row["stop_lat"]), float(row["stop_lon"]))
                except (TypeError, ValueError):
                    continue

        # Skip pairs already linked by a transfer/walk edge from the prior blocks
        # (GTFS transfers.txt).
        existing_pairs = set()
        for u, v, edge_data in G.edges(data=True):
            if edge_data.get("type") == "transfer" and u[0] != v[0]:
                existing_pairs.add(frozenset((u[0], v[0])))

        # Build a KD-Tree from all stop coordinates for fast spatial lookups.
        # A KD-Tree partitions points in space so that "find all pairs within distance R" runs in O(n log n) instead of O(n²) brute-force checks.
        stop_names = list(stop_coords.keys())
        coords_array = np.array([(lat, lon) for lat, lon in stop_coords.values()])

        # Convert walking radius from km to degrees (≈ KM_PER_DEGREE km per degree of latitude).
        radius_deg = walking_radius_km / KM_PER_DEGREE

        # query_pairs returns all (i, j) index pairs whose distance ≤ radius_deg.
        # Each pair is returned once (i < j), so no duplicates.
        tree = cKDTree(coords_array)
        candidate_pairs = tree.query_pairs(r=radius_deg)

        walking_edges_added = 0 # Counter
        for i, j in candidate_pairs:
            name_a, name_b = stop_names[i], stop_names[j]

            # Skip if these two stops already have a GTFS transfer edge 
            pair_key = frozenset((name_a, name_b))
            if pair_key in existing_pairs:
                continue

            # Confirm with haversine since degree-based radius is only approximate.
            lat_a, lon_a = stop_coords[name_a]
            lat_b, lon_b = stop_coords[name_b]
            dist_km = haversine(lon_a, lat_a, lon_b, lat_b)
            if dist_km > walking_radius_km:
                continue

            walk_time_min = (dist_km / walking_speed_kmh) * 60.0
            walk_base_min = walk_time_min

            # One physical stop pair => many node pairs (one per route combination).
            # We add both directions since walking is bidirectional.
            for route_a in stop_to_routes.get(name_a, ()):
                for route_b in stop_to_routes.get(name_b, ()):
                    if route_a == route_b:
                        continue
                    node1 = (name_a, route_a)
                    node2 = (name_b, route_b)

                    # Total time = walk + expected boarding wait for the destination route.
                    total_ab = walk_base_min + boarding_wait_min(route_b)
                    total_ba = walk_base_min + boarding_wait_min(route_a)

                    # key forward
                    key_fwd = f"walk_{name_a}_{route_a}_to_{name_b}_{route_b}"
                    G.add_edge(node1, node2, key=key_fwd,
                               type="walk",
                               Waktuij=total_ab,
                               Biayaij=0.0,
                               Transitij=0,
                               Waktuij_norm=total_ab / T_MAX,
                               Biayaij_norm=0.0,
                               Transitij_norm=0.0,
                               distance_km=dist_km)
                    # key reverse
                    key_rev = f"walk_{name_b}_{route_b}_to_{name_a}_{route_a}"
                    G.add_edge(node2, node1, key=key_rev,
                               type="walk",
                               Waktuij=total_ba,
                               Biayaij=0.0,
                               Transitij=0,
                               Waktuij_norm=total_ba / T_MAX,
                               Biayaij_norm=0.0,
                               Transitij_norm=0.0,
                               distance_km=dist_km)
                    walking_edges_added += 2

        print(f"Walking edges added: {walking_edges_added}")

        # -------------------------------------- 
        # endregion
        # --------------------------------------

        # ===============================================
        # endregion
        # ===============================================

        _elapsed = perf_counter() - _t0
        print(f"Graph built successfully! ({_elapsed:.2f}s)")
        print(f"Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}")
        print(f"Stops with multiple routes: {sum(1 for r in stop_to_routes.values() if len(r) > 1)}")
        
        return G, stop_to_routes
        
    except Exception as e:
        print(f"Internal Error: {str(e)}")
        return None, None

