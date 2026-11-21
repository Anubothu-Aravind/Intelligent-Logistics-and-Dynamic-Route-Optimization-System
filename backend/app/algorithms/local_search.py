"""Neighbourhood local search.

Intra-route:  2-opt (Croes 1958), Or-opt (Or 1976) – move segments of 1..3 stops
Inter-route:  Relocate and Swap (Savelsbergh 1992) – respecting onboard locks
Speed-up:     Granular neighbourhoods (Toth & Vigo 2003) – inter-route moves only
              place a customer next to one of its k nearest customers
Control:      Variable Neighbourhood Descent (Mladenović & Hansen 1997)
"""
from __future__ import annotations

import time

from .vrp import DEPOT, Instance, Solution, normalize_route, route_cost

EPS = 1e-6


def two_opt(inst: Instance, k: int, seq: list[int]) -> tuple[list[int], float]:
    best = start = route_cost(inst, k, seq)
    improved = True
    while improved:
        improved = False
        n = len(seq)
        for i in range(n - 1):
            for j in range(i + 2, n + 1):
                cand = seq[:i] + seq[i:j][::-1] + seq[j:]
                c = route_cost(inst, k, cand)
                if c + EPS < best:
                    seq, best, improved = cand, c, True
    return seq, start - best


def or_opt(inst: Instance, k: int, seq: list[int]) -> tuple[list[int], float]:
    best = start = route_cost(inst, k, seq)
    improved = True
    while improved:
        improved = False
        for length in (1, 2, 3):
            i = 0
            while i <= len(seq) - length:
                seg = seq[i:i + length]
                rest = seq[:i] + seq[i + length:]
                moved = False
                for j in range(len(rest) + 1):
                    if j == i:
                        continue
                    cand = rest[:j] + seg + rest[j:]
                    c = route_cost(inst, k, cand)
                    if c + EPS < best:
                        seq, best, improved, moved = cand, c, True, True
                        break
                if not moved:
                    i += 1
    return seq, start - best


def _positions(inst: Instance, route: list[int], c: int, nb: dict[int, list[int]]) -> set[int]:
    """Granular insertion positions: next to one of c's nearest neighbours."""
    near = set(nb.get(c, ()))
    pos = {0, len(route)} if len(route) < 3 else set()
    for idx, x in enumerate(route):
        if x in near:
            pos.add(idx)
            pos.add(idx + 1)
    return pos


def relocate(inst: Instance, sol: Solution, k_nb: int) -> float:
    lock = inst.owner_lock()
    nb = inst.neighbours(k_nb)
    costs = [route_cost(inst, k, r) for k, r in enumerate(sol.routes)]
    total = 0.0
    improved = True
    while improved:
        improved = False
        for a in range(len(sol.routes)):
            idx = 0
            while idx < len(sol.routes[a]):
                ra = sol.routes[a]
                c = ra[idx]
                if c == DEPOT or c in lock:
                    idx += 1
                    continue
                reduced = normalize_route(inst, a, ra[:idx] + ra[idx + 1:])
                ca = route_cost(inst, a, reduced)
                best = (EPS, None, None, None)
                for b, rb in enumerate(sol.routes):
                    if b == a:
                        continue
                    for pos in _positions(inst, rb, c, nb):
                        variants = [rb[:pos] + [c] + rb[pos:]]
                        if not inst.vehicles[b].at_depot:
                            variants.append(rb[:pos] + [DEPOT, c] + rb[pos:])
                        for cand in variants:
                            cb = route_cost(inst, b, cand)
                            gain = costs[a] + costs[b] - ca - cb
                            if gain > best[0]:
                                best = (gain, b, cand, cb)
                if best[1] is not None:
                    gain, b, cand, cb = best
                    sol.routes[a], costs[a] = reduced, ca
                    sol.routes[b] = normalize_route(inst, b, cand)
                    costs[b] = route_cost(inst, b, sol.routes[b])
                    total += gain
                    improved = True
                else:
                    idx += 1
    return total


def swap(inst: Instance, sol: Solution, k_nb: int) -> float:
    lock = inst.owner_lock()
    nb = inst.neighbours(k_nb)
    where = {}
    for k, r in enumerate(sol.routes):
        for i, c in enumerate(r):
            if c != DEPOT:
                where[c] = k
    costs = [route_cost(inst, k, r) for k, r in enumerate(sol.routes)]
    total = 0.0
    improved = True
    while improved:
        improved = False
        for ci in list(where):
            if ci in lock:
                continue
            a = where[ci]
            for cj in nb.get(ci, ()):
                b = where.get(cj)
                if b is None or b == a or cj in lock:
                    continue
                ra, rb = sol.routes[a], sol.routes[b]
                i, j = ra.index(ci), rb.index(cj)
                na = ra[:i] + [cj] + ra[i + 1:]
                nb_ = rb[:j] + [ci] + rb[j + 1:]
                ca, cb = route_cost(inst, a, na), route_cost(inst, b, nb_)
                gain = costs[a] + costs[b] - ca - cb
                if gain > EPS:
                    sol.routes[a], sol.routes[b] = na, nb_
                    costs[a], costs[b] = ca, cb
                    where[ci], where[cj] = b, a
                    total += gain
                    improved = True
                    break
    return total


def improve(inst: Instance, sol: Solution, operators: list[str], max_rounds: int,
            time_limit_s: float | None = None, k_nb: int = 12) -> tuple[Solution, dict[str, float]]:
    """Variable Neighbourhood Descent over the selected operators."""
    sol = sol.copy()
    gains = {op: 0.0 for op in operators}
    start = time.perf_counter()
    for _ in range(max_rounds):
        round_gain = 0.0
        for op in operators:
            if time_limit_s and time.perf_counter() - start > time_limit_s:
                return sol, gains
            if op in ("two_opt", "or_opt"):
                fn = two_opt if op == "two_opt" else or_opt
                g = 0.0
                for k, r in enumerate(sol.routes):
                    if len(r) > 1:
                        sol.routes[k], gk = fn(inst, k, r)
                        g += gk
            elif op == "relocate":
                g = relocate(inst, sol, k_nb)
            elif op == "swap":
                g = swap(inst, sol, k_nb)
            else:
                raise ValueError(f"Unknown local-search operator '{op}'")
            gains[op] += g
            round_gain += g
        if round_gain <= EPS:
            break
    return sol, gains
