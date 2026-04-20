import os
from .forms import RouteForm
from .solvers.gurobi import (
    find_route_with_gurobi
)
from .graph_making.graph import (
    construct_graph_with_costs,
)
from .gtfs_helper import gtfsHelper
from datetime import datetime, time
from django.shortcuts import render
from django.conf import settings
from django.http import HttpResponse, JsonResponse

HALTE_NAMES_CACHE = []

try:
    # Reuse the shared GTFS feed/cache from graph_making.
    stops = gtfsHelper.stops
    if stops is not None and "stop_name" in stops.columns:
        HALTE_NAMES_CACHE = sorted(stops["stop_name"].dropna().unique().tolist())
        print(f"INFO: Cached {len(HALTE_NAMES_CACHE)} stop names")
except Exception as e:
    print(f"Failed to load GTFS data from graph helper: {e}")

# API
def getHalteList(request):
    query = request.GET.get("q", "").strip().lower()
    if not query or not HALTE_NAMES_CACHE: return JsonResponse([], safe=False)
    starts_with = [h for h in HALTE_NAMES_CACHE if h.lower().startswith(query)]
    contains_word = [
        h for h in HALTE_NAMES_CACHE
        if not h.lower().startswith(query) and any(word.startswith(query) for word in h.lower().split())
    ]
    filtered = (starts_with + contains_word)[:10]
    return JsonResponse(filtered, safe=False)

def index(request):
    hasil = {}
    form = None
    
    if request.method == "POST":
        form = RouteForm(request.POST)

        if form.is_valid():

            halte_asal = form.cleaned_data["halte_asal"]
            halte_tujuan = form.cleaned_data["halte_tujuan"]
            preferensi = form.cleaned_data["preferensi"]
            solver_method = form.cleaned_data["metode_solver"]

            depart_time = form.cleaned_data["jam_berangkat"]
            depart_time_str = depart_time.strftime("%H:%M")

            depart_date = form.cleaned_data["tanggal_berangkat"]
            depart_date_str = depart_date.strftime("%Y-%m-%d")
            
            # TODO: Manual Error handling, check if valid or not
            # Error Handling
            if halte_asal == halte_tujuan:
                hasil = {"error": f"Halte Asal dan Tujuan sama (`{halte_asal}'), ganti salah satu"}
            elif HALTE_NAMES_CACHE and (halte_asal not in HALTE_NAMES_CACHE):
                hasil = {"error": f"Halte Asal '{halte_asal}' tidak ditemukan. Coba cek lagi"}
            elif HALTE_NAMES_CACHE and (halte_tujuan not in HALTE_NAMES_CACHE):
                hasil = {"error": f"Halte Tujuan '{halte_tujuan}' tidak ditemukan. Coba cek lagi"}
            else:
                try:
                    
                    rush_hour_morning_start = time(7,0)
                    rush_hour_morning_end = time(9,0)
                    rush_hour_night_start = time(17,0)
                    rush_hour_night_end = time(19,0)

                    normal_hour_start = time(9,1)
                    normal_hour_end = time(16,59)

                    night_hour_1_end = time(6,58)
                    night_hour_2_start = time(19,1)

                    is_rush_hour = (
                        (rush_hour_morning_start <= depart_time <=rush_hour_morning_end) or
                        (rush_hour_night_start <= depart_time <= rush_hour_night_end)
                    )

                    is_normal_hour = (normal_hour_start <= depart_time <= normal_hour_end)

                    is_night_hour = (
                        (time(0,0) <= depart_time <= night_hour_1_end) or
                        (night_hour_2_start <= depart_time <= time(23,59))
                    )

                    # Penentuan parameter berdasarkan depart_time
                    if is_rush_hour:
                        print("MODE: JAM SIBUK") # for terminal msg
                        mode_waktu = "JAM SIBUK"
                        param_speed = 17.5 # Kecepatan rata-rata km/h
                    elif is_normal_hour:
                        print("MODE: JAM NORMAL") # for terminal msg
                        mode_waktu = "JAM NORMAL"
                        param_speed = 25 # Kecepatan rata-rata km/h
                    elif is_night_hour:
                        print("MODE: JAM MALAM")
                        mode_waktu = "JAM MALAM"
                        param_speed = 40 # Kecepatan rata-rata km/h

                    dynamic_params = {
                        "mode": mode_waktu,
                        "speed": param_speed
                    }

                    # --- Preference --- 
                    # TODO: Harus diganti nanti saat pengujian
                    if preferensi == "cepat":
                        preferensi_label = "⚡ Paling Cepat"
                        weights_dict = {"waktu": 0.8, "biaya": 0.1, "transit": 0.1}
                    elif preferensi == "murah":
                        preferensi_label = "Termurah"
                        weights_dict = {"waktu": 0.1, "biaya": 0.8, "transit": 0.1}
                    elif preferensi == "min_transit":
                        preferensi_label = "🔄 Minim Transit"
                        weights_dict = {"waktu": 0.1, "biaya": 0.1, "transit": 0.8}
                    else: 
                        preferensi_label = "Seimbang"
                        weights_dict = {"waktu": 0.4, "biaya": 0.3, "transit": 0.3}

                    data_directory = os.path.join(settings.BASE_DIR, "myapp", "static", "data")

                    print("--- Start Pencarian Rute ---")

                    print(f"INFO: Building graph with speed={param_speed}")
                    G, stop_to_routes = construct_graph_with_costs(depart_date, depart_time, avg_transfer_min=param_speed)

                    if solver_method == "MILP":
                        hasil_route = find_route_with_gurobi(G, stop_to_routes, start_stop=halte_asal, end_stop=halte_tujuan, 
                                                             weights=weights_dict)
                    elif solver_method == "astar":
                        #TODO: Make A-star Algorithm
                        hasil_route = None # find route with astar
                    elif solver_method == "HACO":   
                        #TODO: MAKE HACO Algorithm
                        hasil_rotue = None # find route with haco

                    print(hasil_route)

                except Exception as e:
                    hasil = {"error": f"Internal Error: {str(e)}"}
                    print(f"Internal Error: {str(e)}")
        else:

            # jika form tidak valid
            hasil = {"error": "Input tidak valid. Cek ulang form."}
            print("error: Input tidak valid. Cek ulang form.")


    return render(
        request,
        "index.html",
        {
            "form": form,
            "hasil": hasil
        }
    )