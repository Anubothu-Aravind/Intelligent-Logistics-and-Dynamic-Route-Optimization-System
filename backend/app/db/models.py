from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Depot(Base):
    __tablename__ = "depots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(200), default="")
    node_id: Mapped[int] = mapped_column(Integer)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)


class Vehicle(Base):
    __tablename__ = "vehicles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    model: Mapped[str] = mapped_column(String(64))
    driver_name: Mapped[str] = mapped_column(String(120))
    driver_since: Mapped[int] = mapped_column(Integer)
    capacity_kg: Mapped[float] = mapped_column(Float)
    fuel_l_per_100km: Mapped[float] = mapped_column(Float)
    co2_kg_per_l: Mapped[float] = mapped_column(Float)
    fuel_tank_l: Mapped[float] = mapped_column(Float)
    fuel_level_l: Mapped[float] = mapped_column(Float)
    depot_id: Mapped[int] = mapped_column(ForeignKey("depots.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    customer_name: Mapped[str] = mapped_column(String(160))
    address: Mapped[str] = mapped_column(String(200))
    node_id: Mapped[int] = mapped_column(Integer)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    weight_kg: Mapped[float] = mapped_column(Float)
    priority: Mapped[str] = mapped_column(String(16), index=True)
    ready_min: Mapped[float] = mapped_column(Float)
    deadline_min: Mapped[float] = mapped_column(Float)
    service_min: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending | assigned | in_transit | delivered | cancelled
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(16), default="initial")   # initial | user | simulated
    created_min: Mapped[float] = mapped_column(Float)
    delivered_min: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    delivery_note: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class OptimizationRun(Base):
    __tablename__ = "optimization_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    kind: Mapped[str] = mapped_column(String(16), index=True)            # static | dynamic
    algorithm: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    baseline: Mapped[dict] = mapped_column(JSON, default=dict)
    comparison: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[dict] = mapped_column(JSON, default=dict)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    runtime_ms: Mapped[float] = mapped_column(Float, default=0.0)
    sim_min: Mapped[float] = mapped_column(Float, default=0.0)


class SimEvent(Base):
    __tablename__ = "sim_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    sim_min: Mapped[float] = mapped_column(Float, index=True)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    response: Mapped[dict] = mapped_column(JSON, default=dict)


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="finished")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    results: Mapped[list] = mapped_column(JSON, default=list)


class AppMeta(Base):
    """Key/value store for engine bookkeeping (e.g. the road-graph signature)."""
    __tablename__ = "app_meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(2000))
