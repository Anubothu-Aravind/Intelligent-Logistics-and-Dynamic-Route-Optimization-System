"""Experimental evaluation (Algorithm Engineering).

Experiment 1  Dijkstra vs A* vs Bidirectional Dijkstra vs Floyd–Warshall per graph size
              -> runtime per query, nodes explored, path cost, peak memory
Experiment 2  FIFO, Nearest Neighbour, Clarke–Wright, Sweep, CW + local search, pure GA,
              memetic GA (and OR-Tools) per number of orders
              -> objective, distance, late deliveries, vehicles, utilisation,
                 improvement vs FIFO, runtime, CPU time, peak memory

Engineering:
* every experiment runs in a separate process ("spawn") -> the API/simulation is
  never blocked by the GIL and a runaway experiment is killed after a timeout
* results are persisted after EVERY experiment (a crash or cancel keeps them)
* progress = completed experiments / planned experiments (real, not estimated)
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import queue as queue_mod
import random
import threading
import time
import tracemalloc

from app.core.config import Scenario
from app.core.timeutil import hhmm_to_min

log = logging.getLogger("logistics.bench")

VRP_LABELS = {
    "fifo": "FIFO baseline", "nearest_neighbour": "Nearest Neighbour", "clarke_wright": "Clarke–Wright",
    "sweep": "Sweep", "clarke_wright_ls": "Clarke–Wright + local search", "genetic": "Genetic algorithm (pure)",
    "memetic_ga": "Memetic GA (seeded + local search)", "ortools": "OR-Tools GLS (reference)",
}
SP_LABELS = {"dijkstra": "Dijkstra", "astar": "A*", "bidirectional_dijkstra": "Bidirectional Dijkstra",
             "floyd_warshall": "Floyd–Warshall"}

STATUS: dict = {"running": False, "run_id": None, "progress": 0.0, "done": 0, "total": 0, "message": "idle",
                "current": None, "results": None, "error": None}
_lock = threading.Lock()
_cancel = threading.Event()
_current_proc: dict = {"p": None}


# ======================================================================= child jobs
def _measure(fn):
    tracemalloc.start()
    c0, w0 = time.process_time(), time.perf_counter()
    out = fn()
    wall, cpu = (time.perf_counter() - w0) * 1000, (time.process_time() - c0) * 1000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return out, wall, cpu, peak / 1024


def sp_job(data: dict, rows: int, cols: int, queries: int, seed: int, algos: list[str]) -> list[dict]:
    from app.algorithms.shortest_path import astar, bidirectional_dijkstra, dijkstra, floyd_warshall
    from app.services.city_generator import generate_city
    sc = Scenario(data)
    if rows == 0:                       # the application's real map (cached download)
        from app.core.config import DATA_DIR
        from app.services.city_generator import load_network
        net, _ = load_network({**sc.section("city"), "source": "osm"}, seed, DATA_DIR)
    else:
        net, _ = generate_city(sc.section("city"), seed, rows=rows, cols=cols)
    rng = random.Random(seed)
    ids = list(net.nodes)
    pairs = [(rng.choice(ids), rng.choice(ids)) for _ in range(queries)]
    fns = {"dijkstra": dijkstra, "astar": astar, "bidirectional_dijkstra": bidirectional_dijkstra}
    out = []
    base = {"graph": sc.get("city.name", "city") if rows == 0 else f"{rows}x{cols}", "nodes": len(net.nodes), "edges": len(net.edges)}
    for name in algos:
        if name in fns:
            res, wall, cpu, peak = _measure(lambda: [fns[name](net, a, b, "time") for a, b in pairs])
            out.append({**base, "algorithm": name, "label": SP_LABELS[name], "status": "ok",
                        "avg_runtime_ms": round(sum(x.runtime_ms for x in res) / len(res), 4),
                        "avg_expanded": round(sum(x.expanded for x in res) / len(res), 1),
                        "avg_cost_min": round(sum(x.cost for x in res) / len(res), 4),
                        "cpu_ms_total": round(cpu, 2), "peak_kb": round(peak, 1)})
        elif name == "floyd_warshall":
            if len(net.nodes) > int(sc.get("algorithms.floyd_warshall_max_nodes")):
                out.append({**base, "algorithm": name, "label": SP_LABELS[name], "status": "skipped",
                            "note": f"> floyd_warshall_max_nodes ({sc.get('algorithms.floyd_warshall_max_nodes')}): O(V³)"})
                continue
            (idx, dist, _, ms), wall, cpu, peak = _measure(lambda: floyd_warshall(net, "time"))
            costs = [dist[idx[a]][idx[b]] for a, b in pairs]
            out.append({**base, "algorithm": name, "label": SP_LABELS[name], "status": "ok",
                        "avg_runtime_ms": round(ms / len(pairs), 4), "precompute_ms": round(ms, 1),
                        "avg_expanded": len(net.nodes), "avg_cost_min": round(sum(costs) / len(costs), 4),
                        "cpu_ms_total": round(cpu, 2), "peak_kb": round(peak, 1)})
    return out


def synthetic_instance(sc: Scenario, n_orders: int, n_vehicles: int, seed: int):
    from app.algorithms.vrp import Weights
    from app.services import optimizer
    from app.services.city_generator import generate_city
    rng = random.Random(seed)
    side = max(10, int((n_orders * 2.5) ** 0.5))
    net, _ = generate_city(sc.section("city"), seed, rows=side, cols=side)
    oc = sc.section("orders")
    start = hhmm_to_min(sc.get("schedule.shift_start"))
    depot = net.nearest_node(float(sc.get("city.center_lat")), float(sc.get("city.center_lon")))
    pnames = list(oc["priorities"])
    ids = list(net.nodes)
    orders = []
    for i in range(n_orders):
        node = rng.choice(ids)
        lat, lon = net.nodes[node]
        dl = start + rng.uniform(oc["deadline_offset_min"]["min"], oc["deadline_offset_min"]["max"])
        orders.append({"id": i + 1, "node_id": node, "lat": lat, "lon": lon,
                       "weight_kg": rng.uniform(oc["weight_kg"]["min"], oc["weight_kg"]["max"]),
                       "priority": rng.choices(pnames, [oc["priorities"][p][0] for p in pnames])[0],
                       "ready_min": dl - rng.uniform(oc["time_window_min"]["min"], oc["time_window_min"]["max"]),
                       "deadline_min": dl,
                       "service_min": rng.uniform(oc["service_time_min"]["min"], oc["service_time_min"]["max"])})
    types = sc.get("fleet.types")
    total = sum(o["weight_kg"] for o in orders)
    vehicles = []
    for k in range(n_vehicles):
        t = types[k % len(types)]
        vehicles.append({"id": k + 1, "code": f"{t['prefix']}-{k}", "capacity_kg": float(t["capacity_kg"]),
                         "fuel_l_per_100km": t["fuel_l_per_100km"], "co2_kg_per_l": t["co2_kg_per_l"]})
    cap = sum(v["capacity_kg"] for v in vehicles)
    if cap < total * 1.2:                         # the fleet must be able to carry the demand
        for v in vehicles:
            v["capacity_kg"] *= total * 1.2 / cap
    w = Weights.from_scenario(sc.section("objective"))
    pm = {k: float(v[1]) for k, v in oc["priorities"].items()}
    starts = [optimizer.VehicleStart(v, depot, start, True) for v in vehicles]
    return optimizer.build_instance(net, depot, starts, orders, w, pm, 0.0), net


def vrp_job(data: dict, n: int, vehicles: int, seed: int, ga_generations: int, algo: str) -> dict:
    from app.algorithms import construction, genetic, local_search, ortools_solver
    from app.algorithms.vrp import DEPOT, evaluate_solution
    sc = Scenario(data)
    bi, net = synthetic_instance(sc, n, vehicles, seed)
    inst = bi.inst
    ops = list(sc.get("algorithms.default_improvement"))
    rounds = int(sc.get("algorithms.local_search_max_iterations"))
    ls_limit = float(sc.get("algorithms.local_search_time_limit_s")) * 4
    knb = int(sc.get("algorithms.granular_neighbours"))
    ga = lambda: genetic.GAParams.from_config(sc.section("algorithms")["genetic"], seed, {"generations": ga_generations})  # noqa: E731
    runners = {
        "fifo": lambda: construction.fifo(inst),
        "nearest_neighbour": lambda: construction.nearest_neighbour(inst),
        "clarke_wright": lambda: construction.clarke_wright(inst),
        "sweep": lambda: construction.sweep(inst),
        "clarke_wright_ls": lambda: local_search.improve(inst, construction.clarke_wright(inst), ops, rounds, ls_limit, knb)[0],
        "genetic": lambda: genetic.genetic_algorithm(inst, ga(), None, None),
        "memetic_ga": lambda: genetic.genetic_algorithm(
            inst, ga(), [construction.CONSTRUCTIONS[a](inst) for a in ("nearest_neighbour", "clarke_wright", "sweep")],
            ops, rounds, ls_limit, knb),
        "ortools": lambda: ortools_solver.solve(inst, int(sc.get("algorithms.ortools_time_limit_s"))),
    }
    if algo == "ortools" and not ortools_solver.AVAILABLE:
        return {"orders": n, "algorithm": algo, "label": VRP_LABELS[algo], "status": "skipped", "note": "OR-Tools not installed"}
    sol, wall, cpu, peak = _measure(runners[algo])
    m = evaluate_solution(inst, sol)
    base = evaluate_solution(inst, construction.fifo(inst))["cost"]
    used = [k for k, r in enumerate(sol.routes) if any(c != DEPOT for c in r)]
    cap = sum(inst.vehicles[k].capacity for k in used)
    load = sum(inst.demand[c] for k in used for c in sol.routes[k] if c != DEPOT)
    return {"orders": n, "graph_nodes": len(net.nodes), "algorithm": algo, "label": VRP_LABELS[algo], "status": "ok",
            "objective": round(m["cost"], 2), "distance_km": round(m["distance_km"], 2),
            "late_count": m["late_count"], "vehicles_used": m["vehicles_used"], "feasible": m["feasible"],
            "utilization": round(load / cap, 4) if cap else 0.0,
            "improvement_vs_fifo_pct": round((base - m["cost"]) / base * 100, 2) if base else 0.0,
            "runtime_ms": round(wall, 2), "cpu_ms": round(cpu, 2), "peak_kb": round(peak, 1),
            "matrix_ms": round(bi.matrix.runtime_ms, 2)}


def _child(q, fn_name, args):
    try:
        q.put(("ok", globals()[fn_name](*args)))
    except Exception as exc:  # reported to the parent as a failed experiment
        q.put(("error", f"{type(exc).__name__}: {exc}"))


def run_isolated(fn_name: str, args: tuple, timeout_s: float):
    """Run a job in a fresh process; returns (status, payload). status: ok | error | timeout | cancelled."""
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=_child, args=(q, fn_name, args), daemon=True)
    p.start()
    _current_proc["p"] = p
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                return q.get(timeout=0.25)
            except queue_mod.Empty:
                pass
            if _cancel.is_set():
                return "cancelled", "cancelled by user"
            if time.monotonic() > deadline:
                return "timeout", f"exceeded {timeout_s:.0f} s"
            if not p.is_alive() and q.empty():
                return "error", f"worker exited with code {p.exitcode}"
    finally:
        if p.is_alive():
            p.terminate()
        p.join(2)
        _current_proc["p"] = None


# ======================================================================= orchestration
def plan_jobs(sc: Scenario, params: dict) -> list[dict]:
    bc = sc.section("benchmark")
    seed = int(params.get("seed") or sc.get("random_seed"))
    sp_algos = [a for a in (params.get("shortest_path_algorithms") or bc["shortest_path_algorithms"]) if a in SP_LABELS]
    vrp_algos = [a for a in (params.get("vrp_algorithms") or bc["vrp_algorithms"]) if a in VRP_LABELS]
    if not params.get("include_ortools", True):
        vrp_algos = [a for a in vrp_algos if a != "ortools"]
    jobs = []
    if sp_algos:
        for r, c in params.get("graph_sizes") or bc["graph_sizes"]:
            jobs.append({"kind": "shortest_path", "label": f"shortest paths on {sc.get('city.name') if r == 0 else f'{r}x{c}'}", "fn": "sp_job",
                         "args": (sc.data, int(r), int(c), int(params.get("path_queries") or bc["path_queries"]), seed, sp_algos)})
    for n in params.get("vrp_sizes") or bc["vrp_sizes"]:
        for a in vrp_algos:
            jobs.append({"kind": "vrp", "label": f"{VRP_LABELS[a]} on {n} orders", "fn": "vrp_job", "algo": a, "orders": n,
                         "args": (sc.data, int(n), int(params.get("vrp_vehicles") or bc["vrp_vehicles"]), seed,
                                  int(params.get("ga_generations") or bc["ga_generations"]), a)})
    return jobs


def execute(sc: Scenario, params: dict, on_progress=None) -> dict:
    """Run all jobs sequentially, each isolated. on_progress(results) is called after every job."""
    jobs = plan_jobs(sc, params)
    timeout = float(params.get("timeout_s") or sc.get("benchmark.experiment_timeout_s"))
    results = {"shortest_path": [], "vrp": [], "failures": []}
    STATUS.update(total=len(jobs), done=0)
    for i, job in enumerate(jobs):
        if _cancel.is_set():
            break
        STATUS.update(current=job["label"], message=f"running {job['label']}")
        status, payload = run_isolated(job["fn"], job["args"], timeout)
        if status == "ok":
            results[job["kind"]].extend(payload if isinstance(payload, list) else [payload])
        else:
            row = {"experiment": job["label"], "status": status, "note": payload}
            results["failures"].append(row)
            if job["kind"] == "vrp":
                results["vrp"].append({"orders": job["orders"], "algorithm": job["algo"],
                                       "label": VRP_LABELS[job["algo"]], "status": status, "note": payload})
        STATUS.update(done=i + 1, progress=round((i + 1) / max(1, len(jobs)), 4), results=results)
        if on_progress:
            on_progress(results)
    return results


def start_async(sc: Scenario, params: dict, create_run, save_run) -> bool:
    """create_run(params) -> id ; save_run(id, results, status)."""
    with _lock:
        if STATUS["running"]:
            return False
        _cancel.clear()
        run_id = create_run(params)
        STATUS.update(running=True, run_id=run_id, progress=0.0, done=0, total=0, message="starting",
                      current=None, results=None, error=None)

    def worker():
        final = "finished"
        try:
            res = execute(sc, params, lambda r: save_run(run_id, r, "running"))
            final = "cancelled" if _cancel.is_set() else "finished"
            save_run(run_id, res, final)
            STATUS.update(message=final, results=res)
        except Exception as exc:
            final = "failed"
            log.exception("benchmark failed")
            STATUS.update(error=str(exc), message="failed")
            save_run(run_id, STATUS.get("results") or {"shortest_path": [], "vrp": [], "failures": []}, final)
        finally:
            STATUS["running"] = False

    threading.Thread(target=worker, daemon=True, name="benchmark").start()
    return True


def cancel() -> bool:
    if not STATUS["running"]:
        return False
    _cancel.set()
    return True
