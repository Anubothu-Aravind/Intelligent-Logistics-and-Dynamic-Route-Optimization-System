"""Real road network from OpenStreetMap (Overpass API).

* fetched once and cached on disk (keyed by centre, radius and road types), so
  the public API is not hit on every start
* every OSM way becomes directed edges (oneway / roundabout respected, maxspeed
  parsed, otherwise a per-highway-type default speed from settings.yaml)
* chains of degree-2 nodes are contracted into single edges that keep the road
  shape as geometry -> fewer nodes for the algorithms, curved roads on the map
* only the largest strongly connected component is kept (every stop reachable)
* OSM ids are remapped to compact ids 0..N-1 (fits the existing INTEGER columns)
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from app.algorithms.graph import RoadNetwork
from app.core.geo import haversine_m

log = logging.getLogger("logistics.osm")


class OSMUnavailable(RuntimeError):
    pass


def _query(cfg: dict, lat: float, lon: float) -> str:
    types = "|".join(cfg["highway_types"])
    return (f'[out:json][timeout:{int(cfg["timeout_s"])}];'
            f'way["highway"~"^({types})$"](around:{int(cfg["radius_m"])},{lat},{lon});'
            f'(._;>;);out body;')


def cache_path(cfg: dict, lat: float, lon: float, base_dir: Path) -> Path:
    key = json.dumps([round(lat, 5), round(lon, 5), cfg["radius_m"], sorted(cfg["highway_types"])])
    return base_dir / f"overpass_{hashlib.sha1(key.encode()).hexdigest()[:12]}.json"


def fetch_overpass(cfg: dict, lat: float, lon: float, base_dir: Path, force: bool = False) -> tuple[dict, str]:
    """Return (overpass json, origin) where origin is 'cache' or the endpoint used."""
    path = cache_path(cfg, lat, lon, base_dir)
    if path.exists():
        return json.loads(path.read_text()), "cache"
    failed = path.with_suffix(".unavailable")
    retry_after = float(cfg.get("retry_after_min", 30)) * 60
    if not force and failed.exists() and time.time() - failed.stat().st_mtime < retry_after:
        # recent failure: don't make every restart wait for the network again
        raise OSMUnavailable(failed.read_text() + f" (next attempt after {retry_after / 60:.0f} min, or delete {failed.name})")
    query = _query(cfg, lat, lon)
    errors = []
    for url in cfg["overpass_urls"] * (2 if force else 1):     # set-up retries every mirror twice
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": query}).encode(),
                                         headers={"User-Agent": "intelligent-logistics-student-project/1.0"})
            with urllib.request.urlopen(req, timeout=float(cfg["timeout_s"]) + 10) as resp:
                data = json.loads(resp.read())
            if not data.get("elements"):
                raise OSMUnavailable("Overpass returned no roads for this area")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data))
            return data, url
        except Exception as exc:  # network errors, HTTP errors, bad JSON
            reason = getattr(exc, "reason", None) or getattr(exc, "code", None) or exc
            errors.append(f"{urllib.parse.urlparse(url).netloc} unreachable ({str(reason)[:120]})")
    msg = "; ".join(errors) or "no Overpass endpoint configured"
    try:
        failed.parent.mkdir(parents=True, exist_ok=True)
        failed.write_text(msg)
    except OSError:
        pass
    raise OSMUnavailable(msg)


_SPEED = re.compile(r"(\d+(?:\.\d+)?)\s*(mph|km/h|kmh)?", re.I)


def _maxspeed(tag: str | None) -> float | None:
    if not tag:
        return None
    m = _SPEED.match(tag.strip())
    if not m:
        return None
    v = float(m.group(1))
    return v * 1.609 if (m.group(2) or "").lower() == "mph" else v


def build_network(data: dict, cfg: dict) -> tuple[RoadNetwork, dict]:
    nodes = {e["id"]: (e["lat"], e["lon"]) for e in data["elements"] if e["type"] == "node"}
    ways = [e for e in data["elements"] if e["type"] == "way" and len(e.get("nodes", [])) > 1]
    speeds, arterial = cfg["speeds_kmh"], set(cfg["arterial_types"])

    # raw directed adjacency on OSM node ids
    raw: dict[tuple[int, int], tuple[float, str, str]] = {}
    degree: dict[int, set[int]] = {}
    endpoints: set[int] = set()
    for w in ways:
        tags = w.get("tags", {})
        hw = tags.get("highway", "residential")
        speed = _maxspeed(tags.get("maxspeed")) or float(speeds.get(hw, speeds["default"]))
        name = tags.get("name") or tags.get("ref") or hw.replace("_", " ").title()
        cls = "arterial" if hw.removesuffix("_link") in arterial else "local"
        oneway = tags.get("oneway", "no")
        if tags.get("junction") in ("roundabout", "circular") and oneway == "no":
            oneway = "yes"
        seq = [n for n in w["nodes"] if n in nodes]
        endpoints.update((seq[0], seq[-1]))
        for a, b in zip(seq, seq[1:]):
            if a == b:
                continue
            degree.setdefault(a, set()).add(b)
            degree.setdefault(b, set()).add(a)
            if oneway in ("-1", "reverse"):
                raw[(b, a)] = (speed, cls, name)
            else:
                raw[(a, b)] = (speed, cls, name)
                if oneway not in ("yes", "true", "1"):
                    raw[(b, a)] = (speed, cls, name)

    # A node is contracted only if it is a pure pass-through: exactly two neighbours,
    # identical direction pattern on both sides and identical road attributes.
    out_adj: dict[int, list[int]] = {}
    for (a, b) in raw:
        out_adj.setdefault(a, []).append(b)

    def pass_through(n: int) -> bool:
        nb = degree.get(n, set())
        if len(nb) != 2 or n in endpoints:
            return False
        p, q = sorted(nb)
        fwd, bwd = ((p, n) in raw, (n, q) in raw), ((q, n) in raw, (n, p) in raw)
        if fwd[0] != fwd[1] or bwd[0] != bwd[1] or not (fwd[0] or bwd[0]):
            return False
        attrs = {raw[k] for k in ((p, n), (n, q), (q, n), (n, p)) if k in raw}
        return len(attrs) == 1

    keep = {n for n in degree if not pass_through(n)}
    edges: list[tuple[int, int, list[int], float, str, str]] = []
    for (a, b), (speed, cls, name) in raw.items():
        if a not in keep:
            continue
        chain, prev, cur = [a], a, b
        while cur not in keep:
            nxt = [x for x in out_adj.get(cur, []) if x != prev]
            chain.append(cur)
            prev, cur = cur, nxt[0]
        chain.append(cur)
        edges.append((a, cur, chain[1:-1], speed, cls, name))

    # largest strongly connected component (iterative Kosaraju)
    adj: dict[int, list[int]] = {}
    radj: dict[int, list[int]] = {}
    for a, b, *_ in edges:
        if a != b:
            adj.setdefault(a, []).append(b)
            radj.setdefault(b, []).append(a)
    order, seen = [], set()
    for root in adj:
        if root in seen:
            continue
        stack = [(root, iter(adj.get(root, [])))]
        seen.add(root)
        while stack:
            node, it = stack[-1]
            nxt = next((x for x in it if x not in seen), None)
            if nxt is None:
                order.append(node)
                stack.pop()
            else:
                seen.add(nxt)
                stack.append((nxt, iter(adj.get(nxt, []))))
    comp: dict[int, int] = {}
    for root in reversed(order):
        if root in comp:
            continue
        stack = [root]
        comp[root] = root
        while stack:
            u = stack.pop()
            for v in radj.get(u, []):
                if v not in comp:
                    comp[v] = root
                    stack.append(v)
    sizes: dict[int, int] = {}
    for c in comp.values():
        sizes[c] = sizes.get(c, 0) + 1
    if not sizes:
        raise OSMUnavailable("OSM data contains no routable roads")
    big = max(sizes, key=sizes.get)
    members = sorted(n for n, c in comp.items() if c == big)
    remap = {osm: i for i, osm in enumerate(members)}

    net = RoadNetwork()
    for osm in members:
        net.add_node(remap[osm], *nodes[osm])
    names = set()
    for a, b, shape, speed, cls, name in edges:
        if a in remap and b in remap and a != b and (remap[a], remap[b]) not in net.edges:
            net.add_edge(remap[a], remap[b], speed, cls, name, geometry=[nodes[s] for s in shape])
            names.add(name)
    net.version = 0
    lats = [p[0] for p in net.nodes.values()]
    meta = {"source": "osm", "osm_nodes": len(nodes), "osm_ways": len(ways),
            "street_names": sorted(names)[:500], "removed_unreachable_nodes": len(comp) - len(members),
            "extent_m": round(haversine_m(min(lats), 0, max(lats), 0))}
    return net, meta
