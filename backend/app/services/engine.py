"""LogisticsEngine – the single in-memory source of truth.

* holds the road graph, fleet, orders and the active delivery plan
* runs the discrete-time simulation (vehicles follow their A* paths)
* reacts to dynamic events (new orders, congestion, road closures) with
  re-optimisation (Dynamic Vehicle Routing)
Everything mutating is guarded by a re-entrant lock; the database is written
through so state survives restarts.
"""
from __future__ import annotations

import copy
import logging
import math
import random
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy import delete as sql_delete, update as sql_update

from faker import Faker

from app.algorithms import construction, local_search
from app.algorithms.genetic import GAParams
from app.algorithms.graph import INF
from app.algorithms.shortest_path import shortest_path, yen_k_shortest
from app.algorithms.vrp import DEPOT, Solution, Weights, evaluate_solution, normalize_route
from app.core.config import DATA_DIR, get_scenario
from app.core.geo import haversine_m
from app.core.timeutil import hhmm_to_min, min_to_hhmm
from app.db import models
from app.db import migrate
from app.db.database import SessionLocal
from app.services import optimizer, seeding
from app.services.city_generator import MapUnavailable, graph_signature, load_network, street_of_node

log = logging.getLogger("logistics.engine")


class Conflict(RuntimeError):
    """The request conflicts with the current engine state (HTTP 409)."""

ORDER_FIELDS = ["id", "code", "customer_name", "address", "node_id", "lat", "lon", "weight_kg", "priority",
                "ready_min", "deadline_min", "service_min", "status", "vehicle_id", "source", "created_min",
                "delivered_min", "delivery_note"]
VEHICLE_FIELDS = ["id", "code", "model", "driver_name", "driver_since", "capacity_kg", "fuel_l_per_100km",
                  "co2_kg_per_l", "fuel_tank_l", "fuel_level_l", "depot_id", "active"]
DEPOT_FIELDS = ["id", "name", "address", "node_id", "lat", "lon"]


def _row(obj, fields) -> dict:
    return {f: getattr(obj, f) for f in fields}


@dataclass
class Stop:
    kind: str                 # order | depot | return
    node: int
    order_id: int | None = None


@dataclass
class VehicleRuntime:
    vehicle_id: int
    depot_node: int
    node: int
    lat: float
    lon: float
    status: str = "idle"      # idle | moving | servicing | reloading | done | blocked
    stops: list[Stop] = field(default_factory=list)
    planned_legs: list[list[int]] = field(default_factory=list)
    path: list[int] = field(default_factory=list)
    times: list[float] = field(default_factory=list)
    idx: int = 0
    target: Stop | None = None
    busy_until: float | None = None
    servicing_order: int | None = None
    service_arrival: float | None = None
    onboard: set[int] = field(default_factory=set)
    completed: list[dict] = field(default_factory=list)
    trail: list[list[float]] = field(default_factory=list)
    distance_m: float = 0.0
    work_min: float = 0.0          # driving + service minutes today (workload fairness)
    heading: float = 0.0
    speed_kmh: float = 0.0


