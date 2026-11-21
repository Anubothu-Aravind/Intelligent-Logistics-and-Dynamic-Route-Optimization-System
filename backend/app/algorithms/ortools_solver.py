"""Google OR-Tools routing solver – used ONLY as an external comparison baseline.

The project's own algorithms (construction + local search + GA) are the
primary engine; OR-Tools gives a reference point for solution quality.
"""
from __future__ import annotations

from .vrp import DEPOT, Instance, Solution

try:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    AVAILABLE = False


def solve(inst: Instance, time_limit_s: int) -> Solution:
    if not AVAILABLE:
        raise RuntimeError("OR-Tools is not installed")
    customers = list(inst.customers)
    nodes = [DEPOT] + customers                 # local index -> instance point
    n, m = len(nodes), len(inst.vehicles)
    mgr = pywrapcp.RoutingIndexManager(n, m, 0)
    routing = pywrapcp.RoutingModel(mgr)
    w = inst.weights
    scale = 100

    def arc(i, j):
        a, b = nodes[mgr.IndexToNode(i)], nodes[mgr.IndexToNode(j)]
        return int(scale * (w.alpha * inst.dist[a][b] / 1000.0 + w.beta * inst.time[a][b]))

    cb = routing.RegisterTransitCallback(arc)
    routing.SetArcCostEvaluatorOfAllVehicles(cb)
    for k in range(m):
        routing.SetFixedCostOfVehicle(int(scale * w.delta), k)

    dem_cb = routing.RegisterUnaryTransitCallback(lambda i: int(inst.demand[nodes[mgr.IndexToNode(i)]]))
    routing.AddDimensionWithVehicleCapacity(dem_cb, 0, [int(v.capacity) for v in inst.vehicles], True, "Cap")

    def travel(i, j):
        a, b = nodes[mgr.IndexToNode(i)], nodes[mgr.IndexToNode(j)]
        return int(inst.time[a][b] + inst.service[a])

    t_cb = routing.RegisterTransitCallback(travel)
    horizon = int(max(inst.deadline[c] for c in customers) + 24 * 60)
    routing.AddDimension(t_cb, horizon, horizon, False, "Time")
    tdim = routing.GetDimensionOrDie("Time")
    for k, v in enumerate(inst.vehicles):
        tdim.CumulVar(routing.Start(k)).SetRange(int(v.start_time), int(v.start_time))
    for li, c in enumerate(nodes):
        if li == 0:
            continue
        idx = mgr.NodeToIndex(li)
        tdim.CumulVar(idx).SetMin(int(inst.ready[c]))
        tdim.SetCumulVarSoftUpperBound(idx, int(inst.deadline[c]),
                                       int(scale * w.gamma * inst.penalty_mult[c]))
        routing.AddDisjunction([idx], int(scale * w.unassigned_penalty))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = int(time_limit_s)
    result = routing.SolveWithParameters(params)
    routes = [[] for _ in range(m)]
    served = set()
    if result:
        for k in range(m):
            idx = routing.Start(k)
            while not routing.IsEnd(idx):
                node = nodes[mgr.IndexToNode(idx)]
                if node != DEPOT:
                    routes[k].append(node)
                    served.add(node)
                idx = result.Value(routing.NextVar(idx))
    return Solution(routes, [c for c in customers if c not in served], "ortools")
