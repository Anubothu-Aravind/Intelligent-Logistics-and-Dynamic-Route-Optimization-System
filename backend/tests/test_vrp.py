import pytest

from app.algorithms import construction, genetic, local_search
from app.algorithms.vrp import DEPOT, Weights, evaluate_solution, route_cost, evaluate_route
from app.core.config import get_scenario
from app.services.benchmark import synthetic_instance as _synthetic_instance


@pytest.fixture(scope="module")
def bi():
    return _synthetic_instance(get_scenario(), 40, 4, 3)[0]


def _check_complete(inst, sol):
    served = [c for r in sol.routes for c in r if c != DEPOT] + sol.unassigned
    assert sorted(served) == sorted(inst.customers), "every order exactly once"


@pytest.mark.parametrize("name", ["fifo", "nearest_neighbour", "clarke_wright", "sweep"])
def test_constructions_serve_every_order_within_capacity(bi, name):
    inst = bi.inst
    sol = construction.CONSTRUCTIONS[name](inst)
    _check_complete(inst, sol)
    for k, r in enumerate(sol.routes):
        assert sum(inst.demand[c] for c in r) <= inst.vehicles[k].capacity + 1e-9


def test_fast_route_cost_matches_full_evaluator(bi):
    inst = bi.inst
    sol = construction.nearest_neighbour(inst)
    for k, r in enumerate(sol.routes):
        assert route_cost(inst, k, r) == pytest.approx(evaluate_route(inst, k, r).cost)


def test_local_search_never_worsens(bi):
    inst = bi.inst
    sol = construction.sweep(inst)
    before = evaluate_solution(inst, sol)["cost"]
    better, gains = local_search.improve(inst, sol, ["two_opt", "or_opt", "relocate", "swap"], 20)
    _check_complete(inst, better)
    assert evaluate_solution(inst, better)["cost"] <= before + 1e-6
    assert all(g >= 0 for g in gains.values())


def test_optimised_beats_fifo_baseline(bi):
    inst = bi.inst
    fifo = evaluate_solution(inst, construction.fifo(inst))["cost"]
    cw, _ = local_search.improve(inst, construction.clarke_wright(inst), ["two_opt", "or_opt", "relocate"], 20)
    assert evaluate_solution(inst, cw)["cost"] < fifo


def test_genetic_split_and_convergence(bi):
    inst = bi.inst
    params = genetic.GAParams(20, 15, 3, 0.9, 0.2, 2, 30, False, 1)
    sol = genetic.genetic_algorithm(inst, params)
    _check_complete(inst, sol)
    assert sol.history == sorted(sol.history, reverse=True), "elitism keeps best non-increasing"


def test_objective_weights_change_behaviour(bi):
    inst = bi.inst
    sol = construction.clarke_wright(inst)
    base = evaluate_solution(inst, sol)
    from dataclasses import replace
    inst.weights = replace(inst.weights, delta=1000.0)
    heavy = evaluate_solution(inst, sol)
    assert heavy["cost"] - base["cost"] == pytest.approx((1000.0 - get_scenario().get("objective.delta_vehicle_fixed"))
                                                        * base["vehicles_used"])


def test_vehicle_already_working_pays_no_second_fixed_cost(bi):
    from dataclasses import replace
    inst = bi.inst
    sol = construction.clarke_wright(inst)
    k = next(i for i, r in enumerate(sol.routes) if r)
    fresh = route_cost(inst, k, sol.routes[k])
    inst.vehicles[k] = replace(inst.vehicles[k], used_today=True)
    try:
        assert fresh - route_cost(inst, k, sol.routes[k]) == pytest.approx(inst.weights.delta)
    finally:
        inst.vehicles[k] = replace(inst.vehicles[k], used_today=False)


def test_max_route_duration_spreads_work_over_vehicles(bi):
    """With the overtime penalty, inserting many orders should not pile them on one vehicle."""
    from dataclasses import replace
    from app.algorithms.vrp import Solution
    inst = bi.inst
    old = inst.weights
    inst.weights = replace(old, max_route_min=120.0, overtime_penalty=5.0)
    try:
        sol = construction.regret_insertion(inst, Solution([[] for _ in inst.vehicles], list(inst.customers)))
        used = [r for r in sol.routes if r]
        assert len(used) >= 2
        assert max(len(r) for r in used) < len(inst.customers)
    finally:
        inst.weights = old


def test_new_orders_are_shared_not_piled_on_one_vehicle():
    """Regression: with few orders, every new order used to go to the first vehicle."""
    from collections import Counter
    from app.services.engine import ENGINE as E
    E.bootstrap(reseed=True)
    E.delete_orders(flt={}, include_delivered=True)
    for _ in range(8):
        E.add_order({})
    E.optimize({})
    E.set_running(True)
    for _ in range(10):
        E.tick()
    for _ in range(8):
        E.event_new_order({})
    per_vehicle = Counter(o["vehicle_id"] for o in E.orders.values() if o["source"] == "simulated")
    assert len(per_vehicle) >= 3 and max(per_vehicle.values()) <= 4
    E.reset_simulation()
