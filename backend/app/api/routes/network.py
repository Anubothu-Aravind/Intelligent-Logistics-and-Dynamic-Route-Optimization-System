from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.algorithms.shortest_path import POINT_TO_POINT, floyd_path, floyd_warshall, yen_k_shortest
from app.api.deps import engine
from app.schemas.requests import PathQueryIn

router = APIRouter(prefix="/network", tags=["road network"])


def _ui(eng) -> dict:
    ui = dict(eng.sc.section("ui"))
    real = eng.city.get("source") == "osm"
    ui["city"] = eng.city.get("city")
    if ui.get("default_basemap", "auto") == "auto":
        ui["default_basemap"] = "tiles" if real else "schematic"
    # tiles under a generated city would show streets that do not exist in the graph
    ui["tiles_match_graph"] = real
    return ui


@router.get("")
def network(request: Request, response: Response, eng=Depends(engine)):
    """Road graph for drawing. Static per scenario -> ETag so browsers re-use it."""
    net = eng.net
    etag = f'W/"net-{eng.seed}-{len(net.nodes)}-{len(net.edges)}-{eng.city.get("source")}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    seen, roads = set(), []
    for (u, v), e in net.edges.items():
        key = (min(u, v), max(u, v))
        if key in seen:
            continue
        seen.add(key)
        roads.append({"u": u, "v": v, "class": e.road_class, "name": e.name,
                      "coords": [[round(a, 6), round(b, 6)] for a, b in net.edge_points(e)]})
    lats = [p[0] for p in net.nodes.values()]
    lons = [p[1] for p in net.nodes.values()]
    return {"nodes": len(net.nodes), "edges": len(net.edges), "roads": roads,
            "bounds": [[min(lats), min(lons)], [max(lats), max(lons)]],
            "meta": {k: v for k, v in eng.city.items() if k != "street_names"}, "ui": _ui(eng)}


def _endpoints(eng, body) -> tuple[int, int]:
    net = eng.net
    if body.source is not None and body.target is not None:
        src, dst = body.source, body.target
    elif None not in (body.source_lat, body.source_lon, body.target_lat, body.target_lon):
        src = net.nearest_node(body.source_lat, body.source_lon)
        dst = net.nearest_node(body.target_lat, body.target_lon)
    else:
        raise HTTPException(422, "Give source/target node ids or both coordinate pairs")
    if src not in net.nodes or dst not in net.nodes:
        raise HTTPException(404, "Unknown node")
    if src == dst:
        raise HTTPException(400, "Origin and destination snap to the same intersection – pick points further apart")
    return src, dst


@router.post("/path")
def path_query(body: PathQueryIn, eng=Depends(engine)):
    """Run every shortest-path algorithm on the same query and compare them."""
    with eng.lock:
        net = eng.net
        src, dst = _endpoints(eng, body)
        results = {name: fn(net, src, dst, body.metric).to_dict(net) for name, fn in POINT_TO_POINT.items()}
        fw = None
        if len(net.nodes) <= int(eng.sc.get("algorithms.floyd_warshall_max_nodes")):
            idx, dist, nxt, ms = floyd_warshall(net, body.metric)
            fw = {"algorithm": "floyd_warshall", "precompute_ms": round(ms, 1),
                  "cost": round(dist[idx[src]][idx[dst]], 4), "nodes": floyd_path(idx, nxt, src, dst)}
        k = body.k or int(eng.sc.get("algorithms.k_alternative_paths"))
        alts = [p.to_dict(net) for p in yen_k_shortest(net, src, dst, k, body.metric)]
    return {"source": src, "target": dst, "metric": body.metric, "results": results,
            "floyd_warshall": fw, "alternatives": alts}


class TraceIn(PathQueryIn):
    algorithms: list[str] = Field(default_factory=lambda: list(POINT_TO_POINT))


@router.post("/path/trace")
def path_trace(body: TraceIn, eng=Depends(engine)):
    """Step-by-step exploration order of each algorithm (for the visualiser).

    expanded[i] = [lat, lon, side] for the i-th settled node (side 1 = backward search)."""
    bad = [a for a in body.algorithms if a not in POINT_TO_POINT]
    if bad:
        raise HTTPException(422, f"Unknown algorithm(s): {bad}")
    with eng.lock:
        net = eng.net
        src, dst = _endpoints(eng, body)
        out = {}
        for name in body.algorithms:
            trace: list[int] = []
            res = POINT_TO_POINT[name](net, src, dst, body.metric, trace=trace)
            pts = []
            for t in trace:
                node, side = (t, 0) if t >= 0 else (-t - 1, 1)
                lat, lon = net.nodes[node]
                pts.append([round(lat, 6), round(lon, 6), side])
            out[name] = {**{k: v for k, v in res.to_dict(net).items() if k != "nodes"}, "expanded_nodes": pts}
        k = body.k or int(eng.sc.get("algorithms.k_alternative_paths"))
        alts = [{k2: v for k2, v in p.to_dict(net).items() if k2 != "nodes"} for p in yen_k_shortest(net, src, dst, k, body.metric)]
        return {"source": src, "target": dst, "source_coords": net.nodes[src], "target_coords": net.nodes[dst],
                "metric": body.metric, "graph_nodes": len(net.nodes), "results": out, "alternatives": alts,
                "heuristic": "straight-line distance" + (" ÷ max speed limit" if body.metric == "time" else "")}
