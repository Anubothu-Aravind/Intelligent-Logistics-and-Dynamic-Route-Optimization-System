import random

import pytest

from app.algorithms.shortest_path import (astar, bidirectional_dijkstra, dijkstra, floyd_path, floyd_warshall,
                                          yen_k_shortest)
from app.core.config import get_scenario
from app.services.city_generator import generate_city


@pytest.fixture(scope="module")
def net():
    sc = get_scenario()
    return generate_city(sc.section("city"), 7, rows=12, cols=12)[0]


def _pairs(net, n=25):
    rng = random.Random(1)
    ids = list(net.nodes)
    return [(rng.choice(ids), rng.choice(ids)) for _ in range(n)]


@pytest.mark.parametrize("metric", ["time", "distance"])
def test_all_algorithms_agree_on_optimal_cost(net, metric):
    idx, dist, nxt, _ = floyd_warshall(net, metric)
    for s, t in _pairs(net):
        d = dijkstra(net, s, t, metric)
        a = astar(net, s, t, metric)
        b = bidirectional_dijkstra(net, s, t, metric)
        assert d.cost == pytest.approx(a.cost) == pytest.approx(b.cost) == pytest.approx(dist[idx[s]][idx[t]])
        assert d.nodes[0] == s and d.nodes[-1] == t
        assert floyd_path(idx, nxt, s, t)[-1] == t


def test_astar_expands_no_more_than_dijkstra(net):
    total_d = total_a = 0
    for s, t in _pairs(net):
        total_d += dijkstra(net, s, t).expanded
        total_a += astar(net, s, t).expanded
    assert total_a <= total_d


def test_yen_returns_distinct_sorted_paths(net):
    s, t = _pairs(net, 1)[0]
    paths = yen_k_shortest(net, s, t, 3)
    assert len({tuple(p.nodes) for p in paths}) == len(paths)
    costs = [p.cost for p in paths]
    assert costs == sorted(costs)


def test_closed_road_is_avoided(net):
    s, t = _pairs(net, 1)[0]
    p = dijkstra(net, s, t)
    if len(p.nodes) < 3:
        pytest.skip("trivial path")
    u, v = p.nodes[1], p.nodes[2]
    net.set_closed(u, v, True)
    try:
        q = astar(net, s, t)
        assert (u, v) not in set(zip(q.nodes, q.nodes[1:]))
        assert q.cost >= p.cost
    finally:
        net.set_closed(u, v, False)