class LogisticsEngine:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.revision = 0
        self.state_version = 0          # bumps whenever orders / fleet / plan inputs change
        self.ready = False
        self.boot_error: str | None = None
        self._depth = 0
        self._dirty: dict[int, dict] = {}
        self.persistence_error: str | None = None
        self._optimizing = False
        self.feed = deque(maxlen=50)
        self._feed_id = 1

    # ------------------------------------------------------------- transactions
    @contextmanager
    def _op(self):
        """Engine operation: holds the lock; buffered DB writes are flushed in ONE
        transaction when the outermost operation finishes."""
        with self.lock:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
                if self._depth == 0:
                    self._flush()

    def _flush(self) -> None:
        if not self._dirty:
            return
        rows = [{"id": oid, **changes} for oid, changes in self._dirty.items() if oid in self.orders]
        try:
            with SessionLocal.begin() as db:
                if rows:
                    db.execute(sql_update(models.Order), rows)
            self._dirty.clear()
            self.persistence_error = None
        except Exception as exc:          # keep the changes and retry on the next flush
            self.persistence_error = f"{type(exc).__name__}: {exc}"[:300]
            log.exception("could not persist %d order change(s); will retry", len(rows))

    # ================================================================ bootstrap
    def bootstrap(self, reseed: bool = False, seed: int | None = None) -> None:
        with self.lock:
            self.ready = False
            self.sc = get_scenario()
            if seed is not None:
                self.sc.data["random_seed"] = int(seed)
            self.seed = int(self.sc.get("random_seed"))
            t0 = time.perf_counter()
            try:
                self.net, self.city = load_network(self.sc.section("city"), self.seed, DATA_DIR)
            except MapUnavailable as exc:
                self.boot_error = str(exc)
                log.error("%s", exc)
                return
            self.boot_error = None
            self.city["load_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            log.info("road network: %s (%d intersections, %d road segments, %.0f ms)", self.city.get("city") or
                     self.city.get("source"), len(self.net.nodes), len(self.net.edges), self.city["load_ms"])
            self.rng = random.Random(self.seed + 1)
            self.faker = Faker(self.sc.get("city.name_locale"))
            self.faker.seed_instance(self.seed + 2)
            migrate.upgrade()
            signature = graph_signature(self.net)
            with SessionLocal() as db:
                if reseed or db.query(models.Depot).count() == 0:
                    seeding.seed_scenario(db, self.net, self.sc, self.rng, self.faker)
                else:
                    meta = db.get(models.AppMeta, "graph_signature")
                    if meta is None or meta.value != signature:
                        self._resnap(db)
                db.merge(models.AppMeta(key="graph_signature", value=signature))
                db.commit()
            self._dirty.clear()
            self._load()
            self.reset_simulation(drop_dynamic_orders=False, clear_plan=True)
            self.ready = True

    def _resnap(self, db) -> None:
        """The road graph changed (e.g. generated city -> real OSM roads): keep every
        existing depot and order, but move it to the nearest intersection of the new graph."""
        moved = 0
        for row in list(db.query(models.Depot)) + list(db.query(models.Order)):
            node = self.net.nearest_node(row.lat, row.lon)
            row.node_id = node
            row.lat, row.lon = self.net.nodes[node]
            moved += 1
        log.info("road graph changed – re-snapped %d depot/order records", moved)

    def _load(self) -> None:
        with SessionLocal() as db:
            self.depots = {d.id: _row(d, DEPOT_FIELDS) for d in db.query(models.Depot).all()}
            self.vehicles = {v.id: _row(v, VEHICLE_FIELDS) for v in db.query(models.Vehicle).order_by(models.Vehicle.id)}
            self.orders = {o.id: _row(o, ORDER_FIELDS) for o in db.query(models.Order).order_by(models.Order.id)}

    # ------------------------------------------------------------- persistence
    def _persist(self, model, obj_id: int, **changes) -> None:
        with SessionLocal() as db:
            row = db.get(model, obj_id)
            if row is None:
                return
            for k, v in changes.items():
                setattr(row, k, v)
            db.commit()

    def _set_order(self, oid: int, **changes) -> None:
        """Update in memory now; persisted in the operation's single DB transaction."""
        self.orders[oid].update(changes)
        self._dirty.setdefault(oid, {}).update(changes)

    def _feed(self, kind: str, message: str, **data) -> dict:
        item = {"id": self._feed_id, "sim_min": self.clock, "time": min_to_hhmm(self.clock),
                "type": kind, "message": message, **data}
        self._feed_id += 1
        self.feed.appendleft(item)
        return item

    def _bump(self, inputs_changed: bool = False) -> None:
        self.revision += 1
        if inputs_changed:
            self.state_version += 1

    # ================================================================ settings
    @property
    def shift_start(self) -> float:
        return hhmm_to_min(self.sc.get("schedule.shift_start"))

    @property
    def sp_algorithm(self) -> str:
        return self.active_settings.get("shortest_path") or self.sc.get("algorithms.default_shortest_path")

    def weights(self, overrides: dict | None = None) -> Weights:
        merged = dict(self.active_settings.get("weights") or {})
        merged.update(overrides or {})
        return Weights.from_scenario(self.sc.section("objective"), merged)

    def priority_mult(self) -> dict[str, float]:
        return {k: float(v[1]) for k, v in self.sc.get("orders.priorities").items()}

    def depot_node(self, depot_id: int) -> int:
        return self.depots[depot_id]["node_id"]

    def nearest_depot(self, node: int, among: set[int] | None = None) -> int:
        lat, lon = self.net.nodes[node]
        return min(among or self.depots, key=lambda d: haversine_m(lat, lon, self.depots[d]["lat"], self.depots[d]["lon"]))

    def active_vehicles(self) -> list[dict]:
        return [v for v in self.vehicles.values() if v["active"]]

    # ================================================================ simulation
    def reset_simulation(self, drop_dynamic_orders: bool = True, clear_plan: bool = True) -> None:
        with self._op():
            self.clock = self.shift_start
            self.running = False
            self.dispatched = False
            self.minutes_per_tick = float(self.sc.get("simulation.minutes_per_tick"))
            self.random_events = bool(self.sc.get("simulation.random_events.enabled"))
            self.feed = deque(maxlen=int(self.sc.get("simulation.event_feed_size")))
            self._feed_id = 1
            self.congestions: list[dict] = []
            self.closures: list[dict] = []
            self.net.reset_traffic()
            self._flush()
            self._dirty.clear()
            if not hasattr(self, "active_settings"):
                self.active_settings = {}
            with SessionLocal() as db:
                if drop_dynamic_orders:
                    db.query(models.Order).filter(models.Order.source == "simulated").delete()
                db.query(models.SimEvent).delete()
                db.query(models.Order).filter(models.Order.status != "cancelled").update(
                    {"status": "pending", "delivered_min": None, "delivery_note": None,
                     **({"vehicle_id": None} if clear_plan else {})})
                db.commit()
            self._load()
            self.runtime: dict[int, VehicleRuntime] = {}
            for v in self.vehicles.values():
                self._init_runtime(v)
            if clear_plan:
                self.plan = None
                self.plan_meta = None
            elif self.plan:
                self._apply_routes_from_plan()
            self._feed("system", "Simulation reset – all vehicles at their depot")
            self._bump(inputs_changed=True)

    def _init_runtime(self, v: dict) -> None:
        dn = self.depot_node(v["depot_id"])
        lat, lon = self.net.nodes[dn]
        self.runtime[v["id"]] = VehicleRuntime(v["id"], dn, dn, lat, lon, trail=[[lat, lon]])

    def _apply_routes_from_plan(self) -> None:
        for r in self.plan["routes"]:
            rt = self.runtime.get(r["vehicle_id"])
            if not rt:
                continue
            rt.stops = [Stop("order" if s["type"] == "order" else "depot", s["node"], s["order_id"])
                        for s in r["stops"]]
            rt.planned_legs = [leg["nodes"] for leg in r["legs"]]
            for s in rt.stops:
                if s.order_id:
                    self._set_order(s.order_id, vehicle_id=r["vehicle_id"], status="assigned")

    def set_running(self, running: bool) -> dict:
        with self._op():
            if running and not self.dispatched:
                if self.plan is None:
                    self.optimize({})
                elif any(o["status"] == "pending" for o in self.orders.values()):
                    self.reoptimize("dispatch", strategy="insertion")   # orders added after planning
                self._dispatch()
            self.running = running
            self._feed("system", "Simulation started" if running else "Simulation paused")
            self._bump(inputs_changed=True)
            return self.snapshot()

    def stop_run(self) -> dict:
        """Stop = end this run and go back to planning: clock to shift start, vehicles to
        their hubs, deliveries undone – every order and the current plan are kept."""
        with self._op():
            self.reset_simulation(drop_dynamic_orders=False, clear_plan=True)
            saved = getattr(self, "static_plan", None)
            if saved:
                plan, meta = copy.deepcopy(saved)
                ids = {st["order_id"] for r in plan["routes"] for st in r["stops"] if st.get("order_id")}
                if ids and ids <= set(self.orders):
                    self.plan, self.plan_meta = plan, meta
                    self._apply_routes_from_plan()
            extra = sum(1 for o in self.orders.values() if o["status"] == "pending")
            self._feed("system", "Run stopped – back to planning" + (f"; {extra} order(s) not in the plan yet" if extra else ""))
            self._bump(inputs_changed=True)
            return self.snapshot()

    def set_speed(self, minutes_per_tick: float) -> None:
        with self._op():
            self.minutes_per_tick = max(0.05, float(minutes_per_tick))
            self._bump()

    def _dispatch(self) -> None:
        self.dispatched = True
        for rt in self.runtime.values():
            self._load_at_depot(rt)
            if rt.stops:
                self._start_leg(rt, self.clock)
        self._feed("dispatch", f"Fleet dispatched at {min_to_hhmm(self.clock)}")

    def _load_at_depot(self, rt: VehicleRuntime) -> list[int]:
        loaded = []
        for s in rt.stops:
            if s.kind == "order" and s.order_id not in rt.onboard:
                rt.onboard.add(s.order_id)
                self._set_order(s.order_id, status="in_transit")
                loaded.append(s.order_id)
        return loaded

    # ---------------------------------------------------------------- movement
    def _compute_path(self, a: int, b: int) -> list[int]:
        """Shortest path with a memo that is invalidated whenever traffic changes."""
        key = (a, b, self.sp_algorithm)
        if getattr(self, "_cache_version", None) != self.net.version:
            self._path_cache, self._cache_version = {}, self.net.version
        if key not in self._path_cache:
            res = shortest_path(self.net, a, b, self.sp_algorithm)
            if not res.found and self.sp_algorithm != "dijkstra":
                res = shortest_path(self.net, a, b, "dijkstra")
            self._path_cache[key] = res.nodes
        return self._path_cache[key]

    def _schedule(self, path: list[int], t0: float) -> list[float]:
        times, t = [t0], t0
        for a, b in zip(path, path[1:]):
            e = self.net.edges[(a, b)]
            t += e.free_flow_min * e.traffic        # a vehicle already on a closed edge may finish it
            times.append(t)
        return times

    def _start_leg(self, rt: VehicleRuntime, t0: float) -> None:
        if rt.stops:
            rt.target = rt.stops[0]
        elif rt.node != rt.depot_node:
            rt.target = Stop("return", rt.depot_node)
        else:
            rt.target, rt.status, rt.speed_kmh = None, ("done" if rt.completed else "idle"), 0.0
            rt.path, rt.times = [], []
            return
        planned = rt.planned_legs.pop(0) if rt.planned_legs and rt.target.kind != "return" else None
        path = planned if planned and planned[0] == rt.node and planned[-1] == rt.target.node \
            and self._path_open(planned) else self._compute_path(rt.node, rt.target.node)
        if not path:
            rt.status, rt.path, rt.times = "blocked", [], []
            self._feed("alert", f"{self.vehicles[rt.vehicle_id]['code']} has no open road to its next stop")
            return
        if rt.node == rt.depot_node and rt.target.kind == "order":
            o = self.orders.get(rt.target.order_id)
            travel = self.net.path_stats(path)[1]
            if o and t0 + travel < o["ready_min"]:
                t0 = o["ready_min"] - travel       # hold at the depot instead of waiting at the customer
        rt.path, rt.times, rt.idx = path, self._schedule(path, t0), 0
        rt.status = "moving"

    def _path_open(self, path: list[int]) -> bool:
        return all(self.net.edges.get((a, b)) and not self.net.edges[(a, b)].closed for a, b in zip(path, path[1:]))

    def _reroute(self, rt: VehicleRuntime) -> None:
        """Keep the edge currently being driven, re-plan from the next intersection."""
        if rt.status != "moving" or not rt.target or len(rt.path) < 2:
            return
        nxt = min(rt.idx + 1, len(rt.path) - 1)
        head, head_t = rt.path[: nxt + 1], rt.times[: nxt + 1]
        tail = self._compute_path(rt.path[nxt], rt.target.node)
        if not tail:
            return
        rt.path = head + tail[1:]
        rt.times = head_t + self._schedule(tail, head_t[-1])[1:]
        rt.planned_legs = []                    # future legs recomputed when started

    def _advance(self, rt: VehicleRuntime, now: float) -> None:
        guard = 0
        while guard < 500:
            guard += 1
            if rt.busy_until is not None:
                if now < rt.busy_until:
                    return
                t_free = rt.busy_until
                self._finish_busy(rt)
                self._start_leg(rt, t_free)
                continue
            if rt.status != "moving":
                return
            while rt.idx < len(rt.path) - 1 and rt.times[rt.idx + 1] <= now:
                e = self.net.edges[(rt.path[rt.idx], rt.path[rt.idx + 1])]
                rt.distance_m += e.length_m
                rt.work_min += max(0.0, rt.times[rt.idx + 1] - rt.times[rt.idx])
                self._burn_fuel(rt.vehicle_id, e.length_m)
                rt.idx += 1
                rt.node = rt.path[rt.idx]
                rt.trail.extend([list(p) for p in (e.geometry or [])])
                rt.trail.append(list(self.net.nodes[rt.node]))
            if rt.idx >= len(rt.path) - 1:
                rt.lat, rt.lon = self.net.nodes[rt.node]
                self._arrive(rt, rt.times[-1] if rt.times else now)
                continue
            a, b = rt.path[rt.idx], rt.path[rt.idx + 1]
            t0, t1 = rt.times[rt.idx], rt.times[rt.idx + 1]
            f = 0.0 if t1 <= t0 else (now - t0) / (t1 - t0)
            e = self.net.edges[(a, b)]
            rt.lat, rt.lon, rt.heading = self.net.point_along(e, f)
            rt.speed_kmh = e.speed_kmh / e.traffic
            return

    def _burn_fuel(self, vid: int, metres: float) -> None:
        v = self.vehicles[vid]
        v["fuel_level_l"] = max(0.0, v["fuel_level_l"] - metres / 1000 * v["fuel_l_per_100km"] / 100)

    def _arrive(self, rt: VehicleRuntime, t: float) -> None:
        target = rt.target
        rt.speed_kmh = 0.0
        rt.path, rt.times, rt.idx = [], [], 0
        if target is None:
            rt.status = "idle"
            return
        if target.kind == "return":
            rt.status, rt.target = "done", None
            rt.completed.append({"type": "return", "time": t})
            self._feed("vehicle", f"{self.vehicles[rt.vehicle_id]['code']} returned to depot")
            return
        rt.stops.pop(0)
        if target.kind == "depot":
            rt.status = "reloading"
            rt.busy_until = t + float(self.sc.get("simulation.depot_reload_min"))
            rt.service_arrival = t
            return
        o = self.orders[target.order_id]
        start = max(t, o["ready_min"])
        rt.status = "servicing"
        rt.servicing_order = target.order_id
        rt.service_arrival = t
        rt.busy_until = start + o["service_min"]

    def _finish_busy(self, rt: VehicleRuntime) -> None:
        if rt.status == "reloading":
            loaded = self._load_at_depot(rt)
            rt.completed.append({"type": "depot", "time": rt.service_arrival, "loaded": loaded})
            self._feed("vehicle", f"{self.vehicles[rt.vehicle_id]['code']} reloaded {len(loaded)} parcel(s)")
            self._persist(models.Vehicle, rt.vehicle_id, fuel_level_l=self.vehicles[rt.vehicle_id]["fuel_level_l"])
        elif rt.servicing_order is not None:
            oid = rt.servicing_order
            rt.work_min += self.orders[oid]["service_min"]
            o = self.orders[oid]
            arrival = rt.service_arrival
            note = "early" if arrival < o["ready_min"] - 1e-6 else ("late" if arrival > o["deadline_min"] else "on_time")
            self._set_order(oid, status="delivered", delivered_min=round(arrival, 1), delivery_note=note)
            rt.onboard.discard(oid)
            rt.completed.append({"type": "order", "order_id": oid, "time": arrival, "note": note})
            self._feed("delivery", f"{self.vehicles[rt.vehicle_id]['code']} delivered {o['code']} ({note.replace('_', ' ')})",
                       order_id=oid, vehicle_id=rt.vehicle_id)
        rt.busy_until, rt.servicing_order, rt.service_arrival = None, None, None

    def tick(self) -> bool:
        with self._op():
            if not (self.ready and self.running):
                return False
            self.clock += self.minutes_per_tick
            for rt in self.runtime.values():
                if self.vehicles[rt.vehicle_id]["active"]:
                    self._advance(rt, self.clock)
            self._expire_traffic()
            if self.random_events:
                self._random_events()
            if self.dispatched and all(rt.status in ("idle", "done") for rt in self.runtime.values()) \
                    and not any(o["status"] in ("pending", "assigned", "in_transit") for o in self.orders.values()):
                self.running = False
                self._feed("system", "All deliveries completed – simulation stopped")
            self._bump()
            return True

    def _random_events(self) -> None:
        cfg = self.sc.section("simulation")["random_events"]
        roll = self.rng.random()
        if roll < cfg["new_order_probability"]:
            self.event_new_order({})
        elif roll < cfg["new_order_probability"] + cfg["congestion_probability"]:
            self.event_congestion({})
        elif roll < cfg["new_order_probability"] + cfg["congestion_probability"] + cfg["closure_probability"]:
            self.event_closure({})

    # ================================================================ optimisation
    def _ga_params(self, overrides: dict | None) -> GAParams:
        return GAParams.from_config(self.sc.section("algorithms")["genetic"], self.seed, overrides)

    def _groups(self, order_ids: list[int]) -> dict[int, list[int]]:
        """Cluster-first: each order goes to the nearest depot that has active vehicles."""
        staffed = {v["depot_id"] for v in self.active_vehicles()} or set(self.depots)
        groups: dict[int, list[int]] = {d: [] for d in staffed}
        for oid in order_ids:
            groups[self.nearest_depot(self.orders[oid]["node_id"], staffed)].append(oid)
        return groups

    def _default_settings(self) -> dict:
        return {"algorithm": self.sc.get("algorithms.default_construction"),
                "shortest_path": self.sc.get("algorithms.default_shortest_path"),
                "operators": list(self.sc.get("algorithms.default_improvement")),
                "weights": {}, "ga": {}}

    def _settings_from(self, req: dict) -> dict:
        algorithm = req.get("algorithm") or self.sc.get("algorithms.default_construction")
        if algorithm not in optimizer.ROUTING_ALGORITHMS:
            raise ValueError(f"algorithm must be one of {list(optimizer.ROUTING_ALGORITHMS)}")
        if algorithm == "ortools" and not optimizer.ortools_solver.AVAILABLE:
            raise ValueError("OR-Tools is not installed on the server")
        d = self._default_settings()
        return {"algorithm": algorithm, "shortest_path": req.get("shortest_path") or d["shortest_path"],
                "operators": req["operators"] if req.get("operators") is not None else d["operators"],
                "weights": req.get("weights") or {}, "ga": req.get("ga") or {}}

    def _prepare(self, ids: list[int], settings: dict) -> list[dict]:
        """Build one CVRPTW instance per staffed depot (needs the lock: reads live state)."""
        merged = dict(settings.get("weights") or {})
        weights = Weights.from_scenario(self.sc.section("objective"), merged)
        groups = []
        for depot_id, oids in self._groups(ids).items():
            vehicles = [v for v in self.active_vehicles() if v["depot_id"] == depot_id]
            if not vehicles or not oids:
                continue
            starts = [optimizer.VehicleStart(dict(v), self.depot_node(depot_id), self.clock, True) for v in vehicles]
            bi = optimizer.build_instance(self.net, self.depot_node(depot_id), starts,
                                          [dict(self.orders[i]) for i in oids], weights, self.priority_mult(),
                                          float(self.sc.get("simulation.depot_reload_min")))
            groups.append({"depot_id": depot_id, "bi": bi, "weights": weights})
        return groups

    def _solve_prepared(self, groups: list[dict], settings: dict, arrival: list[int]) -> list[dict]:
        """Pure computation on prepared instances – runs WITHOUT the engine lock."""
        rounds = int(self.sc.get("algorithms.local_search_max_iterations"))
        out = []
        for g in groups:
            (sol, stages), wall, cpu, peak = optimizer.measured(
                optimizer.solve, g["bi"], settings["algorithm"], settings["operators"], rounds,
                self._ga_params(settings["ga"]), int(self.sc.get("algorithms.ortools_time_limit_s")), arrival,
                float(self.sc.get("algorithms.local_search_time_limit_s")), int(self.sc.get("algorithms.granular_neighbours")))
            base, _ = optimizer.solve(g["bi"], "fifo", [], 0, None, 0, arrival)
            out.append({**g, "sol": sol, "stages": stages, "wall": wall, "cpu": cpu, "peak": peak,
                        "metrics": optimizer.solution_metrics(g["bi"], sol),
                        "baseline": optimizer.solution_metrics(g["bi"], base)})
        return out

    def _assemble(self, solved: list[dict], settings: dict) -> dict:
        plans = [optimizer.build_plan(self.net, g["bi"], g["sol"], self.orders, settings["shortest_path"]) for g in solved]
        plan = {"routes": [r for p in plans for r in p["routes"]],
                "unassigned": [u for p in plans for u in p["unassigned"]],
                "shortest_path": _merge_numeric([p["shortest_path"] for p in plans], keep={"algorithm"}),
                "matrix": _merge_numeric([p["matrix"] for p in plans])}
        metrics = _merge_metrics([g["metrics"] for g in solved])
        baseline = _merge_metrics([g["baseline"] for g in solved])
        weights = solved[0]["weights"] if solved else self.weights()
        return {
            "plan": plan, "metrics": metrics, "baseline": baseline,
            "runtime_ms": round(sum(g["wall"] for g in solved), 2),
            "explanation": {
                "algorithm": settings["algorithm"], "algorithm_label": optimizer.ROUTING_ALGORITHMS[settings["algorithm"]],
                "stages": [{"depot": self.depots[g["depot_id"]]["name"], **s} for g in solved for s in g["stages"]],
                "convergence": [round(h, 2) for g in solved for h in g["sol"].history],
                "weights": weights.__dict__, "operators": settings["operators"],
                "shortest_path": plan["shortest_path"], "matrix": plan["matrix"],
                "improvement_vs_baseline": _improvement(baseline, metrics),
                "cpu_ms": round(sum(g["cpu"] for g in solved), 1),
                "peak_memory_kb": round(max((g["peak"] for g in solved), default=0), 1),
            },
        }

    def optimize(self, req: dict) -> dict:
        """Static optimisation of all open orders before dispatch, or a full dynamic
        re-plan once the fleet is on the road.

        The (possibly long) solve runs WITHOUT the engine lock, so the simulation,
        WebSocket and other requests keep working. If orders or the fleet change
        meanwhile, the stale result is discarded (Conflict -> HTTP 409)."""
        with self._op():
            settings = self._settings_from(req)
            if self._optimizing:
                raise Conflict("An optimisation is already running – wait for it to finish")
            if self.dispatched:
                self.active_settings = settings
                return self.reoptimize("manual", strategy="full")
            ids = [o["id"] for o in self.orders.values() if o["status"] in ("pending", "assigned")]
            if not ids:
                raise ValueError("There are no open orders to optimise – create or generate orders first")
            if not self.active_vehicles():
                raise ValueError("No active vehicles – activate or register a vehicle first")
            arrival = sorted(ids, key=lambda i: (self.orders[i]["created_min"], i))
            groups = self._prepare(ids, settings)
            version = self.state_version
            self._optimizing = True
        try:
            solved = self._solve_prepared(groups, settings, arrival)
        finally:
            self._optimizing = False
        with self._op():
            if self.state_version != version or self.dispatched:
                raise Conflict("Orders or fleet changed while optimising – the result was discarded, please run again")
            result = self._assemble(solved, settings)
            self.active_settings = settings
            self.plan = result["plan"]
            for o in self.orders.values():
                if o["status"] in ("pending", "assigned"):
                    self._set_order(o["id"], vehicle_id=None, status="pending")
            for rt in self.runtime.values():
                rt.stops, rt.planned_legs = [], []
            self._apply_routes_from_plan()
            run = self._save_run("static", settings["algorithm"], result)
            self.plan_meta = {"run_id": run, **{k: result[k] for k in ("metrics", "baseline", "explanation")}}
            self.static_plan = copy.deepcopy((self.plan, self.plan_meta))
            self._feed("optimize", f"Optimised {len(ids)} orders with {optimizer.ROUTING_ALGORITHMS[settings['algorithm']]}")
            self._bump()
            return {"run_id": run, **result}

    def _save_run(self, kind: str, algorithm: str, result: dict, comparison: list | None = None) -> int:
        with SessionLocal.begin() as db:
            run = models.OptimizationRun(
                kind=kind, algorithm=algorithm, params=self.active_settings, metrics=result["metrics"],
                baseline=result.get("baseline", {}), comparison=comparison or [],
                explanation=result["explanation"], plan=result.get("plan", {}),
                runtime_ms=result.get("runtime_ms", 0.0), sim_min=self.clock)
            db.add(run)
            db.flush()
            return run.id

    def compare_algorithms(self, algorithms: list[str] | None = None) -> list[dict]:
        """Run several algorithms on the same open orders (outside the lock)."""
        with self._op():
            if self._optimizing:
                raise Conflict("An optimisation is already running – wait for it to finish")
            algos = [a for a in (algorithms or list(optimizer.ROUTING_ALGORITHMS))
                     if a != "ortools" or optimizer.ortools_solver.AVAILABLE]
            statuses = ("pending", "assigned") if not self.dispatched else ("pending", "assigned", "in_transit")
            ids = [o["id"] for o in self.orders.values() if o["status"] in statuses]
            if not ids:
                raise ValueError("There are no open orders to compare algorithms on")
            arrival = sorted(ids, key=lambda i: (self.orders[i]["created_min"], i))
            base_settings = {**self._default_settings(), **(self.active_settings or {})}
            groups = self._prepare(ids, base_settings)
            self._optimizing = True
        rows = []
        try:
            for algo in algos:
                settings = {**base_settings, "algorithm": algo}
                solved = self._solve_prepared(groups, settings, arrival)
                metrics = _merge_metrics([g["metrics"] for g in solved])
                rows.append({"algorithm": algo, "label": optimizer.ROUTING_ALGORITHMS[algo],
                             "runtime_ms": round(sum(g["wall"] for g in solved), 2), **metrics,
                             "convergence": [round(h, 2) for g in solved for h in g["sol"].history]})
        finally:
            self._optimizing = False
        with SessionLocal.begin() as db:
            db.add(models.BenchmarkRun(kind="algorithm_comparison", params={"orders": len(ids)}, results=rows))
        return rows

    def _vehicle_start(self, rt: VehicleRuntime, v: dict) -> optimizer.VehicleStart:
        if not self.dispatched:
            return optimizer.VehicleStart(v, rt.depot_node, self.clock, True)
        start = self._vehicle_start_raw(rt, v)
        start.used_today = bool(rt.completed) or rt.status != "idle" or bool(rt.trail[1:])
        start.prior_work_min = rt.work_min
        return start

    def _is_scheduled(self, rt: VehicleRuntime) -> bool:
        """Holding at the depot until its planned departure (has not left yet)."""
        return rt.status == "moving" and bool(rt.times) and self.clock < rt.times[0] and rt.node == rt.depot_node

    def _vehicle_start_raw(self, rt: VehicleRuntime, v: dict) -> optimizer.VehicleStart:
        if self._is_scheduled(rt):              # still parked: can load more and leave whenever is best
            return optimizer.VehicleStart(v, rt.depot_node, self.clock, True, set(rt.onboard))
        if rt.status == "moving" and len(rt.path) > 1:
            nxt = min(rt.idx + 1, len(rt.path) - 1)
            return optimizer.VehicleStart(v, rt.path[nxt], max(rt.times[nxt], self.clock), False, set(rt.onboard))
        if rt.status in ("servicing", "reloading"):
            at_depot = rt.status == "reloading"
            return optimizer.VehicleStart(v, rt.node, rt.busy_until, at_depot, set(rt.onboard))
        at_depot = rt.node == rt.depot_node
        return optimizer.VehicleStart(v, rt.node, self.clock, at_depot, set(rt.onboard))

    def reoptimize(self, trigger: str, strategy: str | None = None, focus_order: int | None = None) -> dict:
        """Dynamic re-optimisation from the current fleet state."""
        with self._op():
            strategy = strategy or self.sc.get("simulation.reoptimize_strategy")
            if not self.active_settings:
                self.active_settings = self._default_settings()
            weights = self.weights()
            servicing = {rt.servicing_order for rt in self.runtime.values() if rt.servicing_order}
            open_ids = [o["id"] for o in self.orders.values()
                        if o["status"] in ("pending", "assigned", "in_transit") and o["id"] not in servicing]
            all_routes, decisions, static_m, dyn_m, plans = [], [], [], [], []
            for depot_id, oids in self._groups(open_ids).items():
                vehicles = [v for v in self.active_vehicles() if v["depot_id"] == depot_id]
                if not vehicles:
                    continue
                rts = [self.runtime[v["id"]] for v in vehicles]
                starts = [self._vehicle_start(rt, v) for rt, v in zip(rts, vehicles)]
                # orders on an inactive vehicle return to the pool
                bi = optimizer.build_instance(self.net, self.depot_node(depot_id), starts,
                                              [self.orders[i] for i in oids], weights, self.priority_mult(),
                                              float(self.sc.get("simulation.depot_reload_min")))
                inst = bi.inst
                routes, placed = [], set()
                for k, rt in enumerate(rts):
                    seq = []
                    for s in rt.stops:
                        if s.kind == "depot":
                            seq.append(DEPOT)
                        elif s.order_id in bi.order_point:
                            seq.append(bi.order_point[s.order_id])
                            placed.add(s.order_id)
                    routes.append(normalize_route(inst, k, seq))
                pending = [bi.order_point[i] for i in oids if i not in placed]
                current = Solution([list(r) for r in routes], list(pending))
                # ---- static policy (no re-optimisation): append to vehicle with most spare capacity
                static = Solution([list(r) for r in routes], [])
                for p in pending:
                    k = max(range(len(rts)), key=lambda k: inst.vehicles[k].capacity - sum(
                        inst.demand[c] for c in static.routes[k] if c != DEPOT))
                    tail = [p] if inst.vehicles[k].at_depot else [DEPOT, p]
                    static.routes[k] = normalize_route(inst, k, static.routes[k] + tail)
                static_m.append(optimizer.solution_metrics(bi, static))
                # ---- dynamic policy
                sol = current.copy()
                if strategy == "full":
                    lock = inst.owner_lock()
                    for k, r in enumerate(sol.routes):
                        free = [c for c in r if c != DEPOT and c not in lock]
                        sol.unassigned.extend(free)
                        sol.routes[k] = normalize_route(inst, k, [c for c in r if c == DEPOT or c in lock])
                explain: list = []
                sol = construction.regret_insertion(inst, sol, explain)
                gains = {}
                if strategy in ("insertion_plus_local_search", "full"):
                    ops = [op for op in self.active_settings["operators"] if op in optimizer.LOCAL_SEARCH_OPERATORS]
                    sol, gains = local_search.improve(inst, sol, ops,
                                                      int(self.sc.get("algorithms.local_search_max_iterations")),
                                                      float(self.sc.get("algorithms.local_search_time_limit_s")),
                                                      int(self.sc.get("algorithms.granular_neighbours")))
                sol.routes = [normalize_route(inst, k, r) for k, r in enumerate(sol.routes)]
                dyn_m.append(optimizer.solution_metrics(bi, sol))
                plan = optimizer.build_plan(self.net, bi, sol, self.orders, self.sp_algorithm)
                plans.append(plan)
                all_routes.append((bi, sol, rts))
                for d in explain:
                    oid = bi.point_order[d["customer"]]
                    decisions.append({
                        "order_id": oid, "order_code": self.orders[oid]["code"],
                        "chosen_vehicle": self.vehicles[rts[d["chosen_vehicle"]].vehicle_id]["code"],
                        "delta_cost": round(d["delta_cost"], 2),
                        "candidates": [{"vehicle": self.vehicles[rts[c["vehicle"]].vehicle_id]["code"],
                                        "delta_cost": None if c["delta_cost"] == INF else round(c["delta_cost"], 2)}
                                       for c in d["candidates"]],
                    })
                if gains:
                    decisions.append({"local_search_gains": {k: round(v, 2) for k, v in gains.items()}})
            # ---- apply
            for bi, sol, rts in all_routes:
                for k, rt in enumerate(rts):
                    new_stops = [Stop("depot", bi.point_nodes[DEPOT]) if p == DEPOT else
                                 Stop("order", bi.point_nodes[p], bi.point_order[p]) for p in sol.routes[k]]
                    changed = [s.order_id for s in new_stops] != [s.order_id for s in rt.stops] or \
                        [s.kind for s in new_stops] != [s.kind for s in rt.stops]
                    rt.stops = new_stops
                    for s in new_stops:
                        if s.order_id and self.orders[s.order_id]["status"] == "pending" or \
                                (s.order_id and self.orders[s.order_id]["vehicle_id"] != rt.vehicle_id):
                            self._set_order(s.order_id, vehicle_id=rt.vehicle_id,
                                            status="in_transit" if s.order_id in rt.onboard else "assigned")
                    rt.planned_legs = []
                    if not self.dispatched:
                        continue
                    if self._is_scheduled(rt):
                        # parked vehicle: load any new parcels and recompute when to leave
                        rt.path, rt.times, rt.idx, rt.status = [], [], 0, "idle"
                        self._load_at_depot(rt)
                        if rt.stops:
                            self._start_leg(rt, self.clock)
                    elif rt.status == "moving":
                        if changed:
                            rt.target = rt.stops[0] if rt.stops else Stop("return", rt.depot_node)
                        self._reroute(rt)
                    elif rt.status in ("idle", "done", "blocked") and rt.stops:
                        if rt.node == rt.depot_node:
                            self._load_at_depot(rt)
                        self._start_leg(rt, self.clock)
            for bi, sol, rts in all_routes:
                for u in sol.unassigned:
                    self._set_order(bi.point_order[u], vehicle_id=None, status="pending")
            self.plan = {"routes": [r for p in plans for r in p["routes"]],
                         "unassigned": [u for p in plans for u in p["unassigned"]],
                         "shortest_path": _merge_numeric([p["shortest_path"] for p in plans], keep={"algorithm"}),
                         "matrix": _merge_numeric([p["matrix"] for p in plans])}
            static_merged, dyn_merged = _merge_metrics(static_m), _merge_metrics(dyn_m)
            response = {
                "trigger": trigger, "strategy": strategy,
                "static_policy": static_merged, "reoptimized": dyn_merged,
                "saving": _improvement(static_merged, dyn_merged),
                "decisions": [d for d in decisions if d],
                "focus_order": focus_order,
            }
            result = {"metrics": dyn_merged, "baseline": static_merged, "plan": self.plan,
                      "explanation": response, "runtime_ms": 0.0}
            run = self._save_run("dynamic", f"{strategy}", result)
            self.plan_meta = {"run_id": run, "metrics": dyn_merged, "baseline": static_merged, "explanation": response}
            self._bump(inputs_changed=True)
            return {"run_id": run, **response}

    # ================================================================ events
    def _record_event(self, kind: str, payload: dict, response: dict) -> None:
        with SessionLocal() as db:
            db.add(models.SimEvent(sim_min=self.clock, type=kind, payload=payload, response=response))
            db.commit()

    def _route_nodes_ahead(self) -> list[int]:
        nodes = []
        for rt in self.runtime.values():
            if rt.status == "moving":
                nodes.extend(rt.path[rt.idx + 1:])
        if not nodes and self.plan:
            for r in self.plan["routes"]:
                for leg in r["legs"]:
                    nodes.extend(leg["nodes"][1:-1])
        return nodes

    def event_new_order(self, req: dict) -> dict:
        with self._op():
            node = None
            if req.get("lat") is not None and req.get("lon") is not None:
                node = self.net.nearest_node(float(req["lat"]), float(req["lon"]))
            deadline = None
            if req.get("deadline"):
                deadline = hhmm_to_min(req["deadline"])
            elif req.get("deadline_in_min"):
                deadline = self.clock + float(req["deadline_in_min"])
            with SessionLocal() as db:
                o = seeding.make_order(db, self.net, self.sc, self.rng, self.faker,
                                       [d["node_id"] for d in self.depots.values()], self.clock,
                                       req.get("source") or "simulated", node=node, weight=req.get("weight_kg"),
                                       priority=req.get("priority"), deadline_min=deadline,
                                       customer=req.get("customer_name"))
                db.commit()
                self.orders[o.id] = _row(o, ORDER_FIELDS)
            o = self.orders[o.id]
            self._feed("new_order", f"New {o['priority']} order {o['code']} – {o['weight_kg']} kg, due "
                                    f"{min_to_hhmm(o['deadline_min'])}", order_id=o["id"])
            response = self.reoptimize("new_order", focus_order=o["id"])
            chosen = next((d for d in response["decisions"] if d.get("order_id") == o["id"]), None)
            if chosen:
                self._feed("decision", f"{o['code']} → {chosen['chosen_vehicle']} (Δcost {chosen['delta_cost']})")
            self._record_event("new_order", {"order_id": o["id"], **req}, response)
            return {"order": o, **response}

    def event_congestion(self, req: dict) -> dict:
        with self._op():
            cfg = self.sc.section("simulation")["congestion"]
            if req.get("lat") is not None and req.get("lon") is not None:
                lat, lon = float(req["lat"]), float(req["lon"])
            else:
                ahead = self._route_nodes_ahead() or list(self.net.nodes)
                lat, lon = self.net.nodes[self.rng.choice(ahead)]
            radius = float(req.get("radius_m") or cfg["radius_m"])
            factor = float(req.get("factor") or self.rng.uniform(cfg["factor"]["min"], cfg["factor"]["max"]))
            duration = float(req.get("duration_min") or self.rng.uniform(cfg["duration_min"]["min"], cfg["duration_min"]["max"]))
            nodes = self.net.nodes_within(lat, lon, radius)
            before = {k: e.traffic for k, e in self.net.edges.items() if e.u in nodes and e.v in nodes}
            edges = self.net.set_congestion(nodes, factor)
            item = {"id": len(self.congestions) + len(self.closures) + 1, "center": [lat, lon], "radius_m": radius,
                    "factor": round(factor, 2), "until": self.clock + duration, "until_hhmm": min_to_hhmm(self.clock + duration),
                    "edges": [[e.u, e.v] for e in edges], "previous": {f"{k[0]},{k[1]}": v for k, v in before.items()}}
            self.congestions.append(item)
            area = street_of_node(self.net, self.net.nearest_node(lat, lon))
            self._feed("congestion", f"Congestion ×{factor:.1f} near {area} until {item['until_hhmm']}")
            response = self.reoptimize("congestion")
            self._record_event("congestion", {k: v for k, v in item.items() if k != "previous"}, response)
            return {"congestion": {k: v for k, v in item.items() if k != "previous"}, **response}

    def event_closure(self, req: dict) -> dict:
        with self._op():
            if req.get("u") is not None and req.get("v") is not None:
                u, v = int(req["u"]), int(req["v"])
            else:
                ahead = []
                for rt in self.runtime.values():
                    if rt.status == "moving" and len(rt.path) - rt.idx > 3:
                        ahead.extend(zip(rt.path[rt.idx + 1:-1], rt.path[rt.idx + 2:]))
                if not ahead and self.plan:
                    for r in self.plan["routes"]:
                        for leg in r["legs"]:
                            ahead.extend(zip(leg["nodes"][1:-1], leg["nodes"][2:]))
                candidates = [p for p in ahead if p in self.net.edges] or list(self.net.edges)
                u, v = self.rng.choice(candidates)
            if (u, v) not in self.net.edges:
                raise ValueError("No road between these intersections")
            edges = self.net.set_closed(u, v, True)
            if not self.net.is_strongly_connected_from(u):
                self.net.set_closed(u, v, False)
                raise ValueError("Closing this road would disconnect the network")
            name = edges[0].name
            item = {"id": len(self.congestions) + len(self.closures) + 1, "u": u, "v": v, "street": name,
                    "coords": [list(p) for p in self.net.edge_points(edges[0])]}
            self.closures.append(item)
            self._feed("closure", f"Road closed: {name}")
            response = self.reoptimize("road_closure")
            self._record_event("road_closure", item, response)
            return {"closure": item, **response}

    def clear_traffic(self) -> dict:
        with self._op():
            self.net.reset_traffic()
            self.congestions, self.closures = [], []
            self._feed("system", "Traffic cleared – all roads open")
            for rt in self.runtime.values():
                self._reroute(rt)
            self._bump()
            return {"ok": True}

    def _expire_traffic(self) -> None:
        expired = [c for c in self.congestions if c["until"] <= self.clock]
        if not expired:
            return
        for c in expired:
            for key, val in c["previous"].items():
                a, b = map(int, key.split(","))
                if (a, b) in self.net.edges:
                    self.net.edges[(a, b)].traffic = val
            self.congestions.remove(c)
            self._feed("system", f"Congestion #{c['id']} cleared")
        self.net.version += 1
        for rt in self.runtime.values():
            self._reroute(rt)

    # ================================================================ CRUD helpers
    def add_order(self, req: dict) -> dict:
        req = {**req, "source": "user"}
        if self.dispatched:
            return self.event_new_order(req)
        with self._op():
            node = self.net.nearest_node(float(req["lat"]), float(req["lon"])) if req.get("lat") is not None else None
            deadline = hhmm_to_min(req["deadline"]) if req.get("deadline") else None
            with SessionLocal() as db:
                o = seeding.make_order(db, self.net, self.sc, self.rng, self.faker,
                                       [d["node_id"] for d in self.depots.values()], self.clock, "user", node=node,
                                       weight=req.get("weight_kg"), priority=req.get("priority"),
                                       deadline_min=deadline, customer=req.get("customer_name"))
                db.commit()
                self.orders[o.id] = _row(o, ORDER_FIELDS)
            self._feed("new_order", f"Order {o.code} created")
            self._bump(inputs_changed=True)
            return {"order": self.orders[o.id]}

    def generate_orders(self, count: int) -> list[dict]:
        out = []
        for _ in range(count):
            out.append(self.add_order({})["order"] if not self.dispatched else self.event_new_order({})["order"])
        return out

    def cancel_order(self, oid: int) -> dict:
        """Cancel = keep the record (status 'cancelled') but remove it from all routes."""
        with self._op():
            o = self.orders.get(oid)
            if not o:
                raise KeyError(oid)
            if o["status"] in ("delivered", "in_transit", "cancelled"):
                raise ValueError(f"{o['code']} is {o['status'].replace('_', ' ')} and cannot be cancelled")
            self._detach_orders({oid})
            self._set_order(oid, status="cancelled", vehicle_id=None)
            self._feed("system", f"Order {o['code']} cancelled")
            self._refresh_plan("order_cancelled")
            self._bump(inputs_changed=True)
            return o

    # ------------------------------------------------------------ deletion
    def _detach_orders(self, ids: set[int]) -> None:
        """Remove orders from every vehicle route / load and from the plan."""
        for rt in self.runtime.values():
            before = len(rt.stops)
            rt.stops = [st for st in rt.stops if st.order_id not in ids]
            rt.onboard -= ids
            if len(rt.stops) != before:
                rt.planned_legs = []
                if rt.status == "moving" and rt.target and rt.target.order_id in ids:
                    rt.target = rt.stops[0] if rt.stops else Stop("return", rt.depot_node)
                    self._reroute(rt)
        if self.plan:
            for r in self.plan["routes"]:
                r["stops"] = [st for st in r["stops"] if st.get("order_id") not in ids]
            self.plan["unassigned"] = [u for u in self.plan["unassigned"] if u not in ids]

    def _refresh_plan(self, trigger: str) -> None:
        """Recompute route legs / ETAs after orders left the plan (no re-assignment needed)."""
        if self.plan is None:
            return
        if any(o["status"] in ("pending", "assigned", "in_transit") for o in self.orders.values()):
            self.reoptimize(trigger, strategy="insertion")
        else:
            self.plan, self.plan_meta = None, None

    def deletion_preview(self, ids: list[int] | None, flt: dict | None, include_delivered: bool) -> dict:
        with self._op():
            targets = self._match(ids, flt)
            servicing = {rt.servicing_order for rt in self.runtime.values() if rt.servicing_order}
            by_status: dict[str, int] = {}
            for oid in targets:
                st = self.orders[oid]["status"]
                by_status[st] = by_status.get(st, 0) + 1
            blocked = {oid for oid in targets if oid in servicing}
            delivered = {oid for oid in targets if self.orders[oid]["status"] == "delivered"}
            deletable = targets - blocked - (set() if include_delivered else delivered)
            return {"matched": len(targets), "deletable": len(deletable), "by_status": by_status,
                    "skipped_delivered": 0 if include_delivered else len(delivered - blocked),
                    "skipped_in_service": len(blocked), "include_delivered": include_delivered,
                    "affects_routes": sum(1 for oid in deletable if self.orders[oid]["vehicle_id"])}

    def _match(self, ids: list[int] | None, flt: dict | None) -> set[int]:
        if ids is not None:
            return {i for i in ids if i in self.orders}
        flt = flt or {}
        q = (flt.get("q") or "").strip().lower()
        statuses = set(flt.get("statuses") or ([flt["status"]] if flt.get("status") else []))
        out = set()
        for o in self.orders.values():
            if statuses and o["status"] not in statuses:
                continue
            if flt.get("priority") and o["priority"] != flt["priority"]:
                continue
            if q and q not in f"{o['code']} {o['customer_name']} {o['address']}".lower():
                continue
            out.add(o["id"])
        return out

    def delete_orders(self, ids: list[int] | None = None, flt: dict | None = None,
                      include_delivered: bool = False) -> dict:
        """Permanently delete orders (one DB transaction). Delivered orders are kept unless
        include_delivered is set; an order being handed over right now is never deleted."""
        with self._op():
            preview = self.deletion_preview(ids, flt, include_delivered)
            targets = self._match(ids, flt)
            servicing = {rt.servicing_order for rt in self.runtime.values() if rt.servicing_order}
            doomed = {oid for oid in targets if oid not in servicing
                      and (include_delivered or self.orders[oid]["status"] != "delivered")}
            if not doomed:
                return {**preview, "deleted": 0}
            self._flush()
            ordered = sorted(doomed)
            with SessionLocal.begin() as db:          # all-or-nothing; memory untouched on failure
                for i in range(0, len(ordered), 500):
                    db.execute(sql_delete(models.Order).where(models.Order.id.in_(ordered[i:i + 500])))
            self._detach_orders(doomed)
            for oid in doomed:
                self.orders.pop(oid, None)
                self._dirty.pop(oid, None)
            self._feed("system", f"Deleted {len(doomed)} order(s)")
            self._refresh_plan("orders_deleted")
            self._bump(inputs_changed=True)
            return {**preview, "deleted": len(doomed)}


    def add_vehicle(self, req: dict) -> dict:
        with self._op():
            types = {t["model"]: t for t in self.sc.get("fleet.types")}
            if req.get("model") and req["model"] not in types:
                raise ValueError(f"vehicle type must be one of {list(types)}")
            vt = dict(types[req["model"]]) if req.get("model") else None
            if req.get("capacity_kg") and vt is None:     # random type, but the capacity the user typed
                ft = list(types.values())
                vt = dict(self.rng.choices(ft, weights=[t["weight"] for t in ft])[0])
            if vt and req.get("capacity_kg"):
                vt["capacity_kg"] = float(req["capacity_kg"])
            depot_id = int(req.get("depot_id") or next(iter(self.depots)))
            if depot_id not in self.depots:
                raise KeyError(f"depot {depot_id}")
            with SessionLocal() as db:
                v = seeding.make_vehicle(db, self.sc, self.rng, self.faker, depot_id, vt, req.get("driver_name"))
                db.commit()
                self.vehicles[v.id] = _row(v, VEHICLE_FIELDS)
            self._init_runtime(self.vehicles[v.id])
            self._feed("system", f"Vehicle {v.code} registered")
            self._bump(inputs_changed=True)
            return self.vehicles[v.id]

    def update_vehicle(self, vid: int, req: dict) -> dict:
        with self._op():
            if vid not in self.vehicles:
                raise KeyError(vid)
            v = self.vehicles[vid]
            rt = self.runtime[vid]
            if req.get("depot_id") is not None and int(req["depot_id"]) != v["depot_id"]:
                self._move_vehicle(v, rt, int(req["depot_id"]))
            if req.get("active") is False and (rt.onboard or rt.status in ("moving", "servicing", "reloading")):
                raise Conflict(f"{v['code']} is on the road with parcels – deactivate it after it returns")
            changes = {k: req[k] for k in ("capacity_kg", "driver_name", "active") if req.get(k) is not None}
            if req.get("active") is False and rt.stops:
                for st in rt.stops:
                    if st.order_id:
                        self._set_order(st.order_id, vehicle_id=None, status="pending")
                rt.stops, rt.planned_legs = [], []
                self._feed("system", f"{v['code']} deactivated – its orders are back in the pool; re-optimise to reassign")
            v.update(changes)
            if changes:
                self._persist(models.Vehicle, vid, **changes)
            self._bump(inputs_changed=True)
            return v

    def _move_vehicle(self, v: dict, rt: VehicleRuntime, depot_id: int) -> None:
        """Re-home a vehicle to another hub. Only while it is parked (not carrying parcels)."""
        if depot_id not in self.depots:
            raise KeyError(depot_id)
        if rt.onboard or rt.status in ("moving", "servicing", "reloading", "blocked"):
            raise Conflict(f"{v['code']} is on the road – move it to another hub after it returns")
        for st in rt.stops:                     # planned but not loaded -> back to the pool
            if st.order_id:
                self._set_order(st.order_id, vehicle_id=None, status="pending")
        if rt.stops and self.plan:
            self.plan["routes"] = [r for r in self.plan["routes"] if r["vehicle_id"] != v["id"]]
        node = self.depot_node(depot_id)
        lat, lon = self.net.nodes[node]
        rt.stops, rt.planned_legs, rt.depot_node, rt.node, rt.lat, rt.lon = [], [], node, node, lat, lon
        rt.trail.append([lat, lon])
        v["depot_id"] = depot_id
        self._persist(models.Vehicle, v["id"], depot_id=depot_id)
        self._feed("system", f"{v['code']} moved to {self.depots[depot_id]['name']} – re-optimise to use it")

    def depots_view(self) -> list[dict]:
        with self._op():
            staffed = {d: 0 for d in self.depots}
            for v in self.active_vehicles():
                staffed[v["depot_id"]] = staffed.get(v["depot_id"], 0) + 1
            groups = self._groups([o["id"] for o in self.orders.values()
                                   if o["status"] in ("pending", "assigned", "in_transit")]) if self.depots else {}
            return [{**d, "vehicles": staffed.get(d["id"], 0), "open_orders": len(groups.get(d["id"], [])),
                     "in_use": staffed.get(d["id"], 0) > 0} for d in self.depots.values()]

    def add_depot(self, req: dict) -> dict:
        with self._op():
            with SessionLocal() as db:
                d = seeding.make_depot(db, self.net, self.faker, float(req["lat"]), float(req["lon"]), req.get("name"))
                db.commit()
                self.depots[d.id] = _row(d, DEPOT_FIELDS)
            moved = []
            if req.get("move_vehicles"):
                parked = [v for v in self.active_vehicles() if not self.runtime[v["id"]].onboard
                          and self.runtime[v["id"]].status in ("idle", "done")]
                parked.sort(key=lambda v: len(self.runtime[v["id"]].stops))
                for v in parked[: int(req["move_vehicles"])]:
                    self._move_vehicle(v, self.runtime[v["id"]], d.id)
                    moved.append(v["code"])
            self._feed("system", f"Hub {d.name} added" + (f" with {', '.join(moved)}" if moved else " – assign vehicles to use it"))
            self._bump(inputs_changed=True)
            return {**self.depots[d.id], "moved_vehicles": moved}

    def alternatives(self, vehicle_id: int) -> dict:
        with self._op():
            rt = self.runtime[vehicle_id]
            if rt.status == "moving" and rt.target:
                src = rt.path[min(rt.idx + 1, len(rt.path) - 1)]
                dst = rt.target.node
            elif rt.stops:
                src, dst = rt.node, rt.stops[0].node
            else:
                return {"paths": []}
            k = int(self.sc.get("algorithms.k_alternative_paths"))
            paths = yen_k_shortest(self.net, src, dst, k, "time")
            comparison = {a: shortest_path(self.net, src, dst, a).to_dict() for a in
                          ("dijkstra", "astar", "bidirectional_dijkstra")}
            for c in comparison.values():
                c.pop("nodes", None)
            return {"source": src, "target": dst,
                    "paths": [{**p.to_dict(self.net), "rank": i + 1, "chosen": i == 0} for i, p in enumerate(paths)],
                    "algorithms": comparison}

    def vehicle_view(self, rt: VehicleRuntime, detail: bool = False) -> dict:
        """Compact view for the live broadcast; detail=True adds the full stop list."""
        view = self._vehicle_view(rt)
        if not detail:
            view.pop("stops", None)
        return view

    def _vehicle_view(self, rt: VehicleRuntime) -> dict:
        v = self.vehicles[rt.vehicle_id]
        load = sum(self.orders[o]["weight_kg"] for o in rt.onboard if o in self.orders)
        assigned = [s for s in rt.stops if s.kind == "order"]
        done_orders = [c for c in rt.completed if c["type"] == "order"]
        stops = []
        for c in rt.completed:
            if c["type"] == "order" and c["order_id"] in self.orders:
                o = self.orders[c["order_id"]]
                stops.append({"order_id": o["id"], "code": o["code"], "customer": o["customer_name"],
                              "lat": o["lat"], "lon": o["lon"], "address": o["address"], "status": "done", "time": min_to_hhmm(c["time"]),
                              "note": c["note"], "weight_kg": o["weight_kg"], "priority": o["priority"]})
        if rt.servicing_order:
            o = self.orders[rt.servicing_order]
            stops.append({"order_id": o["id"], "code": o["code"], "customer": o["customer_name"], "address": o["address"],
                          "lat": o["lat"], "lon": o["lon"], "status": "servicing", "time": min_to_hhmm(rt.service_arrival), "weight_kg": o["weight_kg"],
                          "priority": o["priority"]})
        # ETAs for remaining stops
        t = rt.times[-1] if rt.status == "moving" and rt.times else (rt.busy_until or self.clock)
        prev = rt.target.node if rt.status == "moving" and rt.target else rt.node
        for i, s in enumerate(rt.stops):
            if i > 0 or rt.status != "moving":
                if prev != s.node:
                    p = self._compute_path(prev, s.node)
                    t += self.net.path_stats(p)[1] if p else 0
            if s.kind == "depot":
                stops.append({"order_id": None, "code": "DEPOT", "customer": "Reload at depot", "address": "",
                              "lat": self.net.nodes[s.node][0], "lon": self.net.nodes[s.node][1],
                              "status": "next" if i == 0 and not rt.servicing_order else "pending",
                              "time": min_to_hhmm(t)})
                t += float(self.sc.get("simulation.depot_reload_min"))
            else:
                o = self.orders[s.order_id]
                arrive = t
                t = max(t, o["ready_min"]) + o["service_min"]
                stops.append({"order_id": o["id"], "code": o["code"], "customer": o["customer_name"],
                              "lat": o["lat"], "lon": o["lon"],
                              "address": o["address"], "status": "next" if i == 0 and not rt.servicing_order else "pending",
                              "time": min_to_hhmm(arrive), "eta_min": round(arrive, 1),
                              "late": arrive > o["deadline_min"], "deadline": min_to_hhmm(o["deadline_min"]),
                              "weight_kg": o["weight_kg"], "priority": o["priority"]})
            prev = s.node
        next_stop = next((s for s in stops if s["status"] in ("servicing", "next")), None)
        total = len(done_orders) + len(assigned) + (1 if rt.servicing_order else 0)
        return {
            "id": v["id"], "code": v["code"], "model": v["model"], "driver_name": v["driver_name"],
            "driver_since": v["driver_since"], "capacity_kg": v["capacity_kg"], "depot_id": v["depot_id"],
            "active": v["active"],
            "status": ("inactive" if not v["active"] else
                       "scheduled" if rt.status == "moving" and rt.times and self.clock < rt.times[0] else rt.status),
            "departs_at": min_to_hhmm(rt.times[0]) if rt.status == "moving" and rt.times and self.clock < rt.times[0] else None,
            "lat": rt.lat, "lon": rt.lon, "heading": round(rt.heading, 1),
            "speed_kmh": 0.0 if rt.status == "moving" and rt.times and self.clock < rt.times[0] else round(rt.speed_kmh, 1),
            "load_kg": round(load, 1), "load_pct": round(load / v["capacity_kg"], 3) if v["capacity_kg"] else 0,
            "fuel_pct": round(v["fuel_level_l"] / v["fuel_tank_l"], 3) if v["fuel_tank_l"] else 0,
            "distance_km": round(rt.distance_m / 1000, 2),
            "stops_total": total, "stops_done": len(done_orders),
            "late_count": sum(1 for c in done_orders if c["note"] == "late"),
            "next_stop": next_stop, "stops": stops,
            "eta_end": min_to_hhmm(t + (self.net.path_stats(self._compute_path(prev, rt.depot_node))[1]
                                        if prev != rt.depot_node else 0)) if rt.stops else None,
            "route_version": self._route_version(rt),
            # motion = the road the vehicle is driving now with its schedule [[lat, lon, sim_min], …];
            # the UI interpolates along it every animation frame (no jumping between ticks)
            "motion": self.net.timed_coords(rt.path[rt.idx:], rt.times[rt.idx:]) if rt.status == "moving" else None,
        }

    def _route_version(self, rt: VehicleRuntime) -> str:
        key = (tuple((st.kind, st.order_id) for st in rt.stops), tuple(rt.path[-1:]), len(rt.path),
               rt.status, self.net.version, len(rt.completed))
        return format(hash(key) & 0xFFFFFFFF, "x")

    def vehicle_route(self, vehicle_id: int) -> dict:
        """Geometry of one vehicle: driven trail, current road (timed) and future legs."""
        with self._op():
            rt = self.runtime.get(vehicle_id)
            if rt is None:
                raise KeyError(vehicle_id)
            future = []
            start = rt.target.node if rt.status == "moving" and rt.target else rt.node
            for st in (rt.stops[1:] if rt.status == "moving" else rt.stops):
                if start != st.node:
                    future.append(self.net.path_coords(self._compute_path(start, st.node)))
                start = st.node
            if (rt.stops or rt.status == "moving") and start != rt.depot_node:
                future.append(self.net.path_coords(self._compute_path(start, rt.depot_node)))
            current = self.net.path_coords(rt.path[rt.idx:]) if rt.status == "moving" else []
            return {"vehicle_id": vehicle_id, "route_version": self._route_version(rt),
                    "trail": rt.trail[-600:], "current": current, "future": future,
                    "stops": self._vehicle_view(rt)["stops"]}

    def all_routes(self) -> dict:
        with self._op():
            out = []
            for rt in self.runtime.values():
                r = self.vehicle_route(rt.vehicle_id)
                paths = [p for p in ([r["current"]] + r["future"]) if len(p) > 1]
                if paths:
                    out.append({"vehicle_id": rt.vehicle_id, "paths": paths})
            return {"routes": out, "revision": self.revision}

    def kpis(self) -> dict:
        orders = [o for o in self.orders.values() if o["status"] != "cancelled"]
        delivered = [o for o in orders if o["status"] == "delivered"]
        late = [o for o in delivered if o["delivery_note"] == "late"]
        delays = [o["delivered_min"] - o["deadline_min"] for o in late]
        return {
            "total_orders": len(orders), "delivered": len(delivered),
            "pending": sum(1 for o in orders if o["status"] in ("pending", "assigned")),
            "in_transit": sum(1 for o in orders if o["status"] == "in_transit"),
            "unassigned": sum(1 for o in orders if o["status"] == "pending"),
            "late": len(late), "on_time_pct": round(1 - len(late) / len(delivered), 4) if delivered else None,
            "avg_delay_min": round(sum(delays) / len(delays), 1) if delays else 0.0,
            "active_vehicles": sum(1 for rt in self.runtime.values() if rt.status in ("moving", "servicing", "reloading")),
            "fleet_size": len(self.active_vehicles()),
            "distance_km": round(sum(rt.distance_m for rt in self.runtime.values()) / 1000, 2),
        }

    def snapshot(self) -> dict:
        with self._op():
            return {
                "revision": self.revision, "clock": self.clock, "clock_hhmm": min_to_hhmm(self.clock),
                "running": self.running, "dispatched": self.dispatched, "minutes_per_tick": self.minutes_per_tick,
                "tick_interval_s": float(self.sc.get("simulation.tick_interval_s")),
                "random_events": self.random_events,
                "shift": {"start": self.sc.get("schedule.shift_start"), "end": self.sc.get("schedule.shift_end")},
                "kpis": self.kpis(),
                "vehicles": [self.vehicle_view(rt) for rt in self.runtime.values()],
                "depots": list(self.depots.values()),
                "traffic": {
                    "congestions": [{k: c[k] for k in ("id", "center", "radius_m", "factor", "until_hhmm")} |
                                    {"segments": [self.net.edge_points(self.net.edges[(a, b)]) for a, b in c["edges"] if (a, b) in self.net.edges]}
                                    for c in self.congestions],
                    "closures": self.closures,
                },
                "persistence_error": self.persistence_error,
                "optimizing": self._optimizing,
                "network": {"source": self.city.get("source"), "city": self.city.get("city")},
                "jam_factor": float(self.sc.get("simulation.congestion.factor.max")) * 0.75,
                "plan": {"run_id": self.plan_meta["run_id"], "metrics": self.plan_meta["metrics"],
                         "algorithm": self.active_settings.get("algorithm")} if self.plan_meta else None,
                "feed": list(self.feed)[:20],
            }


