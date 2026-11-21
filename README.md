# Intelligent Logistics & Dynamic Route Optimization System — Vijayawada

A full-stack logistics platform that plans delivery routes for a fleet of vans on the **real road network of Vijayawada** (OpenStreetMap). It **re-plans the routes while the fleet is on the road**: when new orders arrive, traffic builds up or roads close.

- **Backend:** Python 3.10+, FastAPI, SQLAlchemy, WebSockets. Every routing and optimisation algorithm is written by hand in Python (`backend/app/algorithms/`).
- **Frontend:** React 18, Vite, Tailwind CSS, Leaflet, Recharts, framer-motion (micro-interactions).
- **Database:** SQLite out of the box. PostgreSQL works by changing `DATABASE_URL`.
- **Map:** one map, Vijayawada. `./set-up.sh` downloads its road network once from OpenStreetMap (Overpass API) into `backend/data/osm/`. After that the app runs offline.

### How the app flows

The top bar shows where you are and offers one primary button for the next step:

| Step | What happens | Primary button |
|---|---|---|
| 1 Orders | Create, generate, cancel or delete orders | **Add orders** |
| 2 Plan | Optimise routes for all open orders | **Optimise plan** |
| 3 Dispatch | Load the vans and start the day | **Dispatch fleet** |
| 4 Live | Vans drive their routes; inject events and watch re-planning | **Resume** (while paused) |
| 5 Review | Analytics compared with the FIFO baseline | **Review results** |

Simulation controls, always in the top bar:

| Control | What it does |
|---|---|
| ▶ / ⏸ | Start, pause or resume. |
| ⏹ **Stop** | Ends the run and returns to planning: vans go back to their hubs and the clock to the start of the shift. All orders and the optimised plan are kept. |
| ↺ **Reset** | Clears the plan, events and simulated orders. Your own orders, vans and hubs are kept. |
| **Speed** | Simulated minutes per second. |
| **Events** | New order, urgent order, traffic jam, road closure, clear traffic, random events. |

### How orders are shared between vans

The cost model makes the fleet share the work:
- **Route time counts actual work.** That means driving and handing over parcels; waiting at the hub is free.
- **Customer waiting has a cost (ε).** Orders placed during the day can be delivered immediately, so a free van that can deliver soon wins.
- **Workload fairness (ζ).** The cost grows with the square of each driver's total work today, including work already done. A van that has worked less gets the next job.
- **Fixed vehicle cost (δ).** Charged once per day and small, because the drivers are on shift anyway.
- **Ties.** When options cost the same, the van with the least work wins, not the first in the list.
- **Parked vans.** Vans waiting to leave later still count as available at the hub.

Measured on a 100-order day at Vijayawada scale:
- all 10 vans get 7–16 orders each, with 90–126 minutes of work per driver;
- new orders are spread over several vans;
- 0 late deliveries.

## 1. Quick start

```bash
./set-up.sh      # checks Python/Node, creates .env, venv, installs deps, downloads the Vijayawada map, seeds demo data
./run.sh         # backend on :8000 + frontend on :5173  →  open http://127.0.0.1:5173
```

`set-up.sh` needs an internet connection **once**, for the Vijayawada road network (a few MB, cached). If the download fails, it stops with a clear message; run it again when you are online. Without the map, the app shows a "map not downloaded" screen instead of a different city.

| Command | What it does |
|---|---|
| `./set-up.sh` | One-time setup. Idempotent, so it is safe to re-run. |
| `./set-up.sh --reseed` | Same setup, and regenerates the scenario (city, fleet, orders). |
| `./run.sh` / `./run.sh dev` | Backend with auto-reload plus the Vite dev server. |
| `./run.sh prod` | Builds the frontend and serves it with `vite preview`. |
| `./run.sh backend` / `./run.sh frontend` | Starts one side only. |
| `./run.sh stop` | Stops a running instance of this project and frees its ports. |
| `./run.sh test` | Runs the pytest suite (algorithms and API). |
| `./run.sh bench [--vrp-sizes 50 100 …]` | Runs the experiments and writes CSV and Markdown to `results/`. |

