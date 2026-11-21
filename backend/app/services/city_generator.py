"""Procedural city generator: a jittered street grid with arterials, diagonal
avenues and randomly removed segments – all parameters from settings.yaml."""
from __future__ import annotations

import random

from faker import Faker

from app.algorithms.graph import RoadNetwork
from app.core.geo import offset


def _unique_names(faker: Faker, count: int, suffixes: list[str]) -> list[str]:
    names, seen = [], set()
    while len(names) < count:
        base = faker.last_name()
        if base in seen:
            continue
        seen.add(base)
        names.append(f"{base} {suffixes[len(names) % len(suffixes)]}")
    return names


class MapUnavailable(RuntimeError):
    """The real road network is not available (not downloaded yet / download failed)."""


def generate_city(cfg: dict, seed: int, rows: int | None = None, cols: int | None = None) -> tuple[RoadNetwork, dict]:
    rng = random.Random(seed)
    faker = Faker(cfg["name_locale"])
    faker.seed_instance(seed)
    R = rows or int(cfg["grid_rows"])
    C = cols or int(cfg["grid_cols"])
    block = float(cfg["block_size_m"])
    jitter = float(cfg["jitter_ratio"]) * block
    speeds = cfg["speeds_kmh"]
    every = max(1, int(cfg["arterial_every"]))
    lat0, lon0 = float(cfg["center_lat"]), float(cfg["center_lon"])

    net = RoadNetwork()
    nid = lambda r, c: r * C + c  # noqa: E731
    for r in range(R):
        for c in range(C):
            north = (r - (R - 1) / 2) * block + rng.uniform(-jitter, jitter)
            east = (c - (C - 1) / 2) * block + rng.uniform(-jitter, jitter)
            net.add_node(nid(r, c), *offset(lat0, lon0, north, east))

    row_names = _unique_names(faker, R, ["Road", "Street", "Main Road"])
    col_names = _unique_names(faker, C, ["Avenue", "Cross", "Lane"])
    segments: list[tuple[int, int, str, str]] = []
    for r in range(R):
        for c in range(C):
            if c + 1 < C:
                cls = "arterial" if r % every == 0 else "local"
                segments.append((nid(r, c), nid(r, c + 1), cls, row_names[r]))
            if r + 1 < R:
                cls = "arterial" if c % every == 0 else "local"
                segments.append((nid(r, c), nid(r + 1, c), cls, col_names[c]))

    diag_names = _unique_names(faker, int(cfg["diagonal_count"]), ["Highway", "Ring Road", "Expressway"])
    for d, name in enumerate(diag_names):
        r, c = rng.randrange(R // 3), rng.randrange(C)
        step = 1 if c < C / 2 else -1
        while r + 1 < R and 0 <= c + step < C:
            segments.append((nid(r, c), nid(r + 1, c + step), "diagonal", name))
            r, c = r + 1, c + step

    for u, v, cls, name in segments:
        net.add_edge(u, v, float(speeds[cls]), cls, name)
        net.add_edge(v, u, float(speeds[cls]), cls, name)

    # remove random local segments / make one-way while keeping strong connectivity
    drop_p, oneway_p = float(cfg["edge_drop_probability"]), float(cfg["one_way_probability"])
    root = next(iter(net.nodes))
    for u, v, cls, _ in segments:
        if cls != "local":
            continue
        roll = rng.random()
        if roll < drop_p:
            targets = [(u, v), (v, u)]
        elif roll < drop_p + oneway_p:
            targets = [(v, u)]
        else:
            continue
        for key in targets:
            net.edges[key].closed = True
        if net.is_strongly_connected_from(root):
            for a, b in targets:
                e = net.edges.pop((a, b))
                net.adj[a].remove(e)
                net.radj[b].remove(e)
        else:
            for key in targets:
                net.edges[key].closed = False
    net.version = 0
    meta = {"rows": R, "cols": C, "block_size_m": block, "center": [lat0, lon0],
            "street_names": sorted(set(row_names + col_names + diag_names))}
    return net, meta


def street_of_node(net: RoadNetwork, node: int) -> str:
    edges = net.adj.get(node) or []
    major = sorted(edges, key=lambda e: {"diagonal": 0, "arterial": 1}.get(e.road_class, 2))
    return major[0].name if major else "Unnamed Road"


def load_network(cfg: dict, seed: int, data_dir, force_download: bool = False) -> tuple[RoadNetwork, dict]:
    """Real OSM roads when configured (cached), otherwise / on failure the generated city.

    The returned meta always states the actual source and, for a fallback, why."""
    from pathlib import Path

    from app.services import osm_loader

    if cfg.get("source", "synthetic") == "osm":
        try:
            data, origin = osm_loader.fetch_overpass(cfg["osm"], float(cfg["center_lat"]), float(cfg["center_lon"]),
                                                     Path(data_dir) / cfg["osm"]["cache_dir"].removeprefix("data/"),
                                                     force=force_download)
            net, meta = osm_loader.build_network(data, cfg["osm"])
            meta.update(origin=origin, center=[float(cfg["center_lat"]), float(cfg["center_lon"])],
                        radius_m=cfg["osm"]["radius_m"], city=cfg.get("name"))
            return net, meta
        except Exception as exc:  # unreachable API, bad data …
            raise MapUnavailable(
                f"The {cfg.get('name', 'city')} road network is not available: {str(exc)[:300]}. "
                f"Run ./set-up.sh with an internet connection to download it (one time)."
            ) from exc
    net, meta = generate_city(cfg, seed)
    meta["source"] = "synthetic"
    return net, meta


def graph_signature(net: RoadNetwork) -> str:
    import hashlib
    h = hashlib.sha1()
    for n in sorted(net.nodes)[:: max(1, len(net.nodes) // 200)]:
        h.update(f"{n}:{net.nodes[n][0]:.6f},{net.nodes[n][1]:.6f};".encode())
    h.update(f"{len(net.nodes)}/{len(net.edges)}".encode())
    return h.hexdigest()[:16]
