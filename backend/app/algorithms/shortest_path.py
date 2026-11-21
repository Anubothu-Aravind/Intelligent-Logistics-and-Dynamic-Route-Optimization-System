"""Shortest-path algorithms implemented from scratch.

* Dijkstra (1959)                         – binary-heap label setting, O((V+E) log V)
* A* search (Hart, Nilsson & Raphael 1968) – Dijkstra guided by an admissible heuristic
* Bidirectional Dijkstra (Pohl 1971)       – two simultaneous searches meeting in the middle
* Floyd–Warshall (1962)                    – all-pairs dynamic programming, O(V^3)
* Yen's K-shortest loopless paths (1971)   – alternative routes for the operator
"""
from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field

from .graph import INF, RoadNetwork


@dataclass
class PathResult:
    algorithm: str
    source: int
    target: int
    nodes: list[int] = field(default_factory=list)
    cost: float = INF
    distance_m: float = 0.0
    time_min: float = 0.0
    expanded: int = 0
    runtime_ms: float = 0.0

    @property
    def found(self) -> bool:
        return bool(self.nodes)

    def to_dict(self, graph: RoadNetwork | None = None) -> dict:
        data = {
            "algorithm": self.algorithm, "source": self.source, "target": self.target,
            "found": self.found, "cost": None if self.cost == INF else round(self.cost, 4),
            "distance_m": round(self.distance_m, 1), "time_min": round(self.time_min, 2),
            "expanded": self.expanded, "runtime_ms": round(self.runtime_ms, 3),
            "hops": max(len(self.nodes) - 1, 0), "nodes": self.nodes,
        }
        if graph is not None:
            data["coords"] = graph.path_coords(self.nodes)
        return data


def _reconstruct(prev: dict[int, int], source: int, target: int) -> list[int]:
    if target != source and target not in prev:
        return []
    path = [target]
    while path[-1] != source:
        path.append(prev[path[-1]])
    path.reverse()
    return path


def _finish(res: PathResult, graph: RoadNetwork, prev, start: float) -> PathResult:
    res.nodes = _reconstruct(prev, res.source, res.target) if res.cost < INF else []
    if res.nodes:
        res.distance_m, res.time_min = graph.path_stats(res.nodes)
    res.runtime_ms = (time.perf_counter() - start) * 1000
    return res


# --------------------------------------------------------------------- Dijkstra
def dijkstra_tree(graph: RoadNetwork, source: int, metric: str = "time",
                  banned_edges: set | None = None, banned_nodes: set | None = None):
    """One-to-all Dijkstra. Returns (dist, prev, length_along_path, expanded)."""
    dist = {source: 0.0}
    length = {source: 0.0}
    prev: dict[int, int] = {}
    done: set[int] = set()
    heap = [(0.0, source)]
    expanded = 0
    while heap:
        d, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        expanded += 1
        for e in graph.adj[u]:
            if banned_edges and (e.u, e.v) in banned_edges:
                continue
            if banned_nodes and e.v in banned_nodes:
                continue
            w = e.weight(metric)
            if w == INF:
                continue
            nd = d + w
            if nd < dist.get(e.v, INF):
                dist[e.v] = nd
                length[e.v] = length[u] + e.length_m
                prev[e.v] = u
                heapq.heappush(heap, (nd, e.v))
    return dist, prev, length, expanded


def dijkstra(graph: RoadNetwork, source: int, target: int, metric: str = "time",
             banned_edges: set | None = None, banned_nodes: set | None = None,
             trace: list | None = None) -> PathResult:
    start = time.perf_counter()
    res = PathResult("dijkstra", source, target)
    dist = {source: 0.0}
    prev: dict[int, int] = {}
    done: set[int] = set()
    heap = [(0.0, source)]
    while heap:
        d, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        res.expanded += 1
        if trace is not None:
            trace.append(u)
        if u == target:
            res.cost = d
            break
        for e in graph.adj[u]:
            if banned_edges and (e.u, e.v) in banned_edges:
                continue
            if banned_nodes and e.v in banned_nodes:
                continue
            w = e.weight(metric)
            if w == INF:
                continue
            nd = d + w
            if nd < dist.get(e.v, INF):
                dist[e.v] = nd
                prev[e.v] = u
                heapq.heappush(heap, (nd, e.v))
    return _finish(res, graph, prev, start)


# ---------------------------------------------------------------------------- A*
def astar(graph: RoadNetwork, source: int, target: int, metric: str = "time",
          trace: list | None = None) -> PathResult:
    start = time.perf_counter()
    res = PathResult("astar", source, target)
    g = {source: 0.0}
    prev: dict[int, int] = {}
    closed: set[int] = set()
    heap = [(graph.heuristic(source, target, metric), 0.0, source)]
    while heap:
        _, gu, u = heapq.heappop(heap)
        if u in closed:
            continue
        closed.add(u)
        res.expanded += 1
        if trace is not None:
            trace.append(u)
        if u == target:
            res.cost = gu
            break
        for e in graph.adj[u]:
            w = e.weight(metric)
            if w == INF or e.v in closed:
                continue
            ng = gu + w
            if ng < g.get(e.v, INF):
                g[e.v] = ng
                prev[e.v] = u
                heapq.heappush(heap, (ng + graph.heuristic(e.v, target, metric), ng, e.v))
    return _finish(res, graph, prev, start)