Interactive API documentation (Swagger) is served at `http://127.0.0.1:8000/docs`.

**"Address already in use".** `run.sh` checks both ports before starting:
- If a port is held by an earlier run of *this* project (for example after a closed terminal), that process is stopped automatically.
- If another program holds it, the script stops with that program's PID and command line. Free the port, or change `BACKEND_PORT` / `FRONTEND_PORT` in `.env`.

**Requirements:** Python ≥ 3.10 (with `venv`) and Node.js ≥ 18. PostgreSQL is optional.

### Demo scenario (what to click)

1. **Optimise plan** (top bar). Routes for the 100 demo orders are built with the default algorithm and shown on **Route & dispatch**. **Advanced settings** holds the algorithm details and cost weights.
2. **Dispatch fleet**. The vans leave their hub; vans whose first customer is later wait at the hub ("Departs 11:24").
3. On the **Live map**, click a van to see its route, numbered stops, ETAs, load, speed and fuel.
4. **Events → Urgent order / Traffic jam / Close a road**. The engine re-plans; the activity feed and toasts show which van took the order and why.
5. **Alternative roads** (on a van) compares Yen's K-shortest paths and the three shortest-path algorithms for its next leg.
6. **⏹ Stop** returns to planning with the same plan; **↺ Reset** starts over.
7. **Review results** → **Analytics**; the **Algorithm lab** holds the visualizer, benchmarks and algorithm reference.

## 2. Algorithms (all in Python)

| Module | Algorithm | Used for | Reference |
|---|---|---|---|
| `shortest_path.py` | **Dijkstra** (binary heap) | Road legs; one-to-all runs build the travel-time matrix | Dijkstra 1959 |
| `shortest_path.py` | **A\* search** | Default point-to-point routing. Heuristic = straight-line distance ÷ max speed limit, which is admissible | Hart, Nilsson & Raphael 1968 |
| `shortest_path.py` | **Bidirectional Dijkstra** | Alternative point-to-point search | Pohl 1971 |
| `shortest_path.py` | **Floyd–Warshall** | All-pairs reference on small graphs (benchmarks) | Floyd 1962 |
| `shortest_path.py` | **Yen's K-shortest loopless paths** | "Alternatives" / "why this road?" | Yen 1971 |
| `construction.py` | **FIFO baseline** | The naive dispatcher everything is compared against | – |
| `construction.py` | **Nearest Neighbour** | Greedy CVRP construction | Rosenkrantz et al. 1977 |
| `construction.py` | **Clarke–Wright Savings** (parallel) | CVRP construction | Clarke & Wright 1964 |
| `construction.py` | **Sweep** | Polar-angle clustering, then sequencing | Gillett & Miller 1974 |
| `construction.py` | **Regret-2 insertion** | Leftover orders and **dynamic order insertion** | Potvin & Rousseau 1993 |
| `local_search.py` | **2-opt**, **Or-opt** | Intra-route improvement | Croes 1958; Or 1976 |
| `local_search.py` | **Relocate**, **Swap** with granular neighbourhoods | Inter-route improvement | Savelsbergh 1992; Toth & Vigo 2003 |
| `local_search.py` | **Variable Neighbourhood Descent** | Operator control loop | Mladenović & Hansen 1997 |
| `genetic.py` | **Genetic Algorithm** (giant tour, **Prins Split**, OX crossover, tournament selection, elitism, memetic local search) | Meta-heuristic optimisation | Prins 2004; Davis 1985 |
| `ortools_solver.py` | Google OR-Tools, Guided Local Search | **Comparison only**, never the primary engine | – |

### Optimisation model (CVRPTW)

```
min Z = α·D + β·T + γ·L + δ·V + ε·W + ζ·B   (+ overtime, capacity and unassigned penalties)
```

