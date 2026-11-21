from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

RoutingAlgorithm = Literal["fifo", "nearest_neighbour", "clarke_wright", "sweep", "genetic", "ortools"]
PathAlgorithm = Literal["dijkstra", "astar", "bidirectional_dijkstra"]
Operator = Literal["two_opt", "or_opt", "relocate", "swap"]


class WeightsIn(BaseModel):
    alpha_distance_per_km: float | None = Field(None, ge=0)
    beta_time_per_min: float | None = Field(None, ge=0)
    gamma_lateness_per_min: float | None = Field(None, ge=0)
    delta_vehicle_fixed: float | None = Field(None, ge=0)
    epsilon_waiting_per_min: float | None = Field(None, ge=0)
    zeta_balance_per_h2: float | None = Field(None, ge=0)
    max_route_duration_min: float | None = Field(None, gt=0)
    route_overtime_penalty_per_min: float | None = Field(None, ge=0)


class GAIn(BaseModel):
    population_size: int | None = Field(None, ge=4, le=500)
    generations: int | None = Field(None, ge=1, le=5000)
    mutation_rate: float | None = Field(None, ge=0, le=1)
    crossover_rate: float | None = Field(None, ge=0, le=1)
    time_limit_s: float | None = Field(None, gt=0, le=600)


class OptimizeIn(BaseModel):
    algorithm: RoutingAlgorithm | None = None
    shortest_path: PathAlgorithm | None = None
    operators: list[Operator] | None = None
    weights: WeightsIn | None = None
    ga: GAIn | None = None


class CompareIn(BaseModel):
    algorithms: list[RoutingAlgorithm] | None = None


class OrderIn(BaseModel):
    customer_name: str | None = Field(None, max_length=160)
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    weight_kg: float | None = Field(None, gt=0)
    priority: str | None = None
    deadline: str | None = Field(None, pattern=r"^\d{1,2}:\d{2}$")
    deadline_in_min: float | None = Field(None, gt=0)


class GenerateOrdersIn(BaseModel):
    count: int = Field(..., ge=1, le=1000)


class VehicleIn(BaseModel):
    model: str | None = Field(None, max_length=64)
    capacity_kg: float | None = Field(None, gt=0, le=100_000)
    driver_name: str | None = Field(None, max_length=120)
    depot_id: int | None = None


class VehicleUpdate(BaseModel):
    capacity_kg: float | None = Field(None, gt=0, le=100_000)
    driver_name: str | None = Field(None, min_length=1, max_length=120)
    active: bool | None = None
    depot_id: int | None = None


class DepotIn(BaseModel):
    name: str | None = Field(None, max_length=120)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    move_vehicles: int = Field(0, ge=0, le=200, description="re-home this many idle vehicles to the new hub")


class CongestionIn(BaseModel):
    lat: float | None = None
    lon: float | None = None
    radius_m: float | None = Field(None, gt=0)
    factor: float | None = Field(None, ge=1)
    duration_min: float | None = Field(None, gt=0)


class ClosureIn(BaseModel):
    u: int | None = None
    v: int | None = None


class SpeedIn(BaseModel):
    minutes_per_tick: float = Field(..., gt=0, le=60)


class ResetIn(BaseModel):
    regenerate: bool = False
    seed: int | None = None
    keep_plan: bool = False


class RandomEventsIn(BaseModel):
    enabled: bool


class ReoptimizeIn(BaseModel):
    strategy: Literal["insertion", "insertion_plus_local_search", "full"] | None = None


class PathQueryIn(BaseModel):
    source: int | None = None
    target: int | None = None
    source_lat: float | None = None
    source_lon: float | None = None
    target_lat: float | None = None
    target_lon: float | None = None
    metric: Literal["time", "distance"] = "time"
    k: int | None = Field(None, ge=1, le=10)


class BenchmarkIn(BaseModel):
    graph_sizes: list[list[int]] | None = Field(None, max_length=8)
    path_queries: int | None = Field(None, ge=1, le=1000)
    vrp_sizes: list[int] | None = Field(None, max_length=8)
    vrp_vehicles: int | None = Field(None, ge=1, le=200)
    ga_generations: int | None = Field(None, ge=1, le=2000)
    shortest_path_algorithms: list[str] | None = None
    vrp_algorithms: list[str] | None = None
    include_ortools: bool = True
    timeout_s: float | None = Field(None, ge=5, le=3600)
    seed: int | None = None

    @field_validator("graph_sizes")
    @classmethod
    def _sizes(cls, v):
        for g in v or []:
            if len(g) != 2 or not (g == [0, 0] or all(3 <= x <= 120 for x in g)):
                raise ValueError("graph sizes must be [rows, cols] between 3 and 120, or [0, 0] for the real city map")
        return v

    @field_validator("vrp_sizes")
    @classmethod
    def _vrp(cls, v):
        if any(not 5 <= x <= 2000 for x in v or []):
            raise ValueError("order counts must be between 5 and 2000")
        return v
