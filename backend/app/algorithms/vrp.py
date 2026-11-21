"""Capacitated Vehicle Routing Problem with Time Windows (CVRPTW) model.

Objective (minimised):   Z = alpha*D + beta*T + gamma*L + delta*V  (+ penalties)

  D  total distance [km]            T  total route duration [min]
  L  priority-weighted lateness     V  number of vehicles used

Constraints handled by the evaluator (violations are penalised so that
meta-heuristics can traverse infeasible space):
  * each accepted order delivered exactly once (unassigned -> penalty)
  * sum(demand in a load segment) <= capacity of the vehicle
  * time windows [ready, deadline] (early -> wait, late -> lateness penalty)
  * vehicles start at their current position and return to the depot

Point index 0 is always the depot. Inside a route, the value 0 denotes a
*reload visit* at the depot (needed in the dynamic case when an order that is
still at the warehouse is given to a vehicle already on the road).
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEPOT = 0


@dataclass
class Weights:
    alpha: float
    beta: float
    gamma: float
    delta: float
    capacity_penalty: float
    unassigned_penalty: float
    max_route_min: float = float("inf")
    overtime_penalty: float = 0.0
    epsilon: float = 0.0           # cost per minute an order waits after its ready time
    zeta: float = 0.0              # workload balance: cost per (route hour)^2

    @classmethod
    def from_scenario(cls, objective: dict, overrides: dict | None = None) -> "Weights":
        o = dict(objective)
        o.update({k: v for k, v in (overrides or {}).items() if v is not None})
        return cls(
            alpha=float(o["alpha_distance_per_km"]), beta=float(o["beta_time_per_min"]),
            gamma=float(o["gamma_lateness_per_min"]), delta=float(o["delta_vehicle_fixed"]),
            capacity_penalty=float(o["capacity_violation_penalty"]),
            unassigned_penalty=float(o.get("unassigned_penalty", o["capacity_violation_penalty"] * 5)),
            max_route_min=float(o.get("max_route_duration_min") or float("inf")),
            overtime_penalty=float(o.get("route_overtime_penalty_per_min", 0.0)),
            epsilon=float(o.get("epsilon_waiting_per_min", 0.0)),
            zeta=float(o.get("zeta_balance_per_h2", 0.0)),
        )

    def fixed(self, used_today: bool) -> float:
        """Vehicle fixed cost δ is paid once per day – not again for a vehicle already working."""
        return 0.0 if used_today else self.delta

    def overtime(self, duration: float) -> float:
        return self.overtime_penalty * max(0.0, duration - self.max_route_min)

    def balance(self, duration: float, prior: float = 0.0) -> float:
        """Convex in the driver's total work today (minutes already worked + this route):
        adding work to a driver who has worked less is cheaper -> fair spread over the fleet."""
        h, p = (prior + duration) / 60.0, prior / 60.0
        return self.zeta * (h * h - p * p)


@dataclass
class VehicleSpec:
    key: int                       # database id
    capacity: float
    start_point: int               # matrix point where the vehicle starts
    start_time: float              # minute of day
    at_depot: bool = True          # can load everything before its first stop
    onboard: frozenset[int] = frozenset()   # customers already loaded on this vehicle
    used_today: bool = False       # fixed cost δ already paid (vehicle has been dispatched today)
    prior_work_min: float = 0.0    # minutes this driver has already worked today (driving + service)


@dataclass
class Instance:
    time: list[list[float]]
    dist: list[list[float]]
    demand: list[float]
    service: list[float]
    ready: list[float]
    deadline: list[float]
    penalty_mult: list[float]
    customers: list[int]           # point indices that must be served
    vehicles: list[VehicleSpec]
    weights: Weights
    depot_dwell: float = 0.0
    angle: list[float] = field(default_factory=list)   # polar angle around depot (Sweep)

    def neighbours(self, k: int) -> dict[int, list[int]]:
        """Granular neighbour lists: the k closest customers (by travel time) of each customer."""
        cache = getattr(self, "_nb", None)
        if cache is None or cache[0] != k:
            nb = {c: sorted((x for x in self.customers if x != c),
                            key=lambda x: self.time[c][x] + self.time[x][c])[:k] for c in self.customers}
            self._nb = (k, nb)
        return self._nb[1]

    def owner_lock(self) -> dict[int, int]:
        """Customers that are physically on a vehicle cannot change vehicle."""
        return {c: k for k, v in enumerate(self.vehicles) for c in v.onboard}


@dataclass
class RouteEval:
    distance_km: float = 0.0
    duration_min: float = 0.0
    lateness_min: float = 0.0
    weighted_lateness: float = 0.0
    late_count: int = 0
    early_count: int = 0
    wait_min: float = 0.0
    load_kg: float = 0.0
    overload_kg: float = 0.0
    invalid: int = 0
    used: bool = False
    cost: float = 0.0
    overtime_cost: float = 0.0
    balance_cost: float = 0.0
    waiting_min: float = 0.0       # Σ (service start − ready) over the route's orders
    work_min: float = 0.0          # driving + service + depot dwell (idle waiting is not work)
    departure_delay: float = 0.0   # minutes a parked vehicle stays at the depot before leaving
    arrivals: list[float] = field(default_factory=list)
    end_time: float = 0.0

    @property
    def feasible(self) -> bool:
        return self.overload_kg <= 1e-9 and self.invalid == 0


def evaluate_route(inst: Instance, k: int, seq: list[int]) -> RouteEval:
    v = inst.vehicles[k]
    ev = RouteEval(end_time=v.start_time)
    if not any(c != DEPOT for c in seq):
        return ev
    ev.used = True
    T, D, dem = inst.time, inst.dist, inst.demand
    onboard = v.onboard

    def segment_load(start: int) -> tuple[float, int]:
        load, bad = 0.0, 0
        for c in seq[start:]:
            if c == DEPOT:
                break
            load += dem[c] if c not in onboard else 0.0
        return load, bad

    # ---- initial load
    first_seg, _ = segment_load(0)
    if v.at_depot:
        load = first_seg + sum(dem[c] for c in seq if c in onboard)
    else:
        load = sum(dem[c] for c in seq if c in onboard)
        for c in seq:
            if c == DEPOT:
                break
            if c not in onboard:
                ev.invalid += 1            # cannot deliver a parcel never loaded
    ev.overload_kg += max(0.0, load - v.capacity)
    ev.load_kg = load

    t, pos, d = v.start_time, v.start_point, 0.0
    work = 0.0
    first_wait = None          # a parked vehicle simply departs later instead of waiting
    for i, c in enumerate(seq):
        t += T[pos][c]
        d += D[pos][c]
        work += T[pos][c]
        if c == DEPOT:
            t += inst.depot_dwell
            work += inst.depot_dwell
            extra, _ = segment_load(i + 1)
            load += extra
            ev.overload_kg += max(0.0, load - v.capacity)
            ev.load_kg = max(ev.load_kg, load)
        else:
            w0 = max(0.0, inst.ready[c] - t)
            if first_wait is None:
                first_wait = w0
            if t < inst.ready[c]:
                ev.wait_min += inst.ready[c] - t
                ev.early_count += 1
                t = inst.ready[c]
            ev.arrivals.append(t)
            ev.waiting_min += t - inst.ready[c]
            late = t - inst.deadline[c]
            if late > 0:
                ev.lateness_min += late
                ev.weighted_lateness += late * inst.penalty_mult[c]
                ev.late_count += 1
            t += inst.service[c]
            work += inst.service[c]
            load -= dem[c]
        pos = c
    t += T[pos][DEPOT]
    d += D[pos][DEPOT]
    work += T[pos][DEPOT]
    ev.work_min = work
    ev.end_time = t
    ev.distance_km = d / 1000.0
    ev.departure_delay = (first_wait or 0.0) if v.at_depot and v.start_point == DEPOT else 0.0
    ev.duration_min = t - v.start_time - ev.departure_delay
    w = inst.weights
    ev.overtime_cost = w.overtime(ev.duration_min)          # shift length: elapsed time
    ev.balance_cost = w.balance(work, v.prior_work_min)      # fairness: actual work
    ev.cost = (w.alpha * ev.distance_km + w.beta * work
               + w.gamma * ev.weighted_lateness + w.epsilon * ev.waiting_min + w.fixed(v.used_today) + ev.overtime_cost + ev.balance_cost
               + w.capacity_penalty * (ev.overload_kg + 10 * ev.invalid))
    return ev


def route_cost(inst: Instance, k: int, seq: list[int]) -> float:
    """Objective of one route. Hot path of every heuristic, so the common case
    (vehicle loads at the depot, no reload visits) is evaluated inline."""
    if not seq:
        return 0.0
    v = inst.vehicles[k]
    if not (v.at_depot and not v.onboard and not v.used_today) or DEPOT in seq:
        return evaluate_route(inst, k, seq).cost
    T, D = inst.time, inst.dist
    dem, ready, dl, svc, pm = inst.demand, inst.ready, inst.deadline, inst.service, inst.penalty_mult
    load = d = latew = wait = work = 0.0
    t, pos = v.start_time, v.start_point
    first = True
    delay = 0.0
    for c in seq:
        load += dem[c]
        t += T[pos][c]
        d += D[pos][c]
        work += T[pos][c] + svc[c]
        if t < ready[c]:
            if first and pos == DEPOT:
                delay = ready[c] - t
            t = ready[c]
        first = False
        wait += t - ready[c]
        if t > dl[c]:
            latew += (t - dl[c]) * pm[c]
        t += svc[c]
        pos = c
    t += T[pos][DEPOT]
    d += D[pos][DEPOT]
    w = inst.weights
    over = load - v.capacity if load > v.capacity else 0.0
    dur = t - v.start_time - delay
    work += T[pos][DEPOT]
    return (w.alpha * d / 1000.0 + w.beta * work + w.gamma * latew + w.epsilon * wait + w.delta
            + w.overtime(dur) + w.balance(work) + w.capacity_penalty * over)


@dataclass
class Solution:
    routes: list[list[int]]
    unassigned: list[int] = field(default_factory=list)
    algorithm: str = ""
    history: list[float] = field(default_factory=list)     # convergence trace
    notes: list[str] = field(default_factory=list)

    def copy(self) -> "Solution":
        return Solution([list(r) for r in self.routes], list(self.unassigned),
                        self.algorithm, list(self.history), list(self.notes))


def evaluate_solution(inst: Instance, sol: Solution) -> dict:
    evals = [evaluate_route(inst, k, r) for k, r in enumerate(sol.routes)]
    total = sum(e.cost for e in evals) + inst.weights.unassigned_penalty * len(sol.unassigned)
    return {
        "cost": total,
        "distance_km": sum(e.distance_km for e in evals),
        "duration_min": sum(e.duration_min for e in evals),
        "lateness_min": sum(e.lateness_min for e in evals),
        "late_count": sum(e.late_count for e in evals),
        "early_count": sum(e.early_count for e in evals),
        "vehicles_used": sum(1 for e in evals if e.used),
        "overload_kg": sum(e.overload_kg for e in evals),
        "invalid": sum(e.invalid for e in evals),
        "unassigned": len(sol.unassigned),
        "feasible": all(e.feasible for e in evals) and not sol.unassigned,
        "makespan": max((e.end_time for e in evals if e.used), default=0.0),
        "routes": evals,
    }


def solution_cost(inst: Instance, sol: Solution) -> float:
    return (sum(route_cost(inst, k, r) for k, r in enumerate(sol.routes))
            + inst.weights.unassigned_penalty * len(sol.unassigned))


def normalize_route(inst: Instance, k: int, seq: list[int]) -> list[int]:
    """Drop depot reload visits that pick nothing up."""
    onboard = inst.vehicles[k].onboard
    out: list[int] = []
    for i, c in enumerate(seq):
        if c == DEPOT:
            nxt = []
            for x in seq[i + 1:]:
                if x == DEPOT:
                    break
                nxt.append(x)
            if not any(x not in onboard for x in nxt):
                continue
            if out and out[-1] == DEPOT:
                continue
        out.append(c)
    return out


def best_insertion(inst: Instance, k: int, seq: list[int], customer: int) -> tuple[float, list[int]]:
    """Cheapest feasible position for `customer` in route k (may add a reload visit)."""
    base = route_cost(inst, k, seq)
    best_delta, best_seq = float("inf"), seq
    v = inst.vehicles[k]
    needs_reload = not v.at_depot and customer not in v.onboard
    for pos in range(len(seq) + 1):
        cand = seq[:pos] + [customer] + seq[pos:]
        delta = route_cost(inst, k, cand) - base
        if delta < best_delta:
            best_delta, best_seq = delta, cand
        if needs_reload:
            cand2 = seq[:pos] + [DEPOT, customer] + seq[pos:]
            delta2 = route_cost(inst, k, cand2) - base
            if delta2 < best_delta:
                best_delta, best_seq = delta2, cand2
    return best_delta, normalize_route(inst, k, best_seq)
