"""Bridges live data (orders, vehicles, road graph) and the algorithm package."""
from __future__ import annotations

import time
import tracemalloc
from dataclasses import dataclass, field

from app.algorithms import construction, genetic, local_search, ortools_solver
from app.algorithms.graph import INF, RoadNetwork
from app.algorithms.matrix import StopMatrix, build_matrix
from app.algorithms.shortest_path import shortest_path
from app.algorithms.vrp import DEPOT, Instance, Solution, VehicleSpec, Weights, evaluate_solution
from app.core.geo import polar_angle
from app.core.timeutil import min_to_hhmm

ROUTING_ALGORITHMS = {
    "fifo": "FIFO baseline (orders in arrival order)",
    "nearest_neighbour": "Nearest Neighbour + local search",
    "clarke_wright": "Clarke–Wright Savings + local search",
    "sweep": "Sweep (Gillett–Miller) + local search",
    "genetic": "Genetic Algorithm (Prins split, OX) + local search",
    "ortools": "Google OR-Tools GLS (reference)",
}
LOCAL_SEARCH_OPERATORS = ["two_opt", "or_opt", "relocate", "swap"]


@dataclass
class VehicleStart:
    vehicle: dict
    start_node: int
    start_time: float
    at_depot: bool
    onboard: set[int] = field(default_factory=set)        # order ids
    used_today: bool = False
    prior_work_min: float = 0.0


@dataclass
class BuiltInstance:
    inst: Instance
    matrix: StopMatrix
    point_nodes: list[int]
    point_order: dict[int, int]          # point index -> order id
    order_point: dict[int, int]          # order id -> point index
    vehicles: list[VehicleStart]


def build_instance(net: RoadNetwork, depot_node: int, starts: list[VehicleStart], orders: list[dict],
                   weights: Weights, priority_mult: dict[str, float], depot_dwell: float) -> BuiltInstance:
    point_nodes = [depot_node]
    point_order, order_point = {}, {}
    for o in orders:
        order_point[o["id"]] = len(point_nodes)
        point_order[len(point_nodes)] = o["id"]
        point_nodes.append(o["node_id"])
    start_points = []
    for s in starts:
        if s.at_depot and s.start_node == depot_node:
            start_points.append(DEPOT)
        else:
            start_points.append(len(point_nodes))
            point_nodes.append(s.start_node)
    matrix = build_matrix(net, point_nodes)
    n = len(point_nodes)
    demand, service = [0.0] * n, [0.0] * n
    ready, deadline, pm = [0.0] * n, [INF] * n, [0.0] * n
    lat0, lon0 = net.nodes[depot_node]
    angle = [0.0] * n
    for o in orders:
        p = order_point[o["id"]]
        demand[p], service[p] = o["weight_kg"], o["service_min"]
        ready[p], deadline[p] = o["ready_min"], o["deadline_min"]
        pm[p] = priority_mult.get(o["priority"], 1.0)
        angle[p] = polar_angle(lat0, lon0, o["lat"], o["lon"])
    vehicles = [
        VehicleSpec(s.vehicle["id"], s.vehicle["capacity_kg"], sp, s.start_time, s.at_depot,
                    frozenset(order_point[i] for i in s.onboard if i in order_point), s.used_today, s.prior_work_min)
        for s, sp in zip(starts, start_points)
    ]
    inst = Instance(matrix.time, matrix.dist, demand, service, ready, deadline, pm,
                    list(point_order), vehicles, weights, depot_dwell, angle)
    return BuiltInstance(inst, matrix, point_nodes, point_order, order_point, starts)


