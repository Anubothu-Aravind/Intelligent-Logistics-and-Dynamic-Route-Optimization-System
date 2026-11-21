"""Non-destructive schema upgrades for databases created by earlier versions.

`create_all` only creates missing tables; it never alters existing ones. These
statements add what newer versions need without touching existing rows."""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from .database import Base, engine

log = logging.getLogger("logistics.db")

INDEXES = [
    ("ix_orders_status", "orders", "status"),
    ("ix_orders_priority", "orders", "priority"),
    ("ix_orders_vehicle_id", "orders", "vehicle_id"),
    ("ix_orders_delivered_min", "orders", "delivered_min"),
    ("ix_optimization_runs_kind", "optimization_runs", "kind"),
    ("ix_sim_events_sim_min", "sim_events", "sim_min"),
    ("ix_benchmark_runs_kind", "benchmark_runs", "kind"),
]
COLUMNS = [("benchmark_runs", "status", "VARCHAR(16) DEFAULT 'finished'")]


def upgrade() -> list[str]:
    from . import models  # noqa: F401  (register tables)
    Base.metadata.create_all(engine)
    applied = []
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, col, ddl in COLUMNS:
            if col not in {c["name"] for c in insp.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                applied.append(f"add column {table}.{col}")
        for name, table, col in INDEXES:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({col})"))
    if applied:
        log.info("schema upgraded: %s", applied)
    return applied
