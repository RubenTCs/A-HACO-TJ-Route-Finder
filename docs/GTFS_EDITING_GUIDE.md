# GTFS Data Editing Guide (Backend)

How to add or remove a **halte (stop)** or a **rute/jalur (route)** in the
Transjakarta GTFS feed that powers route optimisation, and how to preprocess raw
GTFS before it is used.

This guide is conceptual and file-level: it tells you *which files and fields to
touch and why*. For the exact definition of every field, always refer to the
official spec: **GTFS Schedule Reference — <https://gtfs.org/documentation/schedule/reference/>**.

---

## 1. How the data flows

```
Transitland (raw GTFS)
        │  download
        ▼
Canonical GTFS Schedule Validator   ← validate before trusting the data
        │
        ▼
Preprocessing (Python)              ← reduce trips, merge stops, fix shape distance
        │
        ▼
myapp/static/data/GTFS_Preprocessed/   ← editable source copy (12 .txt files)
        │  re-zip
        ▼
myapp/static/data/GTFS_Preprocessed.zip   ← what the app actually loads at runtime
        │
        ▼
Graph builder (solver_engine/graph.py)  → NetworkX multigraph → A* / HACO / MILP
```

**The single most important fact:** the running app reads the **`.zip`**, not the
folder. `gtfs_helper.py` loads `myapp/static/data/GTFS_Preprocessed.zip` with
`gtfs_kit.read_feed(..., dist_units="km")`. The `GTFS_Preprocessed/` directory is
just the working/source copy.

So every edit is a loop:

1. Edit the `.txt` files inside `GTFS_Preprocessed/`.
2. Re-zip the folder back into `GTFS_Preprocessed.zip`.
3. Reload the feed (`gtfsHelper.reload()` + `views.refresh_halte_cache()`) or
   simply restart the Django server.

> Note: `GTFS_Preprocessed.zip` is kept as the runtime feed and also as a pristine
> seed/backup. Always keep a backup before editing.

---

## 2. Files in the runtime feed

The runtime feed is the 12 standard GTFS files. See the GTFS reference for each
file's full field list; below is only *what each file is for in this project*.

| File | Role in this project |
|------|----------------------|
| `agency.txt` | Operator info (Transjakarta). Rarely edited. |
| `stops.txt` | **Halte** — id, name, lat/lon. Nodes of the graph. |
| `routes.txt` | **Rute/koridor** — id, names, type, colour. |
| `trips.txt` | A specific run of a route; links `route_id` ↔ `service_id` ↔ stops. |
| `stop_times.txt` | Ordered list of stops per trip (`stop_sequence`). Defines the path. |
| `frequencies.txt` | Operating window + headway per trip. **Required for routing** (see §4). |
| `calendar.txt` | Which weekdays each `service_id` is active. **Required for routing.** |
| `calendar_dates.txt` | Service exceptions (holidays). |
| `fare_attributes.txt` | Fare classes and prices (`fare_id` → `price`). |
| `fare_rules.txt` | Maps `route_id` → `fare_id`. No rule ⇒ route is treated as **free**. |
| `shapes.txt` | Geometry polyline per `shape_id`; drives distance/map drawing. |
| `transfers.txt` | Recommended transfer pairs between nearby stops. |

> `route_list.txt` (mentioned in the proposal) is a **preprocessing-only** helper
> used to pick each route's main trip. It is **not** part of the runtime feed and
> is not read by the app.

---

## 3. Getting and preprocessing raw GTFS

This is the pipeline used to produce the current feed. Repeat it when refreshing
from a newer Transitland export.

### 3.1 Collect

Download the Transjakarta GTFS `.zip` from **Transitland**. It contains the raw
standard files (with many trip variants and split platforms).

### 3.2 Validate