def solve(bi: BuiltInstance, algorithm: str, operators: list[str], ls_rounds: int,
          ga_params: genetic.GAParams | None, ortools_limit: int,
          arrival_order: list[int] | None = None, ls_time_limit_s: float | None = None,
          k_nb: int = 12) -> tuple[Solution, list[dict]]:
    inst = bi.inst
    stages: list[dict] = []

    def stage(name: str, sol: Solution, t0: float, **extra):
        stages.append({"stage": name, "cost": round(evaluate_solution(inst, sol)["cost"], 2),
                       "runtime_ms": round((time.perf_counter() - t0) * 1000, 2), **extra})

    t0 = time.perf_counter()
    if algorithm == "fifo":
        order_pts = [bi.order_point[o] for o in (arrival_order or []) if o in bi.order_point]
        sol = construction.fifo(inst, order_pts or None)
        stage("FIFO assignment", sol, t0)
        return sol, stages
    if algorithm in ("nearest_neighbour", "clarke_wright", "sweep"):
        sol = construction.CONSTRUCTIONS[algorithm](inst)
        stage(f"{ROUTING_ALGORITHMS[algorithm].split(' +')[0]} construction", sol, t0)
    elif algorithm == "genetic":
        if ga_params is None:
            raise ValueError("GA parameters missing")
        seeds = [construction.CONSTRUCTIONS[a](inst) for a in ("nearest_neighbour", "clarke_wright", "sweep")]
        stage("Heuristic seeds (NN, CW, Sweep)", min(seeds, key=lambda s: evaluate_solution(inst, s)["cost"]), t0)
        t0 = time.perf_counter()
        sol = genetic.genetic_algorithm(inst, ga_params, seeds, operators, ls_rounds, ls_time_limit_s, k_nb)
        stage("Genetic algorithm (memetic)", sol, t0, generations=len(sol.history) - 1)
        return sol, stages
    elif algorithm == "ortools":
        sol = ortools_solver.solve(inst, ortools_limit)
        stage("OR-Tools guided local search", sol, t0)
        return sol, stages
    else:
        raise ValueError(f"Unknown routing algorithm '{algorithm}'")
    if operators:
        t0 = time.perf_counter()
        sol, gains = local_search.improve(inst, sol, operators, ls_rounds, ls_time_limit_s, k_nb)
        stage("Local search (VND)", sol, t0, gains={k: round(v, 2) for k, v in gains.items()})
    sol.algorithm = algorithm
    return sol, stages


def solution_metrics(bi: BuiltInstance, sol: Solution) -> dict:
    ev = evaluate_solution(bi.inst, sol)
    fuel = co2 = 0.0
    loads, caps = [], []
    for k, rev in enumerate(ev["routes"]):
        veh = bi.vehicles[k].vehicle
        litres = rev.distance_km * veh["fuel_l_per_100km"] / 100.0
        fuel += litres
        co2 += litres * veh["co2_kg_per_l"]
        if rev.used:
            loads.append(rev.load_kg)
            caps.append(veh["capacity_kg"])
    w = bi.inst.weights
    return {
        "objective": round(ev["cost"], 2),
        "distance_km": round(ev["distance_km"], 2),
        "duration_min": round(ev["duration_min"], 1),
        "lateness_min": round(ev["lateness_min"], 1),
        "late_count": ev["late_count"],
        "early_count": ev["early_count"],
        "vehicles_used": ev["vehicles_used"],
        "unassigned": ev["unassigned"],
        "overload_kg": round(ev["overload_kg"], 1),
        "feasible": ev["feasible"],
        "fuel_l": round(fuel, 2),
        "co2_kg": round(co2, 2),
        "utilization": round(sum(loads) / sum(caps), 4) if caps else 0.0,
        "makespan": min_to_hhmm(ev["makespan"]) if ev["makespan"] else None,
        "cost_breakdown": {
            "distance": round(w.alpha * ev["distance_km"], 2),
            "time": round(w.beta * sum(r.work_min for r in ev["routes"]), 2),
            "lateness": round(w.gamma * sum(r.weighted_lateness for r in ev["routes"]), 2),
            "vehicles": round(sum(w.fixed(bi.inst.vehicles[k].used_today) for k, r in enumerate(ev["routes"]) if r.used), 2),
            "overtime": round(sum(r.overtime_cost for r in ev["routes"]), 2),
            "waiting": round(w.epsilon * sum(r.waiting_min for r in ev["routes"]), 2),
            "balance": round(sum(r.balance_cost for r in ev["routes"]), 2),
            "penalties": round(sum(w.capacity_penalty * (r.overload_kg + 10 * r.invalid) for r in ev["routes"])
                               + w.unassigned_penalty * ev["unassigned"], 2),
        },
    }


