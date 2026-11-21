"""OSM import: built from a fixture in exact Overpass JSON format (no network)."""
import json
from pathlib import Path

import pytest

from app.algorithms.shortest_path import dijkstra
from app.core.config import get_scenario
from app.services import osm_loader
from app.services.city_generator import load_network

FIX = Path(__file__).parent / "fixtures" / "overpass_small.json"


@pytest.fixture(scope="module")
def built():
    return osm_loader.build_network(json.loads(FIX.read_text()), get_scenario().section("city")["osm"])


def test_graph_keeps_largest_component_and_compact_ids(built):
    net, meta = built
    assert set(net.nodes) == set(range(len(net.nodes)))      # remapped 0..N-1
    assert meta["removed_unreachable_nodes"] == 2             # the island
    assert net.is_strongly_connected_from(0)


def test_shape_points_are_contracted_into_geometry(built):
    net, _ = built
    curved = [e for e in net.edges.values() if e.geometry]
    assert curved and all(len(e.geometry) == 2 for e in curved)   # s1, s2 kept as shape
    e = curved[0]
    pts = net.edge_points(e)
    straight = ((pts[0][0] - pts[-1][0]) ** 2 + (pts[0][1] - pts[-1][1]) ** 2) ** 0.5
    assert e.length_m > 0 and len(net.path_coords([e.u, e.v])) == 4 and straight > 0


def test_oneway_and_maxspeed(built):
    net, _ = built
    oneway = [e for e in net.edges.values() if e.name == "One Way Lane"]
    assert oneway and all((e.v, e.u) not in net.edges for e in oneway)
    assert all(e.speed_kmh == 50 for e in net.edges.values() if e.name == "Middle Street")
    assert {e.road_class for e in net.edges.values() if e.name == "Middle Street"} == {"arterial"}


def test_routing_on_osm_graph(built):
    net, _ = built
    res = dijkstra(net, 0, len(net.nodes) - 1)
    assert res.found and res.cost > 0


def test_unreachable_api_reports_missing_map(tmp_path):
    from app.services.city_generator import MapUnavailable
    cfg = dict(get_scenario().section("city"))
    cfg["source"] = "osm"
    cfg["osm"] = {**cfg["osm"], "overpass_urls": ["http://127.0.0.1:9/api"], "timeout_s": 1}
    with pytest.raises(MapUnavailable, match="set-up.sh"):
        load_network(cfg, 1, tmp_path)


def test_cache_is_used_before_network(tmp_path):
    cfg = dict(get_scenario().section("city"))
    cfg["source"] = "osm"
    cfg["osm"] = {**cfg["osm"], "overpass_urls": ["http://127.0.0.1:9/api"], "timeout_s": 1}
    p = osm_loader.cache_path(cfg["osm"], float(cfg["center_lat"]), float(cfg["center_lon"]),
                              tmp_path / cfg["osm"]["cache_dir"].removeprefix("data/"))
    p.parent.mkdir(parents=True)
    p.write_text(FIX.read_text())
    net, meta = load_network(cfg, 1, tmp_path)
    assert meta["source"] == "osm" and meta["origin"] == "cache"


def test_failure_is_remembered_so_restarts_are_fast(tmp_path):
    import time
    cfg = dict(get_scenario().section("city"))
    cfg["source"] = "osm"
    cfg["osm"] = {**cfg["osm"], "overpass_urls": ["http://127.0.0.1:9/api"], "timeout_s": 1}
    from app.services.city_generator import MapUnavailable
    with pytest.raises(MapUnavailable):
        load_network(cfg, 1, tmp_path)                  # first failure is recorded
    cfg["osm"]["overpass_urls"] = ["http://10.255.255.1/api"]   # would hang if contacted
    t = time.perf_counter()
    with pytest.raises(MapUnavailable, match="next attempt"):
        load_network(cfg, 1, tmp_path)
    assert time.perf_counter() - t < 1.0
