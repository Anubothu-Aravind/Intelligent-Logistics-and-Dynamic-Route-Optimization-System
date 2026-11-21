"""Route-construction heuristics for the CVRPTW.

* FIFO baseline            – orders served in arrival order (a "basic" dispatcher)
* Nearest Neighbour        – greedy, Rosenkrantz/Stearns/Lewis (1977) adapted to CVRP
* Clarke–Wright Savings    – parallel savings algorithm (Clarke & Wright 1964)
* Sweep                    – polar-angle clustering (Gillett & Miller 1974)
* Regret-2 insertion       – parallel regret insertion (Potvin & Rousseau 1993)
"""
from __future__ import annotations

from .vrp import DEPOT, Instance, Solution, best_insertion, route_cost


def _vehicle_order(inst: Instance) -> list[int]:
    return sorted(range(len(inst.vehicles)), key=lambda k: -inst.vehicles[k].capacity)


def _load(inst: Instance, seq: list[int]) -> float:
    return sum(inst.demand[c] for c in seq if c != DEPOT)


# ------------------------------------------------------------------- FIFO baseline
def fifo(inst: Instance, arrival_order: list[int] | None = None) -> Solution:
    order = arrival_order or list(inst.customers)
    routes = [[] for _ in inst.vehicles]
    unassigned = []
    vk = _vehicle_order(inst)
    idx = 0
    for c in order:
        placed = False
        while idx < len(vk):
            k = vk[idx]
            if _load(inst, routes[k]) + inst.demand[c] <= inst.vehicles[k].capacity:
                routes[k].append(c)
                placed = True
                break
            idx += 1
        if not placed:
            unassigned.append(c)
    return Solution(routes, unassigned, "fifo")


# --------------------------------------------------------------- Nearest Neighbour
def nearest_neighbour(inst: Instance) -> Solution:
    remaining = set(inst.customers)
    routes = [[] for _ in inst.vehicles]
    for k in _vehicle_order(inst):
        v = inst.vehicles[k]
        pos, load, t = v.start_point, 0.0, v.start_time
        while remaining:
            best, best_score = None, float("inf")
            for c in remaining:
                if load + inst.demand[c] > v.capacity:
                    continue
                arrive = max(t + inst.time[pos][c], inst.ready[c])
                # nearest in travel time, nudged towards urgent deadlines
                score = inst.time[pos][c] + 0.1 * max(0.0, inst.deadline[c] - arrive)
                if score < best_score:
                    best, best_score = c, score
            if best is None:
                break
            routes[k].append(best)
            remaining.discard(best)
            load += inst.demand[best]
            t = max(t + inst.time[pos][best], inst.ready[best]) + inst.service[best]
            pos = best
    sol = Solution(routes, sorted(remaining), "nearest_neighbour")
    return regret_insertion(inst, sol)


# ------------------------------------------------------------ Clarke–Wright Savings
def clarke_wright(inst: Instance) -> Solution:
    cap_max = max(v.capacity for v in inst.vehicles)
    D = inst.dist
    route_of = {c: [c] for c in inst.customers}
    load = {c: inst.demand[c] for c in inst.customers}
    savings = []
    cs = inst.customers
    for a_i, i in enumerate(cs):
        for j in cs[a_i + 1:]:
            s = D[DEPOT][i] + D[DEPOT][j] - D[i][j]
            savings.append((s, i, j))
    savings.sort(reverse=True)
    for s, i, j in savings:
        if s <= 0:
            break
        ri, rj = route_of[i], route_of[j]
        if ri is rj:
            continue
        li, lj = load[ri[0]], load[rj[0]]
        if li + lj > cap_max:
            continue
        # i and j must be route end-points to be merged
        if ri[-1] == i and rj[0] == j:
            merged = ri + rj
        elif ri[0] == i and rj[-1] == j:
            merged = rj + ri
        elif ri[0] == i and rj[0] == j:
            merged = list(reversed(ri)) + rj
        elif ri[-1] == i and rj[-1] == j:
            merged = ri + list(reversed(rj))
        else:
            continue
        total = li + lj
        for c in merged:
            route_of[c] = merged
        load[merged[0]] = total
    unique, seen = [], set()
    for r in route_of.values():
        if id(r) not in seen:
            seen.add(id(r))
            unique.append(r)
    unique.sort(key=lambda r: -_load(inst, r))
    routes = [[] for _ in inst.vehicles]
    free = _vehicle_order(inst)
    unassigned: list[int] = []
    for r in unique:
        need = _load(inst, r)
        fit = [k for k in free if inst.vehicles[k].capacity >= need]
        if fit:
            k = min(fit, key=lambda k: inst.vehicles[k].capacity)   # best fit
            routes[k] = r
            free.remove(k)
        else:
            unassigned.extend(r)
    sol = Solution(routes, unassigned, "clarke_wright")
    return regret_insertion(inst, sol)


