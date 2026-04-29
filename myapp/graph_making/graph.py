import pandas as pd
import numpy as np
import networkx as nx
from math import radians, sin, cos, sqrt, asin
from datetime import time, datetime
import gurobipy as gp
import warnings, os, re, itertools
import numpy as np
from ..gtfs_helper import gtfsHelper

def _time_to_seconds(value):
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

# -- Construct Graph --
T_MAX = 360.0    # max travel time in minutes
C_MAX = 35000.0  # max fare in IDR

def construct_graph_with_costs(depart_date=None, depart_time=None, speed_kmh=25.0, avg_transfer_min=5.0):
    """
    Build the multigraph from GTFS data.

    speed_kmh: average vehicle speed used to derive Waktuij from shape_dist_traveled.
    avg_transfer_min: penalty time applied to transfer edges between routes at the same stop.
    """

    if depart_date is None:
        depart_date = datetime.now().date()
    if depart_time is None:
        depart_time = datetime.now().time()
    
    try:
        # Load GTFS data (uses .copy jika ada accidental perubahan data agar cache tidak berubah)
        stops = gtfsHelper.stops.copy()
        stop_times = gtfsHelper.stop_times.copy()
        trips = gtfsHelper.trips.copy()
        routes = gtfsHelper.routes.copy()
        calendar = gtfsHelper.calendar.copy()
        frequencies = gtfsHelper.frequencies.copy()
        fare_attributes = gtfsHelper.fare_attributes.copy()
        fare_rules = gtfsHelper.fare_rules.copy()
        transfer = gtfsHelper.transfer.copy()

        # Map each route_id to its corridor/route_desc so transfer checks can compare service types.
        route_to_desc = {}
        if {"route_id", "route_desc"}.issubset(routes.columns):
            route_to_desc = {
                str(route_id): route_desc
                for route_id, route_desc in routes[["route_id", "route_desc"]].dropna(subset=["route_id"]).itertuples(index=False)
            }

        # Build a route_id -> fare price lookup from fare_rules joined with fare_attributes.
        route_to_price = {}
        if {"fare_id", "route_id"}.issubset(fare_rules.columns) and {"fare_id", "price"}.issubset(fare_attributes.columns):
            fare_price_map = (
                fare_attributes[["fare_id", "price"]]
                .dropna(subset=["fare_id"])
                .assign(price=lambda df: pd.to_numeric(df["price"], errors="coerce").fillna(0.0))
            )

            fare_rules_enriched = fare_rules[["fare_id", "route_id"]].dropna(subset=["fare_id", "route_id"]).merge(
                fare_price_map,
                on="fare_id",
                how="left"
            )

            route_to_price = (
                fare_rules_enriched.groupby("route_id")["price"].max().fillna(0.0).to_dict()
            )

            route_to_price = {str(route_id): float(price) for route_id, price in route_to_price.items()}
        
        # Filter trips by service_id (which day is active)
        day_name = depart_date.strftime("%A").lower()
        active_service_ids = calendar.loc[
            calendar[day_name] == 1, "service_id"
        ].values
        
        trips_active_by_day = trips[trips["service_id"].isin(active_service_ids)]
        
        # Filter trips by departure time using frequencies
        depart_seconds = _time_to_seconds(depart_time)
        start_seconds = frequencies["start_time"].apply(_time_to_seconds)
        end_seconds = frequencies["end_time"].apply(_time_to_seconds)
        
        trip_ids_in_time_window = frequencies.loc[
            (start_seconds <= depart_seconds) & (depart_seconds <= end_seconds),
            "trip_id"
        ].values
        
        trips_active = trips_active_by_day[trips_active_by_day["trip_id"].isin(trip_ids_in_time_window)]
        
        # Merge stop_times with trips to get route info
        stop_times_full = stop_times.merge(
            trips_active[["trip_id", "route_id"]],
            on="trip_id",
            how="inner"
        )
        
        # Merge with stops to get coordinates
        stop_times_full = stop_times_full.merge(
            stops[["stop_id", "stop_name", "stop_lat", "stop_lon"]],
            on="stop_id",
            how="inner"
        )
        
        # Sort by trip and stop_sequence
        stop_times_full = stop_times_full.sort_values(["trip_id", "stop_sequence"])
        
        # Init Graph
        G = nx.MultiDiGraph()
        stop_to_routes = {}
        transfer_time_min = float(avg_transfer_min)
        
        print("Building travel edges from GTFS...")
        
        # Build travel edges (consecutive stops on same trip)
        for trip_id, trip_data in stop_times_full.groupby("trip_id"):
            trip_data = trip_data.sort_values("stop_sequence")
            
            if len(trip_data) < 2:
                continue
            
            route_id = trip_data.iloc[0]["route_id"]
            
            # Track which stops are on which routes
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
                    dist_km = (float(dist_next) - float(dist_curr)) / 1000.0 # in meter to km
                else:
                    dist_km = haversine(
                        curr_stop["stop_lon"], curr_stop["stop_lat"],
                        next_stop["stop_lon"], next_stop["stop_lat"]
                    )

                # Travel time derived from distance and speed (Tabel 2.1 in proposal).
                travel_time_min = (dist_km / speed_kmh) * 60

                G.add_edge(node1, node2, key=route_id,
                          type="travel",
                          Waktuij=travel_time_min,
                          Biayaij=0,
                          Transitij=0,
                          Waktuij_norm=travel_time_min / T_MAX,
                          Biayaij_norm=0.0,
                          distance_km=dist_km)
        
        # Build transfer edges (between different routes at same stop, dan perpindahan moda kendaraan)
        print("Building transfer edges...")
        for stop_name, route_ids in stop_to_routes.items():
            if len(route_ids) > 1:
                routes_list = list(route_ids)
                for i in range(len(routes_list)):
                    for j in range(i + 1, len(routes_list)):
                        node1 = (stop_name, routes_list[i])
                        node2 = (stop_name, routes_list[j])

                        # Compare dua koridor/rute untuk aturan pengaplikasian biaya tarif.
                        route_i = str(routes_list[i])
                        route_j = str(routes_list[j])
                        route_desc_i = route_to_desc.get(route_i)
                        route_desc_j = route_to_desc.get(route_j)

                        # tarif default jika berada di rute yang sama/rute
                        transfer_cost_ij = 0.0
                        transfer_cost_ji = 0.0

                        # If the corridor changes, charge the fare of the destination route.
                        if route_i != route_j and route_desc_i and route_desc_j and route_desc_i != route_desc_j:
                            transfer_cost_ij = route_to_price.get(route_j, 0.0)
                            transfer_cost_ji = route_to_price.get(route_i, 0.0)
                        
                        # Use unique transfer key
                        transfer_key = f"transfer_{routes_list[i]}_to_{routes_list[j]}"
                        
                        # Add transfer edge
                        G.add_edge(node1, node2, key=transfer_key,
                                  type="transfer",
                                  Waktuij=transfer_time_min,
                                  Biayaij=transfer_cost_ij,
                                  Transitij=1,
                                  Waktuij_norm=transfer_time_min / T_MAX,
                                  Biayaij_norm=transfer_cost_ij / C_MAX,
                                  distance_km=0)

                        transfer_key_rev = f"transfer_{routes_list[j]}_to_{routes_list[i]}"
                        G.add_edge(node2, node1, key=transfer_key_rev,
                                  type="transfer",
                                  Waktuij=transfer_time_min,
                                  Biayaij=transfer_cost_ji,
                                  Transitij=1,
                                  Waktuij_norm=transfer_time_min / T_MAX,
                                  Biayaij_norm=transfer_cost_ji / C_MAX,
                                  distance_km=0)
        
        print(f"Graph built successfully!")
        print(f"Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}")
        print(f"Stops with multiple routes: {sum(1 for r in stop_to_routes.values() if len(r) > 1)}")
        
        return G, stop_to_routes
        
    except Exception as e:
        print(f"Internal Error: {str(e)}")
        return None, None

