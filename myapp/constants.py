from datetime import time

# Normalized cost max
T_MAX = 360.0    # max travel time, minutes
C_MAX = 35000.0  # max fare, IDR
P_MAX = 5.0      # max reasonable number of transfers

# Params for graph construction (graph.py)
DEFAULT_SPEED_KMH = 25.0          
MAX_WAIT_MIN = 10.0               
WALKING_SPEED_KMH = 5.0           
WALKING_RADIUS_M = 400    
BUS_STOP_SECS = 10.0              # additional time penalty for bus stops (boarding/alighting)        

# Konfigurasi kelas tarif (views.py)
FLAT_FARE_CLASSES = {"FP", "FP2"}   # flat-fare classes with mutual free-transfer credit
FREE_FARE_CLASSES = {"GR"}          # always-free fare classes

# Time-of-day discount: discounted fare for FP/FP2 within the morning window.
ECONOMY_FARE_CLASSES = {"FP", "FP2"}
ECONOMY_FARE_PRICE = 2000.0
ECONOMY_DISCOUNT_START = time(5, 0)
ECONOMY_DISCOUNT_END = time(7, 0)   # window is [start, end)

# Pembagian Jam dan kecepatan rata-rata per jam (views.py)
RUSH_HOUR_MORNING_START = time(7, 0)
RUSH_HOUR_MORNING_END = time(9, 0)
RUSH_HOUR_NIGHT_START = time(17, 0)
RUSH_HOUR_NIGHT_END = time(19, 0)

NORMAL_HOUR_START = time(9, 1)
NORMAL_HOUR_END = time(16, 59)

NIGHT_HOUR_1_END = time(6, 58)
NIGHT_HOUR_2_START = time(19, 1)

SPEED_RUSH_HOUR_KMH = 17.5
SPEED_NORMAL_HOUR_KMH = 25.0
SPEED_NIGHT_HOUR_KMH = 40.0

# Weight presets for different user preferences (views.py)
WEIGHTS_CEPAT = {"waktu": 0.8, "biaya": 0.1, "transit": 0.1}
WEIGHTS_MURAH = {"waktu": 0.1, "biaya": 0.8, "transit": 0.1}
WEIGHTS_MIN_TRANSIT = {"waktu": 0.1, "biaya": 0.1, "transit": 0.8}
WEIGHTS_SEIMBANG = {"waktu": 1 / 3, "biaya": 1 / 3, "transit": 1 / 3}

# Hyperparameter for HACO (solvers/haco.py)
HACO_N_ANTS = 20
HACO_MAX_ITER = 100
HACO_MAX_NO_IMPROVE_ITER = 200   # consecutive iterations without improvement before stopping
HACO_TAU_0 = 1                   # initial pheromone τ_ijk(0) = 1
HACO_ALPHA = 1.0                 # pheromone exponent (eq 2.14)
HACO_BETA = 2.0                  # heuristic exponent (eq 2.14)
HACO_RHO = 0.02                  # evaporation rate 
HACO_TABU_SIZE = 0.7             # fraction of solutions sampled into the tabu list

# UI
DEFAULT_ROUTE_COLOR = "#2563eb"  # corridor color when GTFS has no route_color (blue)
WALKING_COLOR = "#6b7280"        # walking segment color (gray)
WALKING_FALLBACK_MAX_DISTANCE_KM = 2.0 # Walking-only fallback (compute_walking_only_route)
MAX_HALTE_SUGGESTIONS = 10       # max autocomplete in getHalteList