# ---------------------------------------------------------------------------- Sweep
def sweep(inst: Instance) -> Solution:
    order = sorted(inst.customers, key=lambda c: inst.angle[c])
    # start the sweep after the largest angular gap to avoid splitting a cluster
    if len(order) > 2:
        gaps = [(inst.angle[order[(i + 1) % len(order)]] - inst.angle[order[i]]) % 6.283185
                for i in range(len(order))]
        cut = max(range(len(gaps)), key=gaps.__getitem__) + 1
        order = order[cut:] + order[:cut]
    routes = [[] for _ in inst.vehicles]
    vk = _vehicle_order(inst)
    idx, unassigned = 0, []
    for c in order:
        while idx < len(vk) and _load(inst, routes[vk[idx]]) + inst.demand[c] > inst.vehicles[vk[idx]].capacity:
            idx += 1
        if idx >= len(vk):
            unassigned.append(c)
        else:
            routes[vk[idx]].append(c)
    # sequence each cluster with nearest neighbour
    for k, r in enumerate(routes):
        if len(r) < 2:
            continue
        pos, left, seq = inst.vehicles[k].start_point, set(r), []
        while left:
            nxt = min(left, key=lambda c: inst.time[pos][c])
            seq.append(nxt)
            left.discard(nxt)
            pos = nxt
        routes[k] = seq
    sol = Solution(routes, unassigned, "sweep")
    return regret_insertion(inst, sol)


# --------------------------------------------------------------- Regret insertion
def regret_insertion(inst: Instance, sol: Solution, explain: list | None = None) -> Solution:
    """Insert every unassigned customer; the one with the largest regret goes first.

    Incremental: insertion options are cached per (customer, route); after an
    insertion only the modified route is re-evaluated (O(p) instead of O(p*m)
    best_insertion calls per step)."""
    lock = inst.owner_lock()
    pending = list(sol.unassigned)
    sol.unassigned = []
    m = len(sol.routes)

    def option(c: int, k: int):
        if c in lock and lock[c] != k:
            return None
        return best_insertion(inst, k, sol.routes[k], c)

    cache = {c: {k: option(c, k) for k in range(m)} for c in pending}
    while pending:
        best_choice = None
        for c in pending:
            # ties (e.g. several idle vehicles) go to the vehicle with the least work, not to index 0
            options = sorted(((v[0], k, v[1]) for k, v in cache[c].items() if v is not None),
                             key=lambda o: (round(o[0], 6), len(sol.routes[o[1]])))
            if not options:
                continue
            regret = (options[1][0] - options[0][0]) if len(options) > 1 else float("inf")
            if best_choice is None or regret > best_choice[0]:
                best_choice = (regret, c, options)
        if best_choice is None:
            sol.unassigned.extend(pending)
            break
        _, c, options = best_choice
        delta, k, seq = options[0]
        sol.routes[k] = seq
        pending.remove(c)
        del cache[c]
        for other in pending:
            cache[other][k] = option(other, k)
        if explain is not None:
            explain.append({
                "customer": c, "chosen_vehicle": k, "delta_cost": delta,
                "candidates": [{"vehicle": kk, "delta_cost": dd} for dd, kk, _ in options[:5]],
            })
    return sol


CONSTRUCTIONS = {
    "fifo": fifo,
    "nearest_neighbour": nearest_neighbour,
    "clarke_wright": clarke_wright,
    "sweep": sweep,
}


def total(inst: Instance, sol: Solution) -> float:
    return sum(route_cost(inst, k, r) for k, r in enumerate(sol.routes))