# ---------------------------------------------------------------- utilities
def _merge_numeric(items: list[dict], keep: set | None = None) -> dict:
    out: dict = {}
    for it in items:
        for k, v in it.items():
            if keep and k in keep:
                out[k] = v
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = round(out.get(k, 0) + v, 4)
    return out


def _merge_metrics(items: list[dict]) -> dict:
    if not items:
        return {}
    if len(items) == 1:
        return items[0]
    out = _merge_numeric(items)
    out["feasible"] = all(i["feasible"] for i in items)
    caps = [i["vehicles_used"] for i in items]
    out["utilization"] = round(sum(i["utilization"] * c for i, c in zip(items, caps)) / max(1, sum(caps)), 4)
    out["makespan"] = max((i["makespan"] for i in items if i.get("makespan")), default=None)
    out["cost_breakdown"] = _merge_numeric([i["cost_breakdown"] for i in items])
    return out


def _improvement(before: dict, after: dict) -> dict:
    if not before or not after:
        return {}
    out = {}
    for k in ("objective", "distance_km", "duration_min", "lateness_min", "late_count", "vehicles_used", "fuel_l", "co2_kg"):
        b, a = before.get(k), after.get(k)
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            out[k] = {"before": b, "after": a, "delta": round(b - a, 2),
                      "pct": round((b - a) / b * 100, 2) if b else 0.0}
    return out


ENGINE = LogisticsEngine()
