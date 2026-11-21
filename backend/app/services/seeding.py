"""Scenario generation – depots, fleet and orders are produced from settings.yaml
with a seeded RNG and Faker (no hard-coded entities)."""
from __future__ import annotations

import random

from faker import Faker
from sqlalchemy.orm import Session

from app.algorithms.graph import RoadNetwork
from app.core.config import Scenario
from app.core.geo import haversine_m
from app.core.timeutil import hhmm_to_min
from app.db import models
from app.services.city_generator import street_of_node


def make_depot(db: Session, net: RoadNetwork, faker: Faker, lat: float, lon: float, name: str | None = None) -> models.Depot:
    node = net.nearest_node(lat, lon)
    nlat, nlon = net.nodes[node]
    depot = models.Depot(name=name or f"{faker.city()} Hub", address=street_of_node(net, node),
                         node_id=node, lat=nlat, lon=nlon)
    db.add(depot)
    db.flush()
    return depot


def make_vehicle(db: Session, sc: Scenario, rng: random.Random, faker: Faker, depot_id: int,
                 vtype: dict | None = None, driver: str | None = None) -> models.Vehicle:
    fleet = sc.section("fleet")
    types = fleet["types"]
    vt = vtype or rng.choices(types, weights=[t["weight"] for t in types])[0]
    prefix = vt["prefix"]
    existing = {c for (c,) in db.query(models.Vehicle.code).all()}
    number = int(fleet["code_start"])
    while f"{prefix}-{number}" in existing:
        number += rng.randint(1, 30)
    exp = fleet["driver_experience_years"]
    fuel = fleet["start_fuel_pct"]
    since = faker.date_between(start_date=f"-{exp['max']}y", end_date=f"-{exp['min']}y").year
    v = models.Vehicle(
        code=f"{prefix}-{number}", model=vt["model"], driver_name=driver or faker.name(),
        driver_since=since, capacity_kg=float(vt["capacity_kg"]),
        fuel_l_per_100km=float(vt["fuel_l_per_100km"]), co2_kg_per_l=float(vt["co2_kg_per_l"]),
        fuel_tank_l=float(vt["tank_l"]),
        fuel_level_l=round(float(vt["tank_l"]) * rng.uniform(fuel["min"], fuel["max"]), 1),
        depot_id=depot_id, active=True,
    )
    db.add(v)
    db.flush()
    return v


def pick_customer_node(net: RoadNetwork, sc: Scenario, rng: random.Random, depot_nodes: list[int]) -> int:
    min_d = float(sc.get("orders.min_distance_from_depot_m"))
    ids = list(net.nodes)
    for _ in range(1000):
        n = rng.choice(ids)
        if all(haversine_m(*net.nodes[n], *net.nodes[d]) >= min_d for d in depot_nodes):
            return n
    return rng.choice(ids)


def next_order_code(db: Session, sc: Scenario) -> str:
    last = db.query(models.Order.id).order_by(models.Order.id.desc()).first()
    return f"{sc.get('orders.code_prefix')}{1001 + (last[0] if last else 0)}"


def make_order(db: Session, net: RoadNetwork, sc: Scenario, rng: random.Random, faker: Faker,
               depot_nodes: list[int], now_min: float, source: str, node: int | None = None,
               weight: float | None = None, priority: str | None = None,
               deadline_min: float | None = None, customer: str | None = None) -> models.Order:
    oc = sc.section("orders")
    node = node if node is not None else pick_customer_node(net, sc, rng, depot_nodes)
    pr_names = list(oc["priorities"])
    priority = priority or rng.choices(pr_names, weights=[oc["priorities"][p][0] for p in pr_names])[0]
    if priority not in oc["priorities"]:
        raise ValueError(f"priority must be one of {pr_names}")
    weight = weight if weight is not None else round(rng.uniform(oc["weight_kg"]["min"], oc["weight_kg"]["max"]), 1)
    if deadline_min is None:
        off = oc["deadline_offset_min"]
        base = hhmm_to_min(sc.get("schedule.shift_start")) if source == "initial" else now_min
        deadline_min = base + rng.uniform(off["min"], off["max"])
    win = rng.uniform(oc["time_window_min"]["min"], oc["time_window_min"]["max"])
    if source != "initial" and oc.get("dynamic_ready_immediately", False):
        ready = now_min                       # a customer ordering now can receive it now
    else:
        ready = max(now_min, deadline_min - win)
    lat, lon = net.nodes[node]
    o = models.Order(
        code=next_order_code(db, sc), customer_name=customer or faker.company(),
        address=f"{faker.building_number()} {street_of_node(net, node)}", node_id=node, lat=lat, lon=lon,
        weight_kg=float(weight), priority=priority, ready_min=round(ready, 1), deadline_min=round(deadline_min, 1),
        service_min=round(rng.uniform(oc["service_time_min"]["min"], oc["service_time_min"]["max"]), 1),
        status="pending", source=source, created_min=now_min,
    )
    db.add(o)
    db.flush()
    return o


def seed_scenario(db: Session, net: RoadNetwork, sc: Scenario, rng: random.Random, faker: Faker) -> None:
    for model in (models.SimEvent, models.OptimizationRun, models.Order, models.Vehicle, models.Depot):
        db.query(model).delete()
    db.flush()
    dcfg = sc.section("depots")
    lat0, lon0 = float(sc.get("city.center_lat")), float(sc.get("city.center_lon"))
    depots = []
    for i in range(int(dcfg["count"])):
        if dcfg["placement"] == "center" and i == 0:
            lat, lon = lat0, lon0
        else:
            lat, lon = net.nodes[rng.choice(list(net.nodes))]
        depots.append(make_depot(db, net, faker, lat, lon))
    for i in range(int(sc.get("fleet.vehicle_count"))):
        make_vehicle(db, sc, rng, faker, depots[i % len(depots)].id)
    start = hhmm_to_min(sc.get("schedule.shift_start"))
    nodes = [d.node_id for d in depots]
    for _ in range(int(sc.get("orders.initial_count"))):
        make_order(db, net, sc, rng, faker, nodes, start, "initial")
    db.commit()