| Symbol | Meaning |
|---|---|
| D | Total distance (km) |
| T | Total route duration (min), including waiting |
| L | Lateness after each order's deadline (min), multiplied by that order's priority factor |
| V | Number of vehicles used. δ is paid once per day, so a van that has already worked today is not charged again. |
| W | Customer waiting: minutes between each order's ready time and its delivery |
| B | Workload balance: Σ ((work already done today + this route's work) / 60)², minus the part already done. It is convex, so the work is shared. |

T counts **work** (driving, handing over parcels, reloading). Idle waiting is not work.

Two operational rules complete the model:
- **Maximum route duration.** A soft constraint: every minute beyond `max_route_duration_min` costs `route_overtime_penalty_per_min`.
- **Held departures.** A parked vehicle waits at the depot instead of at its first customer. Waiting at the depot is not counted as route time, and the simulation holds the vehicle there, shown as "Scheduled · departs HH:MM".

Together with ε·W, these rules stop a single vehicle from collecting every new order while others are free.

Constraints, enforced in `vrp.py`:

- every order is delivered exactly once;
- the load of each loading segment fits the vehicle's capacity;
- time windows `[ready, deadline]` (arriving early means waiting; arriving late is penalised);
- vehicles start at their current position and return to their depot;
- routes follow the road graph.

The weights α, β, γ, δ come from `settings.yaml` and can be changed per run in the UI.

### Dynamic Vehicle Routing (Module 4)

The simulation advances a clock. Vehicles drive their A\* paths using the current (traffic-dependent) edge travel times. An event triggers **re-optimisation from the live state** (`engine.reoptimize`):

| Event | Response |
|---|---|
| New order | Regret-2 insertion over all vehicles, then local search. If the parcel is still at the warehouse, an en-route vehicle gets a **depot reload stop** before it. |
| Traffic congestion | Edge travel times are multiplied by the congestion factor; the travel-time matrix is rebuilt; routes are re-sequenced and re-pathed. |
| Road closure | The edge is removed from the search (connectivity is checked first); vehicles reroute at their next intersection. |
| Congestion expiry | Traffic is restored and vehicles are re-pathed. |

Rules that keep re-planning realistic:

- A parcel already loaded on a vehicle stays on that vehicle. Only its position in the sequence may change.
- Deliveries already completed, or in progress, are never touched.
- A vehicle in the middle of a road segment finishes that segment before taking a new path.

Every event records the **static policy** (keep the plan, append new orders) next to the **re-optimised** plan, with the candidate vehicles and Δcost of each insertion. The Analytics page charts these per event.

Strategies, set by `simulation.reoptimize_strategy`:

| Strategy | Behaviour |
|---|---|
| `insertion` | Regret-2 insertion only. |
| `insertion_plus_local_search` | Insertion, then local search (default). |
| `full` | All not-yet-loaded orders are re-inserted from scratch, then local search. |

### Performance engineering notes

- **Travel-time matrix.** Built with |S| one-to-all Dijkstra runs over the stop nodes S, instead of Floyd–Warshall's O(V³).
- **Cached heuristic data.** A\* uses a precomputed planar projection and a cached max speed, so evaluating the heuristic costs O(1).
- **Fast route cost.** `route_cost` has an inlined path for the common case and is the hot loop of every heuristic.
- **Granular neighbourhoods.** These cut inter-route moves from O(n²) to O(n·k).
- **GA decoding.** Prins Split runs in O(n·L) per chromosome.
- **Path memo.** The simulation's shortest paths are memoised and invalidated whenever traffic changes (`RoadNetwork.version`).

---

### The map: Vijayawada (OpenStreetMap)

The road network within `city.osm.radius_m` (3 km) of `city.center_lat/lon` (central Vijayawada) is loaded from the OpenStreetMap Overpass API. Three mirrors are tried.

How the graph is built:
- One-way streets and roundabouts are respected.
- `maxspeed` is used where tagged; otherwise the speed comes from the per-road-type table in `settings.yaml`.
- Chains of shape points are contracted into single edges that keep the road geometry, so routes and moving vehicles follow the real curves.
- Only the largest strongly connected component is kept, so every stop is reachable.

Caching:
- The download is cached in `backend/data/osm/`, so only the first start needs the internet.
- If the API is unreachable and nothing is cached, the app shows that the map must be downloaded with `./set-up.sh`. There is no substitute map.
- A failed download is retried at most every `retry_after_min` minutes.
- The generated grid city (`CITY_SOURCE=synthetic`) exists only for the automated tests and for benchmark graphs of controlled size.

Moving data between graphs:
- When the graph changes, existing depots and orders are kept and re-snapped to the nearest intersection.

Map tiles:
- **Tiles** (CARTO light basemap by default, no key needed) are drawn under the Vijayawada roads.
- If tiles fail to load, the map falls back to drawing the road graph.
- `MAP_TILE_URL` in `.env` sets another provider. Put `{apikey}` in the URL and set `CARTO_API_KEY` for a keyed one.

## 3. Architecture

```
React (Vite, Tailwind, Leaflet, Recharts)
   │  REST /api/*        WebSocket /ws (live snapshot on every engine revision)
   ▼
FastAPI  ──►  LogisticsEngine (in-memory state, lock-protected, write-through to DB)
                 ├─ city_generator   → RoadNetwork  G=(V,E), w = distance | traffic-aware time
                 ├─ seeding          → depots, fleet, orders (Faker + seeded RNG)
                 ├─ optimizer        → builds CVRPTW instances, runs algorithms, explains plans
                 ├─ simulation loop  → clock, vehicle movement, deliveries, events
                 ├─ analytics        → KPIs, before/after, events, charts
                 └─ benchmark        → algorithm-engineering experiments
SQLAlchemy  →  SQLite / PostgreSQL (orders, vehicles, depots, optimisation runs, events, benchmarks)
```

### Directory layout

```
intelligent-logistics/
├── README.md  set-up.sh  run.sh  .env.example
├── backend/
│   ├── config/settings.yaml          # every scenario / algorithm parameter (nothing hard-coded)
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py                   # FastAPI app, WebSocket, simulation loop
│   │   ├── core/                     # settings loader, geo + time helpers
│   │   ├── algorithms/               # graph, shortest paths, matrix, VRP model, heuristics, GA, OR-Tools
│   │   ├── services/                 # engine, optimizer, seeding, city generator, analytics, benchmark
│   │   ├── api/routes/               # network, orders, fleet, optimisation, simulation, analytics
│   │   ├── db/                       # SQLAlchemy engine + models
│   │   └── schemas/                  # Pydantic request models
│   ├── scripts/run_benchmarks.py     # CLI experiments → results/*.csv, *.md
│   └── tests/                        # pytest: algorithm correctness + full API flow
├── frontend/
│   ├── src/theme/tokens.js           # design tokens (shared by Tailwind and the map/charts)
│   ├── src/components/{ui,map,layout}
│   ├── src/pages/                    # LiveMap, Dispatch, Orders, Fleet, Analytics, Lab
│   └── src/hooks/                    # live WebSocket state, network, API, toasts
└── results/                          # benchmark output
```

---

## 4. Configuration (nothing is hard-coded)

- **`.env`** holds runtime settings: ports, `DATABASE_URL`, CORS, optional overrides (`RANDOM_SEED`, `ORDER_COUNT`, `VEHICLE_COUNT`) and `AUTOSTART_SIMULATION`.
- **`backend/config/settings.yaml`** holds the scenario and algorithms:
  - city grid size, block size, road speeds, arterials and diagonals;
  - vehicle types (capacity, fuel use, CO₂, tank size);
  - order weight, priority mix, time windows and service times;
  - shift hours and objective weights;
  - default algorithms, GA parameters, local-search limits;
  - congestion parameters, random-event probabilities;
  - benchmark sizes and basemap tiles.

To change the scenario, edit the YAML and run `./set-up.sh --reseed`, or use **Reset** with `regenerate: true` from the API.

**PostgreSQL:**

```bash
createdb logistics
# .env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/logistics
./set-up.sh --reseed
```

The map has two basemaps. **Schematic** draws the exact road graph the algorithms use. **Tiles** draws OpenStreetMap/CARTO tiles underneath; the tile URL is set in `settings.yaml`. The city graph is procedurally generated around the configured centre, so its streets do not match the real streets under the tiles.

---

## 5. API overview

| Method & path | Purpose |
|---|---|
| `GET /api/network` | Road graph (roads, bounds, street names) |
| `POST /api/network/path` | Run Dijkstra, A\*, bidirectional Dijkstra, Floyd–Warshall and Yen's K-shortest on one query |
| `POST /api/network/path/trace` | Exploration order of each algorithm, used by the step-by-step visualizer |
| `GET /api/config` | Live algorithm, objective and benchmark configuration |
| `GET /api/orders?page&page_size&status&priority&q&sort&direction` | Paginated, filtered order list (indexed SQL) with per-status counts |
| `GET /api/orders/markers` | Compact map markers (id, code, lat, lon, status, priority) |
| `POST /api/orders`, `POST /api/orders/generate` | Create one order / generate random orders |
| `POST /api/orders/{id}/cancel` | Cancel: keeps the record and removes it from routes |
| `DELETE /api/orders/{id}?include_delivered=` | Permanently delete one order |
| `POST /api/orders/bulk-delete/preview`, `POST /api/orders/bulk-delete`, `POST /api/orders/clear` | Bulk delete by ids or filter, in one transaction. Delivered history is kept unless `include_delivered=true`. |
| `GET/POST /api/vehicles`, `PATCH /api/vehicles/{id}` (capacity, driver, active, **depot_id**) | Fleet management; moving a parked vehicle to another hub |
| `GET /api/vehicles/{id}/route`, `GET /api/routes`, `GET /api/vehicles/{id}/alternatives` | Route geometry on demand; Yen's alternatives |
| `GET/POST /api/depots` (`move_vehicles`) | Hubs with vehicle and open-order counts. Orders go to the nearest hub that has active vehicles. |
| `GET /api/optimization/algorithms` | Available algorithms and defaults |
| `POST /api/optimization/run` | Optimise with `{algorithm, shortest_path, operators, weights, ga}` |
| `POST /api/optimization/compare` | Run every algorithm on the same orders |
| `POST /api/optimization/reoptimize` | Dynamic re-optimisation from the live state |
| `GET /api/optimization/plan`, `GET /api/optimization/runs/{id}` | Active plan with explanation; stored runs |
| `POST /api/simulation/{start,pause,step,reset,speed,random-events}` | Simulation control |
| `POST /api/simulation/events/{new-order,congestion,closure,clear-traffic}` | Dynamic events |
| `GET /api/analytics/summary` | Dashboard data |
| `POST /api/benchmarks`, `POST /api/benchmarks/cancel`, `GET /api/benchmarks/{status,runs,runs/{id},latest,defaults}` | Isolated, cancellable experiments with incremental results |
| `WS /ws` | Live simulation snapshot |

---

## 6. Experiments (Algorithm Engineering)

Run them from **Algorithm lab → Performance experiments** or with `./run.sh bench`.

| # | Comparison | Measured |
|---|---|---|
| 1 | Dijkstra vs A\* vs Bidirectional Dijkstra vs Floyd–Warshall, over graph sizes | Runtime per query, nodes expanded, path cost, peak memory, CPU time |
| 2 | FIFO vs NN vs Clarke–Wright vs Sweep vs CW+local search vs pure GA vs memetic GA vs OR-Tools, over order counts | Objective Z, distance, late deliveries, vehicles, feasibility, wall time, CPU time, peak memory |
| 3 | Static vs dynamic routing | Logged automatically for every simulated event (Analytics page) |
| 4 | Greedy vs optimised allocation | Before/after panel: utilisation, vehicles used, fuel, CO₂ |

Wall time and CPU time come from `perf_counter` and `process_time`. Peak memory comes from `tracemalloc`.

Typical findings (synthetic grids of controlled size, and the Vijayawada map):

- **Shortest paths.** All exact algorithms return identical costs. A\* expands about 3–10× fewer nodes than Dijkstra. Floyd–Warshall is only worth it on very small graphs.
- **Construction only.** Constructive heuristics are fast but violate many time windows.
- **Local search.** Adding local search removes almost all late deliveries.
- **Genetic algorithm.** A pure GA scales poorly; seeding it with heuristics and adding local search (the memetic GA) fixes that. This is consistent with the VRPTW review's emphasis on hybrid methods: about 40% of the surveyed work combines two or more algorithms.

---

## 6b. Performance engineering (measured)

Measured on the same 100-order scenario on the development machine, before and after this rework:

| Path | Before | After |
|---|---|---|
| Optimise, Clarke–Wright | 6.98 s; engine locked for the whole run | 5.15 s with the richer cost model; the solve runs **outside** the lock |
| Live-state requests during a 23 s GA optimisation | blocked until it finished (it held the lock) | 367 requests, median 4.4 ms, max 25 ms |
| DB queries: one optimisation | > 200 (one transaction per order) | 2 (one batched transaction) |
| DB queries: dispatch + 30 simulation ticks | 218 | 10 |
| Live WebSocket snapshot | 59 KB per tick | about 37–42 KB per tick; trails and future routes are fetched only for the selected vehicle |
| Orders list | whole table on every delivery (45 KB) | one page of 25 via indexed SQL (11 KB, about 5 ms) |
| Road network | 186 KB on every page load | gzip on the wire (17 KB), plus an ETag |
| 500-order benchmark | hung the run (all results lost) | every experiment in its own process with a timeout; results saved after each one |

Where these changes live:
- **Insertion step.** Regret-2 insertion caches the insertion options for each route.
- **Database.** Order writes are buffered and flushed in one transaction per engine operation. If a write fails, the changes stay in memory and are retried, and the UI shows a warning.
- **Indexes.** Indexes on `status`, `priority`, `vehicle_id`, `delivered_min`, `kind` and `sim_min` are added non-destructively to existing databases (`app/db/migrate.py`).

## 7. Tests

```bash
./run.sh test
```

What the suite checks:

- **Shortest paths.** All algorithms agree with Floyd–Warshall on optimal costs (time and distance metrics). A\* never expands more nodes than Dijkstra. Yen's paths are distinct and sorted. Closed roads are avoided.
- **VRP.** Every construction serves every order exactly once within capacity. The fast route cost equals the full evaluator. Local search never worsens a solution. The optimised plan beats FIFO. GA elitism is monotone. Objective weights change the cost as specified.
- **API end to end.** Optimise, dispatch, step, then new order, congestion and closure, then analytics and the path query.
- **Orders.** Pagination, server-side search, cancel versus delete, bulk delete by filter, clear all.
- **Cost model.** No second fixed vehicle cost for a vehicle already working; the maximum route duration spreads work over several vehicles.
- **Road data.** The OpenStreetMap graph is built from a fixture in exact Overpass format: compact ids, contraction of road shapes, one-way streets, `maxspeed`, removal of unreachable parts. Also covered: cache use, a clear missing-map error, and remembering failures.
- **Visualizer.** The step-by-step trace endpoint.

---

## 8. Research foundation

- Liu, Chen, Por & Ku (2023), *A Systematic Literature Review of Vehicle Routing Problems with Time Windows*, Sustainability 15(15):12004. This motivates the CVRPTW model, the hybrid approach (construction + local search + meta-heuristic) and the evaluation metrics.
- *A review of recent advances in time-dependent vehicle routing*, European Journal of Operational Research (2024), [doi:10.1016/j.ejor.2024.06.016](https://doi.org/10.1016/j.ejor.2024.06.016). This motivates traffic-dependent travel times and re-optimisation.
- *Recent dynamic vehicle routing problems: A survey*, Computers & Industrial Engineering (2021), [ScienceDirect S0360835221005088](https://www.sciencedirect.com/science/article/pii/S0360835221005088). This motivates the dynamic request handling and the static vs. dynamic policy comparison.
- Prins (2004), *A simple and effective evolutionary algorithm for the vehicle routing problem*, Computers & OR. This is the source of the giant-tour GA with Split.
- Toth & Vigo (2003), *The granular tabu search and its application to the vehicle-routing problem*, INFORMS JoC. This is the source of the granular neighbourhoods.