# ----------------------------------------------------------- Bidirectional Dijkstra
def bidirectional_dijkstra(graph: RoadNetwork, source: int, target: int,
                           metric: str = "time", trace: list | None = None) -> PathResult:
    start = time.perf_counter()
    res = PathResult("bidirectional_dijkstra", source, target)
    if source == target:
        res.cost, res.nodes = 0.0, [source]
        res.runtime_ms = (time.perf_counter() - start) * 1000
        return res
    dist = [{source: 0.0}, {target: 0.0}]
    prev: list[dict[int, int]] = [{}, {}]
    done: list[set[int]] = [set(), set()]
    heaps = [[(0.0, source)], [(0.0, target)]]
    best, meet = INF, None
    while heaps[0] and heaps[1]:
        if heaps[0][0][0] + heaps[1][0][0] >= best:
            break
        side = 0 if heaps[0][0][0] <= heaps[1][0][0] else 1
        d, u = heapq.heappop(heaps[side])
        if u in done[side]:
            continue
        done[side].add(u)
        res.expanded += 1
        if trace is not None:
            trace.append(u if side == 0 else -u - 1)      # negative = backward search
        edges = graph.adj[u] if side == 0 else graph.radj[u]
        for e in edges:
            nxt = e.v if side == 0 else e.u
            w = e.weight(metric)
            if w == INF:
                continue
            nd = d + w
            if nd < dist[side].get(nxt, INF):
                dist[side][nxt] = nd
                prev[side][nxt] = u
                heapq.heappush(heaps[side], (nd, nxt))
            other = dist[1 - side].get(nxt)
            if other is not None and nd + other < best:
                best, meet = nd + other, nxt
    if meet is not None:
        res.cost = best
        forward = _reconstruct(prev[0], source, meet)
        node, backward = meet, []
        while node != target:
            node = prev[1][node]
            backward.append(node)
        res.nodes = forward + backward
        res.distance_m, res.time_min = graph.path_stats(res.nodes)
    res.runtime_ms = (time.perf_counter() - start) * 1000
    return res


# ------------------------------------------------------------------ Floyd–Warshall
def floyd_warshall(graph: RoadNetwork, metric: str = "time"):
    """All-pairs shortest paths. Returns (index, dist matrix, next-hop matrix, runtime_ms)."""
    start = time.perf_counter()
    ids = sorted(graph.nodes)
    index = {n: i for i, n in enumerate(ids)}
    n = len(ids)
    dist = [[INF] * n for _ in range(n)]
    nxt = [[-1] * n for _ in range(n)]
    for i in range(n):
        dist[i][i], nxt[i][i] = 0.0, i
    for e in graph.edges.values():
        w = e.weight(metric)
        i, j = index[e.u], index[e.v]
        if w < dist[i][j]:
            dist[i][j], nxt[i][j] = w, j
    for k in range(n):
        dk = dist[k]
        for i in range(n):
            dik = dist[i][k]
            if dik == INF:
                continue
            di, ni = dist[i], nxt[i]
            nik = ni[k]
            for j in range(n):
                cand = dik + dk[j]
                if cand < di[j]:
                    di[j], ni[j] = cand, nik
    return index, dist, nxt, (time.perf_counter() - start) * 1000


def floyd_path(ids_index: dict[int, int], nxt, source: int, target: int) -> list[int]:
    ids = {i: n for n, i in ids_index.items()}
    i, j = ids_index[source], ids_index[target]
    if nxt[i][j] == -1:
        return []
    path = [i]
    while i != j:
        i = nxt[i][j]
        path.append(i)
    return [ids[p] for p in path]


# --------------------------------------------------------------- Yen's K-shortest
def yen_k_shortest(graph: RoadNetwork, source: int, target: int, k: int,
                   metric: str = "time") -> list[PathResult]:
    first = dijkstra(graph, source, target, metric)
    if not first.found:
        return []
    paths = [first]
    candidates: list[tuple[float, int, list[int]]] = []
    seen = {tuple(first.nodes)}
    counter = 0
    for _ in range(1, k):
        last = paths[-1].nodes
        for i in range(len(last) - 1):
            spur, root = last[i], last[: i + 1]
            banned_edges = {(p.nodes[i], p.nodes[i + 1]) for p in paths
                            if len(p.nodes) > i + 1 and p.nodes[: i + 1] == root}
            banned_nodes = set(root[:-1])
            spur_res = dijkstra(graph, spur, target, metric, banned_edges, banned_nodes)
            if not spur_res.found:
                continue
            total = root[:-1] + spur_res.nodes
            if tuple(total) in seen:
                continue
            seen.add(tuple(total))
            cost = sum(graph.edges[(a, b)].weight(metric) for a, b in zip(total, total[1:]))
            counter += 1
            heapq.heappush(candidates, (cost, counter, total))
        if not candidates:
            break
        cost, _, nodes = heapq.heappop(candidates)
        res = PathResult("yen", source, target, nodes, cost)
        res.distance_m, res.time_min = graph.path_stats(nodes)
        paths.append(res)
    return paths


POINT_TO_POINT = {
    "dijkstra": dijkstra,
    "astar": astar,
    "bidirectional_dijkstra": bidirectional_dijkstra,
}


def shortest_path(graph: RoadNetwork, source: int, target: int, algorithm: str,
                  metric: str = "time") -> PathResult:
    try:
        fn = POINT_TO_POINT[algorithm]
    except KeyError as exc:
        raise ValueError(f"Unknown shortest-path algorithm '{algorithm}'") from exc
    return fn(graph, source, target, metric)
