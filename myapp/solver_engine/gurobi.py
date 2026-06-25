import gurobipy as gp
from .utils import (
    calculate_final_metrics,
    build_detailed_journey,
    build_path_coordinates,
)
# -- Gurobi Solver --
def find_path_with_gurobi(G, stop_to_routes, start_stop, end_stop, weights):
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
        return {"error": f"Halte Asal '{start_stop}' tidak dilayani angkutan pada jam yang dipilih."}
    if end_stop not in stop_to_routes:
        return {"error": f"Halte Tujuan '{end_stop}' tidak dilayani angkutan pada jam yang dipilih."}
    
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

        # Super-source and super-sink edges variables.
        #Represent edges (S,j,k) and (i,D,k) in (2.2)-(2.3).
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

        # (2.1) Objective: min sum((w_t*t_ijk_norm + w_c*c_ijk_norm + w_p*p_ijk) * x_ijk)
        obj_expr = gp.quicksum(
            (
                w_t * G.get_edge_data(u, v, key).get('Waktuij_norm', 0) +
                w_c * G.get_edge_data(u, v, key).get('Biayaij_norm', 0) +
                w_p * G.get_edge_data(u, v, key).get('Transitij_norm', 0)
            ) * x[(u, v, key)]
            for u, v, key in G.edges(keys=True)
        )
        model.setObjective(obj_expr, gp.GRB.MINIMIZE)

        # (2.5) and (2.6): non-negative and normalized weights.
        model.addConstr(w_t + w_c + w_p == 1, "weight_sum")
        model.addConstr(w_t == w_t_input, "fix_w_t")
        model.addConstr(w_c == w_c_input, "fix_w_c")
        model.addConstr(w_p == w_p_input, "fix_w_p")

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

        # -----------------------------------------------------------
        # region extract path 
        # -----------------------------------------------------------

        # Use 0.5 threshold for binary vars. Gurobi can return 0.9999... or 1.0001
        # due to numerical tolerance, so direct == 1 comparison is unsafe.
        BIN_THRESHOLD = 0.5 

        # Build map: each node has at most one outgoing active edge by flow conservation, so next_of[u] = v is well-defined.
        next_of = {}
        for u, v, key in G.edges(keys=True):
            if x[(u, v, key)].X > BIN_THRESHOLD: # Pembulatan untuk variabel biner (harusnya 0 atau 1, tapi bisa jadi 0.9999 atau 1.0001 karena toleransi numerik Gurobi)
                next_of[u] = v

        # Find actual start node from x_source.
        actual_start = next(
            (s for s in start_nodes if x_source[s].X > BIN_THRESHOLD),
            start_nodes[0],
        )

        # Walk the linked list from start until run out of edges. Guard against cycles: a zero-cost subtour in the solution would otherwise loop forever.
        path = [actual_start]
        current = actual_start
        visited = {actual_start}
        while current in next_of:
            current = next_of[current]
            if current in visited:
                break
            visited.add(current)
            path.append(current)
        
        # Verify path ends at a valid end node
        if not path or path[-1][0] != end_stop:
            return {"error": "Jalur tidak ditemukan lengkap."}
        
        # -----------------------------------------------------------
        # endregion
        # -----------------------------------------------------------


        # Calculate final metrics
        final_metrics = calculate_final_metrics(G, path, weights)
        if "error" in final_metrics:
            return final_metrics
        
        detailed_journey = build_detailed_journey(G, path)

        coord_result = build_path_coordinates(detailed_journey, path)

        # Return result
        return {
            "detailed_journey": detailed_journey,
            "path_coordinates": coord_result["path_coordinates"],
            "path_segments": coord_result["path_segments"],
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