Run the raw feed through the **Canonical GTFS Schedule Validator** by MobilityData
(<https://gtfs-validator.mobilitydata.org/>). Fix structural errors before
preprocessing. This is the before/after gate (raw had ~242 routes, 652 trips/shapes,
8,841 stops → after preprocessing 242 routes, 359 trips/shapes, 7,423 stops).

### 3.3 Preprocess (three steps)

1. **Reduce trips per route.** Each route ships many trip variants (different
   directions, alt paths). Keep only the *main* trip per route (selected via
   `route_list.txt`) and filter `trips.txt`, `stop_times.txt`, and
   `frequencies.txt` down to those trips. This keeps the graph one clean corridor
   per direction.
2. **Unify stops.** A physical halte often appears as a parent station plus
   several child platforms. Merge them into one node using the `parent_station`
   relation in `stops.txt`. (Reinforced at runtime: the graph keys nodes by
   `stop_name`, so identical names already collapse to one hub — see §6.)
3. **Normalise shape distance.** Align each shape's final point to its trip's last
   stop coordinate, and ensure `shape_dist_traveled` is **monotonically
   increasing** along the trip. The graph uses consecutive
   `shape_dist_traveled` deltas for segment distance; if it's missing or
   non-increasing, it falls back to straight-line (haversine) distance.

### 3.4 Re-zip

After preprocessing, package the folder back into `GTFS_Preprocessed.zip` (§1).

---

## 4. What makes a stop/route actually routable

Before editing, understand the runtime rules in `solver_engine/graph.py`. These
are the silent failure modes:

- **Graph nodes are keyed by `stop_name`** (not `stop_id`). Two stops with the
  same name become **one** node/hub. This is intentional (it creates transfer
  points), but it means a typo or an accidental name clash will merge or split
  stops unexpectedly.
- A trip is only added to the graph for a query if **both** hold:
  1. its `service_id` is active for the query's **weekday** in `calendar.txt`
     (the matching day column = `1`), **and**
  2. it has a `frequencies.txt` row whose `[start_time, end_time]` covers the
     query **time**.
  Miss either and the route simply won't appear — with no error.
- **Distance** per segment = `shape_dist_traveled` delta (metres → km); blank or
  non-monotonic ⇒ haversine fallback.
- **Fare:** the route needs a `fare_rules.txt` row pointing to a `fare_id` that
  exists in `fare_attributes.txt`. No rule ⇒ the route is free (Rp 0). Fare
  classes: `FP`/`FP2` are flat fare with mutual free-transfer credit, `GR` is
  always free; there is a morning discount window (05:00–07:00) for `FP`/`FP2`.
- **Transfers** between routes at the same `stop_name` are generated
  automatically; `transfers.txt` adds inter-stop walking transfers; short walks
  (≤ 400 m) between different routes are also auto-generated. You do **not**
  hand-author transfer edges.

---

## 5. Adding / removing a HALTE (stop)

### Add a stop

1. **`stops.txt`** — add a row with a unique `stop_id`, a `stop_name`, and valid
   `stop_lat`/`stop_lon`. Keep `location_type` empty/`0` for a boardable stop.
   - Pick the `stop_name` deliberately: reusing an existing name merges this stop
     into that hub (see §6); a new name creates a new node.
2. **`stop_times.txt`** — a stop does nothing until it is part of a trip. To put
   it on a trip, insert a row for that `trip_id` at the desired `stop_sequence`,
   then renumber the following `stop_sequence` values so they stay ordered.
   - Leave `shape_dist_traveled` blank to let the graph use haversine distance,
     or set a value consistent with (between) its neighbours.
3. Re-zip and reload (§1).

A standalone stop that no trip references is harmless but invisible to routing.

### Remove a stop

1. **Detach first.** Remove every `stop_times.txt` row that references the
   `stop_id`, and renumber `stop_sequence` for each affected trip so the sequence
   has no gaps. A trip must keep **at least 2 stops**; if removing the stop would
   drop it below that, delete the whole trip instead (§5 → route removal).
2. **`stops.txt`** — delete the stop row only after it is no longer referenced.
3. Optionally clean any `transfers.txt` rows referencing the `stop_id`.
4. Re-zip and reload.

---

## 6. Adding / removing a RUTE (route / jalur)

A working route is a chain across several files. Refer to the GTFS reference for
each field; the project-specific requirements are called out below.

### Add a route

1. **`routes.txt`** — add a row with a unique `route_id`. Set `route_type` to `3`
   (bus, as used here). `route_short_name`/`route_long_name`, `route_color`, and
   `route_text_color` drive labels/map colour.
2. **`trips.txt`** — add at least one trip with a unique `trip_id`, the new
   `route_id`, and a `service_id` that **exists and is active** in `calendar.txt`.
   Set `direction_id` (`0`/`1`) as appropriate.
3. **`stop_times.txt`** — add the ordered stops for the trip: one row per stop
   with the `trip_id`, increasing `stop_sequence`, `stop_id`, and
   `arrival_time`/`departure_time`. All `stop_id`s must already exist in
   `stops.txt`. Need **≥ 2 stops**.
4. **`frequencies.txt`** — **required.** Add a row for the `trip_id` with a
   `start_time`/`end_time` window and a `headway_secs`. Without this the trip is
   never selected at query time (§4).
5. **`fare_rules.txt`** (optional but recommended) — map the `route_id` to a
   `fare_id` from `fare_attributes.txt`. Omit it only if the route should be
   free.
6. **`shapes.txt`** (optional) — add a `shape_id` polyline and reference it from
   the trip for an accurate drawn path. Without a shape, the map falls back to
   straight lines and distance falls back to haversine.
7. Re-zip and reload.

### Remove a route

1. **`stop_times.txt`** — delete all rows for the route's `trip_id`(s).
2. **`frequencies.txt`** — delete the rows for those `trip_id`(s).
3. **`trips.txt`** — delete the trip rows for the `route_id`.
4. **`routes.txt`** — delete the route row.
5. **`fare_rules.txt`** — delete rows referencing the `route_id`.
6. **`shapes.txt`** — optionally delete the now-orphaned `shape_id`(s).
7. Stops used only by this route can be removed via §5, or left as orphans
   (harmless).
8. Re-zip and reload.

---

## 7. Repackage & reload

1. Re-zip the edited `GTFS_Preprocessed/` folder into `GTFS_Preprocessed.zip`
   (overwrite). The zip must contain the `.txt` files at its root, matching the
   original layout.
2. Drop the cache: call `gtfsHelper.reload()` then `views.refresh_halte_cache()`,
   or restart the Django server. Until this runs, the app keeps serving the old
   feed from memory.
3. Sanity-check: run a search that crosses the edited stop/route at a time and day
   the trip is active.

---

## 8. Gotchas checklist

- [ ] Edited the folder **and** re-zipped to `GTFS_Preprocessed.zip` (runtime
      reads the zip).
- [ ] New trip has a `frequencies.txt` row covering the query time **and** an
      active `service_id` in `calendar.txt`.
- [ ] Trip has **≥ 2 stops** and contiguous `stop_sequence`.
- [ ] `stop_name` chosen deliberately (identical names merge into one hub).
- [ ] `shape_dist_traveled` left blank or kept monotonic.
- [ ] Route has a `fare_rules.txt` → `fare_attributes.txt` mapping (or is meant
      to be free).
- [ ] Reloaded the feed / restarted the server, then verified with a live search.

---

*Field-level reference for every file and column: GTFS Schedule Reference —
<https://gtfs.org/documentation/schedule/reference/>.*
