"""Genetic Algorithm for the CVRPTW (memetic variant, after Prins 2004).

Chromosome : giant tour = permutation of all customers (no trip delimiters)
Decoding   : Prins' Split procedure – optimal partition of the giant tour into
             capacity-feasible trips via shortest path on an auxiliary DAG
Selection  : k-tournament
Crossover  : Order Crossover OX (Davis 1985)
Mutation   : swap or inversion
Elitism    : best `elitism` individuals are copied unchanged
Education  : local search (2-opt/Or-opt/Relocate/Swap) applied to the final best
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass

from .local_search import improve
from .vrp import DEPOT, Instance, Solution, solution_cost


@dataclass
class GAParams:
    population_size: int
    generations: int
    tournament_size: int
    crossover_rate: float
    mutation_rate: float
    elitism: int
    time_limit_s: float
    local_search_on_best: bool
    seed: int

    @classmethod
    def from_config(cls, cfg: dict, seed: int, overrides: dict | None = None) -> "GAParams":
        c = dict(cfg)
        c.update({k: v for k, v in (overrides or {}).items() if v is not None})
        return cls(int(c["population_size"]), int(c["generations"]), int(c["tournament_size"]),
                   float(c["crossover_rate"]), float(c["mutation_rate"]), int(c["elitism"]),
                   float(c["time_limit_s"]), bool(c["local_search_on_best"]), seed)


def split(inst: Instance, tour: list[int], capacity: float, start_time: float) -> list[list[int]]:
    """Prins' Split: O(n * L) Bellman relaxation on the auxiliary DAG."""
    T, D, w = inst.time, inst.dist, inst.weights
    n = len(tour)
    best = [float("inf")] * (n + 1)
    pred = [0] * (n + 1)
    best[0] = 0.0
    for i in range(n):
        if best[i] == float("inf"):
            continue
        load = d = latew = wait = delay = work = 0.0
        t, pos = start_time, DEPOT
        for j in range(i, n):
            c = tour[j]
            load += inst.demand[c]
            if load > capacity:
                break
            t += T[pos][c]
            d += D[pos][c]
            work += T[pos][c] + inst.service[c]
            if t < inst.ready[c]:
                if j == i:
                    delay = inst.ready[c] - t
                t = inst.ready[c]
            wait += t - inst.ready[c]
            if t > inst.deadline[c]:
                latew += (t - inst.deadline[c]) * inst.penalty_mult[c]
            t += inst.service[c]
            pos = c
            dur = t + T[c][DEPOT] - start_time - delay
            wk = work + T[c][DEPOT]
            cost = (w.alpha * (d + D[c][DEPOT]) / 1000.0 + w.beta * wk
                    + w.gamma * latew + w.epsilon * wait + w.delta + w.overtime(dur) + w.balance(wk))
            if best[i] + cost < best[j + 1]:
                best[j + 1] = best[i] + cost
                pred[j + 1] = i
    trips, j = [], n
    while j > 0:
        i = pred[j]
        trips.append(tour[i:j])
        j = i
    trips.reverse()
    return trips


def decode(inst: Instance, tour: list[int]) -> Solution:
    cap_max = max(v.capacity for v in inst.vehicles)
    start = min(v.start_time for v in inst.vehicles)
    trips = split(inst, tour, cap_max, start)
    trips.sort(key=lambda r: -sum(inst.demand[c] for c in r))
    routes: list[list[int]] = [[] for _ in inst.vehicles]
    free = sorted(range(len(inst.vehicles)), key=lambda k: inst.vehicles[k].capacity)
    unassigned: list[int] = []
    for trip in trips:
        need = sum(inst.demand[c] for c in trip)
        fit = next((k for k in free if inst.vehicles[k].capacity >= need), None)
        if fit is None and free:
            fit = free[-1]                      # overload -> penalised in fitness
        if fit is None:
            unassigned.extend(trip)
            continue
        routes[fit] = trip
        free.remove(fit)
    return Solution(routes, unassigned, "genetic")


def order_crossover(p1: list[int], p2: list[int], rng: random.Random) -> list[int]:
    n = len(p1)
    a, b = sorted(rng.sample(range(n), 2))
    child = [None] * n
    child[a:b + 1] = p1[a:b + 1]
    taken = set(p1[a:b + 1])
    fill = [g for g in p2[b + 1:] + p2[:b + 1] if g not in taken]
    idx = (b + 1) % n
    for g in fill:
        child[idx] = g
        idx = (idx + 1) % n
    return child


def mutate(tour: list[int], rng: random.Random) -> None:
    i, j = sorted(rng.sample(range(len(tour)), 2))
    if rng.random() < 0.5:
        tour[i], tour[j] = tour[j], tour[i]
    else:
        tour[i:j + 1] = reversed(tour[i:j + 1])


def giant_tour(sol: Solution) -> list[int]:
    return [c for r in sol.routes for c in r if c != DEPOT] + list(sol.unassigned)


def genetic_algorithm(inst: Instance, params: GAParams, seeds: list[Solution] | None = None,
                      ls_operators: list[str] | None = None, ls_rounds: int = 50,
                      ls_time_limit_s: float | None = None, k_nb: int = 12) -> Solution:
    rng = random.Random(params.seed)
    customers = list(inst.customers)
    if len(customers) < 3:
        sol = decode(inst, customers)
        return sol
    start = time.perf_counter()

    def fitness(tour):
        sol = decode(inst, tour)
        return solution_cost(inst, sol), sol

    population: list[tuple[float, list[int], Solution]] = []
    for s in seeds or []:
        t = giant_tour(s)
        if sorted(t) == sorted(customers):
            f, sol = fitness(t)
            population.append((f, t, sol))
    while len(population) < params.population_size:
        t = customers[:]
        rng.shuffle(t)
        f, sol = fitness(t)
        population.append((f, t, sol))
    population.sort(key=lambda x: x[0])
    history = [population[0][0]]
    generations_run = 0

    def tournament():
        return min(rng.sample(population, min(params.tournament_size, len(population))),
                   key=lambda x: x[0])[1]

    for _ in range(params.generations):
        if time.perf_counter() - start > params.time_limit_s:
            break
        generations_run += 1
        nxt = population[: params.elitism]
        seen = {tuple(p[1]) for p in nxt}
        while len(nxt) < params.population_size:
            p1, p2 = tournament(), tournament()
            child = order_crossover(p1, p2, rng) if rng.random() < params.crossover_rate else p1[:]
            if rng.random() < params.mutation_rate:
                mutate(child, rng)
            key = tuple(child)
            if key in seen:            # keep diversity: avoid clones
                mutate(child, rng)
                key = tuple(child)
            seen.add(key)
            f, sol = fitness(child)
            nxt.append((f, child, sol))
        population = sorted(nxt, key=lambda x: x[0])
        history.append(population[0][0])

    best = population[0][2].copy()
    best.algorithm = "genetic"
    best.notes.append(f"GA ran {generations_run} generations, population {params.population_size}")
    if params.local_search_on_best and ls_operators:
        before = solution_cost(inst, best)
        best, _ = improve(inst, best, ls_operators, ls_rounds, ls_time_limit_s, k_nb)
        best.notes.append(f"memetic local search improved cost by {before - solution_cost(inst, best):.2f}")
        history.append(solution_cost(inst, best))
    best.history = history
    return best
