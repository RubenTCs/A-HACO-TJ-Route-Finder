import gurobipy as gp
import numpy as np
from .utils import (
    calculate_final_metrics,
    build_detailed_journey,
    build_path_coordinates
)
# -- Gurobi Solver --
def find_route_with_gurobi(G, stop_to_routes, start_stop, end_stop, weights):
    """
    Find optimal route using Gurobi MILP solver.
    
    Parameters:
    -----------
    G : nx.MultiDiGraph
        Transport network graph with (stop_name, route_id) nodes
    stop_to_routes : dict
        Mapping of stop_name -> set of route_ids
    start_stop : str
        Starting stop name
    end_stop : str
        Ending stop name
    weights : dict
        Cost weights: {'waktu': w_time, 'biaya': w_cost, 'transit': w_transit}
    
    Returns:
    --------
    dict with solution or error message
    """
    
    print("--- Start find route with GUROBI ---")

    # Validate inputs
    if start_stop not in stop_to_routes:
        return {"error": f"Halte Asal '{start_stop}' tidak ditemukan."}
    if end_stop not in stop_to_routes:
        return {"error": f"Halte Tujuan '{end_stop}' tidak ditemukan."}
    
    # Get candidate nodes for start and end stops (to ensure the start node and end node is in the Graph)
    start_nodes = [n for n in G.nodes() if n[0] == start_stop]
    end_nodes = [n for n in G.nodes() if n[0] == end_stop]
    
    if not start_nodes or not end_nodes:
        return {"error": "Node asal atau tujuan tidak terhubung ke graf."}

    # Validate weights
    # Persamaan (2.5) w_t + w_c + w_p = 1 and (2.6) all weights are non-negative.
    w_t_input = float(weights.get('waktu', 0))
    w_c_input = float(weights.get('biaya', 0))
    w_p_input = float(weights.get('transit', 0))

    if min(w_t_input, w_c_input, w_p_input) < 0:
        return {"error": "Bobot tidak valid: semua bobot harus >= 0."}

    if abs((w_t_input + w_c_input + w_p_input) - 1.0) > 1e-6:
        return {"error": "Bobot tidak valid: w_t + w_c + w_p harus = 1."}
    
    try:
        model = gp.Model("MILP_Transjakarta_Route")
        model.setParam('OutputFlag', 0)  # Suppress solver output (untuk logging progress aja, set to 1 to show the solver logs in the console)

        # Persamaan (2.7), variabel binary: x_ijk = 1 if edge (i,j,k) is selected.
        x = {}
        for u, v, key in G.edges(keys=True):
            x[(u, v, key)] = model.addVar(vtype=gp.GRB.BINARY, name=f"x_{u}_{v}_{key}")

        # Super-source and super-sink arc variables.
        # They represent arcs (S,j,k) and (i,D,k) in (2.2)-(2.3).
        x_source = {}
        for s in start_nodes:
            x_source[s] = model.addVar(vtype=gp.GRB.BINARY, name=f"x_source_{s}")

        x_sink = {}
        for e in end_nodes:
            x_sink[e] = model.addVar(vtype=gp.GRB.BINARY, name=f"x_sink_{e}")

        # Weight variables (2.5)-(2.6)
        w_t = model.addVar(lb=0.0, name="w_t")
        w_c = model.addVar(lb=0.0, name="w_c")
        w_p = model.addVar(lb=0.0, name="w_p")
        
        # model.update()

        # (2.5) and (2.6): non-negative and normalized weights.
        model.addConstr(w_t + w_c + w_p == 1, "weight_sum")
        model.addConstr(w_t == w_t_input, "fix_w_t")
        model.addConstr(w_c == w_c_input, "fix_w_c")
        model.addConstr(w_p == w_p_input, "fix_w_p")

        # (2.1) Objective: min sum((w_t*t_ijk_norm + w_c*c_ijk_norm + w_p*p_ijk) * x_ijk)
        obj_expr = gp.quicksum(
            (
                w_t * G.get_edge_data(u, v, key).get('Waktuij_norm', 0) +
                w_c * G.get_edge_data(u, v, key).get('Biayaij_norm', 0) +
                w_p * G.get_edge_data(u, v, key).get('Transitij', 0)
            ) * x[(u, v, key)]
            for u, v, key in G.edges(keys=True)
        )
        model.setObjective(obj_expr, gp.GRB.MINIMIZE)

        # (2.2): Add constraint hanya satu arc keluar dari S (source).
        model.addConstr(gp.quicksum(x_source[s] for s in start_nodes) == 1, "source")

        # (2.3): Add constraint hanya satu arc masuk ke D (destination) / sink
        model.addConstr(gp.quicksum(x_sink[e] for e in end_nodes) == 1, "sink")

        # (2.4): Flow conservation for all transit nodes.
        for node in G.nodes():
            # Outgoing flow
            out_flow = gp.quicksum(
                x[(node, succ, key)]
                for succ in G.successors(node)
                for key in G[node][succ].keys()
            )
            
            # Incoming flow
            in_flow = gp.quicksum(
                x[(pred, node, key)]
                for pred in G.predecessors(node)
                for key in G[pred][node].keys()
            )
            
            # Add constraint 
            # Aliran masuk - Aliran keluar = 0
            # Aliran masuk == aliran keluar
            model.addConstr(
                in_flow + x_source.get(node, 0) == out_flow + x_sink.get(node, 0),
                f"balance_{node}"
            )

        # Solve
        model.optimize()

        # Extract active edges
        active_edges = [(u, v, key) for u, v, key in G.edges(keys=True) 
                       if x[(u, v, key)].X == 1]
        
        # Find actual start node
        actual_start = next((s for s in start_nodes if x_source[s].X == 1), start_nodes[0])
        
        # Reconstruct path by following active edges
        path = [actual_start]
        current = actual_start
        remaining = set(active_edges)
        
        while remaining:
            next_node = None
            for (u, v, key) in list(remaining):
                if u == current:
                    next_node = v
                    remaining.remove((u, v, key))
                    break
            
            if next_node is None:
                break
            
            path.append(next_node)
            current = next_node
        
        # Verify path ends at a valid end node
        if not path or path[-1][0] != end_stop:
            return {"error": "Jalur tidak ditemukan lengkap."}
        
        # Calculate final metrics
        final_metrics = calculate_final_metrics(G, path, weights)
        if "error" in final_metrics:
            return final_metrics
        
        detailed_journey = build_detailed_journey(G, path)

        halte_coordinates = build_path_coordinates(detailed_journey, path)
        
        # Return result
        return {
            "detailed_journey": detailed_journey,
            "path_coordinates": halte_coordinates,
            "jarak_km": final_metrics.get("jarak_km", 0),
            "waktu_tempuh_menit": final_metrics.get("waktu_tempuh_menit", 0),
            "total_biaya": final_metrics.get("total_biaya", 0),
            "jumlah_transit": final_metrics.get("jumlah_transit", 0),
            "z_score": final_metrics.get("z_score", 0)
        }
        
    except Exception as e:
        print(f"Gurobi Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"error": f"Solver error: {str(e)}"}
