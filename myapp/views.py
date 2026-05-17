from .forms import PathForm
from .solver_engine.gurobi import (
    find_path_with_gurobi
)
from .solver_engine.astar import (
    find_path_with_astar
)
from .solver_engine.haco import (
    find_path_with_haco
)
from .solver_engine.graph import (
    construct_graph_with_costs,
)
from .solver_engine.utils import compute_walking_only_route
from .gtfs_helper import gtfsHelper
from .log.excel_logger import append_search, read_log
from . import constants as C
from datetime import datetime, time
from time import perf_counter
from django.shortcuts import render, redirect
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
    filtered = (starts_with + contains_word)[:C.MAX_HALTE_SUGGESTIONS]
    return JsonResponse(filtered, safe=False)

#Views
def index(request):
    hasil = request.session.pop("hasil", {})
    form_initial = request.session.pop("form_data", None)
    form = PathForm(initial=form_initial) if form_initial else PathForm()

    if request.method == "POST":
        form = PathForm(request.POST)

        if form.is_valid():

            halte_asal = form.cleaned_data["halte_asal"]
            halte_tujuan = form.cleaned_data["halte_tujuan"]
            preferensi = form.cleaned_data["preferensi"]
            solver_method = form.cleaned_data["metode_solver"]

            depart_time = form.cleaned_data["jam_berangkat"]

            depart_date = form.cleaned_data["tanggal_berangkat"]
            
            # Error Handling
            if halte_asal == halte_tujuan:
                hasil = {"error": f"Halte Asal dan Tujuan sama (`{halte_asal}'), ganti salah satu"}
            elif HALTE_NAMES_CACHE and (halte_asal not in HALTE_NAMES_CACHE):
                hasil = {"error": f"Halte Asal '{halte_asal}' tidak ditemukan. Coba cek lagi"}
            elif HALTE_NAMES_CACHE and (halte_tujuan not in HALTE_NAMES_CACHE):
                hasil = {"error": f"Halte Tujuan '{halte_tujuan}' tidak ditemukan. Coba cek lagi"}
            else:
                try:
                    
                    is_rush_hour = (
                        (C.RUSH_HOUR_MORNING_START <= depart_time <= C.RUSH_HOUR_MORNING_END) or
                        (C.RUSH_HOUR_NIGHT_START <= depart_time <= C.RUSH_HOUR_NIGHT_END)
                    )

                    is_normal_hour = (C.NORMAL_HOUR_START <= depart_time <= C.NORMAL_HOUR_END)

                    is_night_hour = (
                        (time(0,0) <= depart_time <= C.NIGHT_HOUR_1_END) or
                        (C.NIGHT_HOUR_2_START <= depart_time <= time(23,59))
                    )

                    # Penentuan parameter berdasarkan depart_time
                    if is_rush_hour:
                        print("MODE: JAM SIBUK") # for terminal msg
                        mode_waktu = "JAM SIBUK"
                        param_speed = C.SPEED_RUSH_HOUR_KMH # Kecepatan rata-rata km/h
                    elif is_normal_hour:
                        print("MODE: JAM NORMAL") # for terminal msg
                        mode_waktu = "JAM NORMAL"
                        param_speed = C.SPEED_NORMAL_HOUR_KMH # Kecepatan rata-rata km/h
                    elif is_night_hour:
                        print("MODE: JAM MALAM")
                        mode_waktu = "JAM MALAM"
                        param_speed = C.SPEED_NIGHT_HOUR_KMH # Kecepatan rata-rata km/h

                    # --- Preference ---
                    # NOTE: Bisa diganti ganti untuk saat pengujian
                    if preferensi == "cepat":
                        preferensi_label = "Paling Cepat"
                        weights_dict = dict(C.WEIGHTS_CEPAT)
                    elif preferensi == "murah":
                        preferensi_label = "Termurah"
                        weights_dict = dict(C.WEIGHTS_MURAH)
                    elif preferensi == "min_transit":
                        preferensi_label = "Minim Transit"
                        weights_dict = dict(C.WEIGHTS_MIN_TRANSIT)
                    else:
                        preferensi_label = "Seimbang"
                        weights_dict = dict(C.WEIGHTS_SEIMBANG)

                    print("--- Start Pencarian Rute ---")

                    print(f"INFO: Building graph with speed={param_speed}")
                    G, stop_to_routes = construct_graph_with_costs(
                        depart_date, depart_time, speed_kmh=param_speed
                    )

                    if G is None:
                        hasil = {"error": "Gagal membangun graf"}
                    else:
                        solver_runners = {
                            "MILP": lambda: find_path_with_gurobi(
                                G, stop_to_routes,
                                start_stop=halte_asal, end_stop=halte_tujuan,
                                weights=weights_dict),
                            "ASTAR": lambda: find_path_with_astar(
                                G, stop_to_routes,
                                start_stop=halte_asal, end_stop=halte_tujuan,
                                weights=weights_dict, speed_kmh=param_speed),
                            "HACO": lambda: find_path_with_haco(
                                G, stop_to_routes,
                                start_stop=halte_asal, end_stop=halte_tujuan,
                                weights=weights_dict),
                        }

                        print(f"INFO: Running solver {solver_method}")
                        t0 = perf_counter()
                        try:
                            res = solver_runners[solver_method]()
                        except Exception as exc:
                            res = {"error": f"{type(exc).__name__}: {exc}"}
                        elapsed = perf_counter() - t0

                        if res and "error" not in res:
                            res["runtime_sec"] = elapsed
                            print(f"INFO: {solver_method} ok in {elapsed:.4f}s")
                        else:
                            err = res.get("error") if isinstance(res, dict) else "no result"
                            res = {"error": err, "runtime_sec": elapsed}
                            print(f"WARN: {solver_method} failed in {elapsed:.4f}s: {err}")

                        hasil_route = res

                        if hasil_route and "error" not in hasil_route:
                            try:
                                append_search(
                                    meta={
                                        "halte_asal": halte_asal,
                                        "halte_tujuan": halte_tujuan,
                                        "tanggal_berangkat": depart_date,
                                        "jam_berangkat": depart_time,
                                        "preferensi": preferensi,
                                        "metode_solver": solver_method,
                                        "mode_waktu": mode_waktu,
                                        "param_speed": param_speed,
                                        "weights": weights_dict,
                                    },
                                    result=hasil_route,
                                )
                            except Exception as log_exc:
                                print(f"WARN: failed to append log: {log_exc}")

                        # Walking-only fallback: surface a walk-only route when
                        # either (a) transit failed entirely, or (b) walking is
                        # actually faster than transit (common for very close
                        # halte where transit needs a transfer).
                        transit_failed = (
                            hasil_route is not None
                            and isinstance(hasil_route, dict)
                            and "error" in hasil_route
                        )
                        walking_route = compute_walking_only_route(halte_asal, halte_tujuan)
                        if walking_route is not None:
                            walking_min = float(walking_route.get("waktu_tempuh_menit", 0) or 0)
                            transit_min = float(
                                hasil_route.get("waktu_tempuh_menit", 0) or 0
                            ) if (hasil_route and not transit_failed) else float("inf")

                            use_walking = transit_failed or walking_min < transit_min
                            if use_walking:
                                if transit_failed:
                                    walking_route["fallback_reason"] = (
                                        hasil_route.get("error", "") if hasil_route else ""
                                    )
                                else:
                                    walking_route["fallback_reason"] = (
                                        f"Jalan kaki lebih cepat ({walking_min:.0f} menit) "
                                        f"dibanding transit ({transit_min:.0f} menit)"
                                    )
                                walking_route["runtime_sec"] = (
                                    hasil_route.get("runtime_sec", 0) if hasil_route else 0
                                )
                                print(
                                    f"INFO: Walking-only chosen. {walking_route['jarak_km']} km, "
                                    f"{walking_route['waktu_tempuh_menit']} min "
                                    f"(transit_failed={transit_failed})"
                                )
                                hasil_route = walking_route

                        if hasil_route is None:
                            hasil = {"error": f"Solver '{solver_method}' tidak dikenal."}
                        elif "error" in hasil_route:
                            hasil = {"error": hasil_route["error"]}
                        else:
                            waktu_menit = hasil_route.get("waktu_tempuh_menit", 0) or 0
                            jam_tiba_str = ""
                            try:
                                from datetime import datetime as _dt, timedelta as _td
                                base = _dt.combine(depart_date, depart_time)
                                arrive = base + _td(minutes=float(waktu_menit))
                                jam_tiba_str = arrive.strftime("%H:%M")
                            except Exception:
                                jam_tiba_str = ""

                            hasil = {
                                "detailed_journey": hasil_route.get("detailed_journey", []),
                                "path_coordinates": hasil_route.get("path_coordinates", []),
                                "path_segments": hasil_route.get("path_segments", []),
                                "jarak_km": hasil_route.get("jarak_km", 0),
                                "waktu_tempuh_menit": waktu_menit,
                                "total_biaya": hasil_route.get("total_biaya", 0),
                                "jumlah_transit": hasil_route.get("jumlah_transit", 0),
                                "z_score": hasil_route.get("z_score", 0),
                                "preferensi": preferensi,
                                "preferensi_label": preferensi_label,
                                "mode_waktu": mode_waktu,
                                "param_speed": param_speed,
                                "solver_method": solver_method,
                                "halte_asal": halte_asal,
                                "halte_tujuan": halte_tujuan,
                                "jam_berangkat": depart_time.strftime("%H:%M"),
                                "jam_tiba": jam_tiba_str,
                                "is_walking_only": hasil_route.get("is_walking_only", False),
                                "fallback_reason": hasil_route.get("fallback_reason", ""),
                            }
                        print(hasil_route)

                except Exception as e:
                    hasil = {"error": f"Internal Error: {str(e)}"}
                    print(f"Internal Error: {str(e)}")
        else:

            # jika form tidak valid
            hasil = {"error": "Input tidak valid. Cek ulang form."}
            print("error: Input tidak valid. Cek ulang form.")

        # redirect after POST so refresh does not rerun path finding.
        request.session["hasil"] = hasil
        request.session["form_data"] = {
            "halte_asal": request.POST.get("halte_asal", ""),
            "halte_tujuan": request.POST.get("halte_tujuan", ""),
            "tanggal_berangkat": request.POST.get("tanggal_berangkat", ""),
            "jam_berangkat": request.POST.get("jam_berangkat", ""),
            "preferensi": request.POST.get("preferensi", ""),
            "metode_solver": request.POST.get("metode_solver", ""),
        }
        return redirect("index")

    
    return render(
        request,
        "index.html",
        {
            "form": form,
            "hasil": hasil,
        }
    )


def log(request):
    rows = read_log(newest_first=True)
    return render(
        request,
        "log.html",
        {
            "rows": rows,
            "total_searches": len(rows),
        },
    )