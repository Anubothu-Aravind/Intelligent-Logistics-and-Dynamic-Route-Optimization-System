"""Travel-time / distance matrices between stops.

Built with one-to-all Dijkstra from every distinct stop node (|S| runs of
Dijkstra are cheaper than Floyd–Warshall when |S| << |V|). The fastest
(traffic-aware) path is used and its physical length is accumulated alongside.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .graph import INF, RoadNetwork
from .shortest_path import _reconstruct, dijkstra_tree


@dataclass
class StopMatrix:
    nodes: list[int]                        # graph node of every matrix point
    time: list[list[float]]                 # minutes
    dist: list[list[float]]                 # metres
    trees: dict[int, dict[int, int]] = field(default_factory=dict)   # source node -> prev
    graph_version: int = 0
    runtime_ms: float = 0.0
    dijkstra_runs: int = 0

    def path(self, a: int, b: int) -> list[int]:
        """Node path between matrix points a and b."""
        src, dst = self.nodes[a], self.nodes[b]
        if src == dst:
            return [src]
        return _reconstruct(self.trees[src], src, dst)


def build_matrix(graph: RoadNetwork, point_nodes: list[int]) -> StopMatrix:
    start = time.perf_counter()
    unique = list(dict.fromkeys(point_nodes))
    trees, times, lengths = {}, {}, {}
    for node in unique:
        dist, prev, length, _ = dijkstra_tree(graph, node, "time")
        trees[node], times[node], lengths[node] = prev, dist, length
    n = len(point_nodes)
    tm = [[0.0] * n for _ in range(n)]
    dm = [[0.0] * n for _ in range(n)]
    for i, a in enumerate(point_nodes):
        ta, la = times[a], lengths[a]
        for j, b in enumerate(point_nodes):
            if i != j:
                tm[i][j] = ta.get(b, INF)
                dm[i][j] = la.get(b, INF)
    return StopMatrix(point_nodes, tm, dm, trees, graph.version,
                      (time.perf_counter() - start) * 1000, len(unique))