def build_plan(net: RoadNetwork, bi: BuiltInstance, sol: Solution, orders: dict[int, dict],
               sp_algorithm: str) -> dict:
    """Turn a solution into map-ready routes: stops with ETA + node paths per leg."""
    ev = evaluate_solution(bi.inst, sol)
    routes, legs_total, expanded_total, sp_ms = [], 0, 0, 0.0
    for k, seq in enumerate(sol.routes):
        start = bi.vehicles[k]
        rev = ev["routes"][k]
        stops, arr_i = [], 0
        for p in seq:
            if p == DEPOT:
                stops.append({"type": "depot", "order_id": None, "node": bi.point_nodes[DEPOT]})
                continue
            oid = bi.point_order[p]
            o = orders[oid]
            eta = rev.arrivals[arr_i]
            arr_i += 1
            stops.append({
                "type": "order", "order_id": oid, "code": o["code"], "node": o["node_id"],
                "customer": o["customer_name"], "lat": o["lat"], "lon": o["lon"],
                "eta": round(eta, 1), "eta_hhmm": min_to_hhmm(eta), "deadline_hhmm": min_to_hhmm(o["deadline_min"]),
                "late": eta > o["deadline_min"], "weight_kg": o["weight_kg"], "priority": o["priority"],
            })
        nodes_seq = [start.start_node] + [s["node"] for s in stops]
        if stops:
            nodes_seq.append(bi.point_nodes[DEPOT])
        legs = []
        for a, b in zip(nodes_seq, nodes_seq[1:]):
            res = shortest_path(net, a, b, sp_algorithm)
            legs_total += 1
            expanded_total += res.expanded
            sp_ms += res.runtime_ms
            legs.append({"from": a, "to": b, "nodes": res.nodes,
                         "coords": net.path_coords(res.nodes),
                         "distance_m": round(res.distance_m, 1), "time_min": round(res.time_min, 2),
                         "expanded": res.expanded})
        veh = start.vehicle
        routes.append({
            "vehicle_id": veh["id"], "vehicle_code": veh["code"],
            "stops": stops, "legs": legs,
            "distance_km": round(rev.distance_km, 2), "duration_min": round(rev.duration_min, 1),
            "load_kg": round(rev.load_kg, 1), "capacity_kg": veh["capacity_kg"],
            "late_count": rev.late_count, "cost": round(rev.cost, 2), "feasible": rev.feasible,
            "end_hhmm": min_to_hhmm(rev.end_time) if rev.used else None,
        })
    return {
        "routes": routes,
        "unassigned": [bi.point_order[p] for p in sol.unassigned],
        "shortest_path": {"algorithm": sp_algorithm, "legs": legs_total,
                          "nodes_expanded": expanded_total, "runtime_ms": round(sp_ms, 2)},
        "matrix": {"points": len(bi.point_nodes), "dijkstra_runs": bi.matrix.dijkstra_runs,
                   "runtime_ms": round(bi.matrix.runtime_ms, 2)},
    }


def measured(fn, *args, **kwargs):
    """Run fn and return (result, wall_ms, cpu_ms, peak_kb)."""
    tracemalloc.start()
    w0, c0 = time.perf_counter(), time.process_time()
    try:
        out = fn(*args, **kwargs)
    finally:
        wall = (time.perf_counter() - w0) * 1000
        cpu = (time.process_time() - c0) * 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    return out, wall, cpu, peak / 1024
