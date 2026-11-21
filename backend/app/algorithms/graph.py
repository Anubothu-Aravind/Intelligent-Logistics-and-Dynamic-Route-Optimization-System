"""Weighted directed road graph G = (V, E) with mutable traffic state.

w(u, v) is either the length of a street segment (metric="distance") or its
traffic-aware travel time (metric="time").
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.core.geo import haversine_m

INF = math.inf


def _heading(la: float, lo: float, lb: float, lob: float) -> float:
    return math.degrees(math.atan2((lob - lo) * math.cos(math.radians(la)), lb - la)) % 360


@dataclass
class Edge:
    u: int
    v: int
    length_m: float
    speed_kmh: float
    road_class: str
    name: str
    traffic: float = 1.0          # multiplier >= 1 (congestion)
    closed: bool = False
    geometry: list[tuple[float, float]] | None = None   # intermediate shape points (real roads)

    @property
    def free_flow_min(self) -> float:
        return self.length_m / 1000.0 / self.speed_kmh * 60.0

    @property
    def travel_min(self) -> float:
        return INF if self.closed else self.free_flow_min * self.traffic

    def weight(self, metric: str) -> float:
        if self.closed:
            return INF
        return self.length_m if metric == "distance" else self.travel_min


@dataclass
class RoadNetwork:
    nodes: dict[int, tuple[float, float]] = field(default_factory=dict)
    adj: dict[int, list[Edge]] = field(default_factory=dict)
    radj: dict[int, list[Edge]] = field(default_factory=dict)
    edges: dict[tuple[int, int], Edge] = field(default_factory=dict)
    version: int = 0               # incremented on every traffic/closure change

    # ------------------------------------------------------------------ build
    def add_node(self, node_id: int, lat: float, lon: float) -> None:
        self.nodes[node_id] = (lat, lon)
        self.adj.setdefault(node_id, [])
        self.radj.setdefault(node_id, [])

    def add_edge(self, u: int, v: int, speed_kmh: float, road_class: str, name: str,
                 geometry: list[tuple[float, float]] | None = None, length_m: float | None = None) -> Edge:
        lat1, lon1 = self.nodes[u]
        lat2, lon2 = self.nodes[v]
        if length_m is None:
            pts = [(lat1, lon1), *(geometry or []), (lat2, lon2)]
            length_m = sum(haversine_m(*a, *b) for a, b in zip(pts, pts[1:]))
        edge = Edge(u, v, length_m, speed_kmh, road_class, name, geometry=geometry or None)
        self.adj[u].append(edge)
        self.radj[v].append(edge)
        self.edges[(u, v)] = edge
        self._max_speed = None
        return edge

    # ---------------------------------------------------------------- queries
    @property
    def max_speed_kmh(self) -> float:
        if getattr(self, "_max_speed", None) is None:
            self._max_speed = max((e.speed_kmh for e in self.edges.values()), default=1.0)
        return self._max_speed

    def _xy(self) -> dict[int, tuple[float, float]]:
        """Local equirectangular projection (metres), computed once."""
        if getattr(self, "_proj", None) is None or len(self._proj) != len(self.nodes):
            lat0 = sum(p[0] for p in self.nodes.values()) / len(self.nodes)
            k = math.cos(math.radians(lat0)) * 111_319.49
            self._k_lon = k
            self._proj = {n: (lon * k, lat * 111_319.49) for n, (lat, lon) in self.nodes.items()}
        return self._proj

    def heuristic(self, a: int, b: int, metric: str) -> float:
        """Admissible A* heuristic: straight-line distance (or its travel time at the
        maximum speed limit). Scaled by 0.995 to absorb projection error."""
        xy = self._xy()
        (x1, y1), (x2, y2) = xy[a], xy[b]
        d = math.hypot(x1 - x2, y1 - y2) * 0.995
        return d if metric == "distance" else d * 0.06 / self.max_speed_kmh

    # ------------------------------------------------------- spatial index
    _CELL_M = 250.0

    def _grid(self) -> dict[tuple[int, int], list[int]]:
        if getattr(self, "_grid_idx", None) is None or self._grid_n != len(self.nodes):
            xy = self._xy()
            grid: dict[tuple[int, int], list[int]] = {}
            for n, (x, y) in xy.items():
                grid.setdefault((int(x // self._CELL_M), int(y // self._CELL_M)), []).append(n)
            self._grid_idx, self._grid_n = grid, len(self.nodes)
        return self._grid_idx

    def _project(self, lat: float, lon: float) -> tuple[float, float]:
        self._xy()
        return lon * self._k_lon, lat * 111_319.49

    def nearest_node(self, lat: float, lon: float) -> int:
        """Nearest intersection using a uniform grid index (expanding ring search)."""
        grid = self._grid()
        x, y = self._project(lat, lon)
        cx, cy = int(x // self._CELL_M), int(y // self._CELL_M)
        best, best_d = None, math.inf
        for ring in range(0, 400):
            for gx in range(cx - ring, cx + ring + 1):
                for gy in (range(cy - ring, cy + ring + 1) if gx in (cx - ring, cx + ring) else (cy - ring, cy + ring)):
                    for n in grid.get((gx, gy), ()):
                        d = haversine_m(lat, lon, *self.nodes[n])
                        if d < best_d:
                            best, best_d = n, d
            if best is not None and best_d <= ring * self._CELL_M:
                return best
        return best if best is not None else min(self.nodes, key=lambda n: haversine_m(lat, lon, *self.nodes[n]))

    def nodes_within(self, lat: float, lon: float, radius_m: float) -> set[int]:
        grid = self._grid()
        x, y = self._project(lat, lon)
        r = int(radius_m // self._CELL_M) + 1
        cx, cy = int(x // self._CELL_M), int(y // self._CELL_M)
        out = set()
        for gx in range(cx - r, cx + r + 1):
            for gy in range(cy - r, cy + r + 1):
                for n in grid.get((gx, gy), ()):
                    if haversine_m(lat, lon, *self.nodes[n]) <= radius_m:
                        out.add(n)
        return out

    # ---------------------------------------------------------- geometry
    def edge_points(self, e: Edge) -> list[tuple[float, float]]:
        return [self.nodes[e.u], *(e.geometry or []), self.nodes[e.v]]

    def path_coords(self, path: list[int]) -> list[list[float]]:
        """Polyline that follows the road shape of every edge on the path."""
        if not path:
            return []
        out = [list(self.nodes[path[0]])]
        for a, b in zip(path, path[1:]):
            e = self.edges.get((a, b))
            for p in (e.geometry or []) if e else []:
                out.append(list(p))
            out.append(list(self.nodes[b]))
        return out

    def point_along(self, e: Edge, f: float) -> tuple[float, float, float]:
        """(lat, lon, heading_deg) at fraction f of the edge's length."""
        pts = self.edge_points(e)
        f = min(1.0, max(0.0, f))
        if len(pts) == 2:
            (la, lo), (lb, lob) = pts
            return la + (lb - la) * f, lo + (lob - lo) * f, _heading(la, lo, lb, lob)
        seg = [haversine_m(*a, *b) for a, b in zip(pts, pts[1:])]
        target, acc = f * sum(seg), 0.0
        for (a, b), L in zip(zip(pts, pts[1:]), seg):
            if acc + L >= target or L == seg[-1] and acc + L >= target - 1e-6:
                g = 0.0 if L == 0 else (target - acc) / L
                return a[0] + (b[0] - a[0]) * g, a[1] + (b[1] - a[1]) * g, _heading(*a, *b)
            acc += L
        a, b = pts[-2], pts[-1]
        return b[0], b[1], _heading(*a, *b)

    def timed_coords(self, path: list[int], times: list[float]) -> list[list[float]]:
        """[[lat, lon, t], ...] following road shape; shape points get distance-interpolated times."""
        if not path:
            return []
        out = [[*self.nodes[path[0]], times[0]]]
        for i, (a, b) in enumerate(zip(path, path[1:])):
            e = self.edges.get((a, b))
            t0, t1 = times[i], times[i + 1]
            if e and e.geometry:
                pts = self.edge_points(e)
                seg = [haversine_m(*p, *q) for p, q in zip(pts, pts[1:])]
                total, acc = sum(seg) or 1.0, 0.0
                for p, L in zip(pts[1:-1], seg):
                    acc += L
                    out.append([p[0], p[1], t0 + (t1 - t0) * acc / total])
            out.append([*self.nodes[b], t1])
        return out

    def path_stats(self, path: list[int]) -> tuple[float, float]:
        """(distance_m, time_min) along a node path using current traffic."""
        dist = time = 0.0
        for a, b in zip(path, path[1:]):
            e = self.edges[(a, b)]
            dist += e.length_m
            time += e.travel_min
        return dist, time

    # ---------------------------------------------------------- dynamic state
    def set_congestion(self, nodes: set[int], factor: float) -> list[Edge]:
        touched = [e for e in self.edges.values() if e.u in nodes and e.v in nodes]
        for e in touched:
            e.traffic = max(e.traffic, factor)
        self.version += 1
        return touched

    def set_closed(self, u: int, v: int, closed: bool, both_directions: bool = True) -> list[Edge]:
        touched = []
        for key in ((u, v), (v, u)) if both_directions else ((u, v),):
            if key in self.edges:
                self.edges[key].closed = closed
                touched.append(self.edges[key])
        self.version += 1
        return touched

    def reset_traffic(self) -> None:
        for e in self.edges.values():
            e.traffic = 1.0
            e.closed = False
        self.version += 1

    def is_strongly_connected_from(self, root: int) -> bool:
        seen, stack = {root}, [root]
        while stack:
            u = stack.pop()
            for e in self.adj[u]:
                if not e.closed and e.v not in seen:
                    seen.add(e.v)
                    stack.append(e.v)
        return len(seen) == len(self.nodes)
