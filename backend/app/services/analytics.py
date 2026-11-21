"""Analytics aggregations for the dashboard (Module 5)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.core.timeutil import min_to_hhmm
from app.db import models
from app.db.database import SessionLocal


def summary(engine, from_min: float | None = None, to_min: float | None = None,
            runs_since_days: float | None = None) -> dict:
    """All figures come from live engine state and stored runs/events.

    from_min / to_min : simulated-clock window (minutes since midnight) applied to
                        deliveries, planned stops and dynamic events
    runs_since_days   : real-time window for the optimisation-run history"""
    lo = float("-inf") if from_min is None else from_min
    hi = float("inf") if to_min is None else to_min
    in_win = lambda t: t is not None and lo <= t <= hi  # noqa: E731
    with engine.lock:
        orders = [o for o in engine.orders.values() if o["status"] != "cancelled"]
        vehicles = engine.vehicles
        plan = engine.plan
        meta = engine.plan_meta
        kpis = engine.kpis()

        # deliveries per hour, stacked by vehicle (actual if simulated, else planned ETAs)
        actual = defaultdict(lambda: defaultdict(int))
        for o in orders:
            if o["status"] == "delivered" and o["vehicle_id"] in vehicles and in_win(o["delivered_min"]):
                actual[int(o["delivered_min"] // 60)][vehicles[o["vehicle_id"]]["code"]] += 1
        planned = defaultdict(lambda: defaultdict(int))
        predicted = {"early": 0, "on_time": 0, "late": 0}
        util = []
        per_vehicle = []
        if plan:
            for r in plan["routes"]:
                code = r["vehicle_code"]
                for s in r["stops"]:
                    if s["type"] == "order" and s.get("eta") is not None and in_win(s["eta"]):
                        planned[int(s["eta"] // 60)][code] += 1
                        o = engine.orders.get(s["order_id"])
                        if o:
                            note = "late" if s["eta"] > o["deadline_min"] else (
                                "early" if s["eta"] < o["ready_min"] else "on_time")
                            predicted[note] += 1
                if r["stops"]:
                    util.append((r["load_kg"], r["capacity_kg"]))
                per_vehicle.append({"vehicle": code, "distance_km": r["distance_km"], "stops": sum(
                    1 for s in r["stops"] if s["type"] == "order"), "load_kg": r["load_kg"],
                    "capacity_kg": r["capacity_kg"], "duration_min": r["duration_min"], "late": r["late_count"]})
        codes = sorted({v["code"] for v in vehicles.values()})

        def series(src):
            return [{"hour": f"{h:02d}:00", **{c: src[h].get(c, 0) for c in codes}} for h in sorted(src)]

        outcomes = {"early": 0, "on_time": 0, "late": 0}
        for o in orders:
            if o["status"] == "delivered" and o["delivery_note"] in outcomes and in_win(o["delivered_min"]):
                outcomes[o["delivery_note"]] += 1
        prio = defaultdict(lambda: defaultdict(int))
        for o in orders:
            prio[o["priority"]][o["status"]] += 1

        with SessionLocal() as db:
            rq = db.query(models.OptimizationRun)
            if runs_since_days:
                rq = rq.filter(models.OptimizationRun.created_at >= datetime.now(timezone.utc) - timedelta(days=runs_since_days))
            runs = rq.order_by(models.OptimizationRun.id.desc()).limit(25).all()
            eq = db.query(models.SimEvent)
            if from_min is not None:
                eq = eq.filter(models.SimEvent.sim_min >= from_min)
            if to_min is not None:
                eq = eq.filter(models.SimEvent.sim_min <= to_min)
            events = eq.order_by(models.SimEvent.id.desc()).limit(50).all()
            static_run = db.query(models.OptimizationRun).filter_by(kind="static").order_by(
                models.OptimizationRun.id.desc()).first()
            comparison = db.query(models.BenchmarkRun).filter_by(kind="algorithm_comparison").order_by(
                models.BenchmarkRun.id.desc()).first()

        ev_rows = []
        for e in events:
            r = e.response or {}
            ev_rows.append({
                "id": e.id, "time": min_to_hhmm(e.sim_min), "type": e.type,
                "static_objective": (r.get("static_policy") or {}).get("objective"),
                "reoptimized_objective": (r.get("reoptimized") or {}).get("objective"),
                "static_late": (r.get("static_policy") or {}).get("late_count"),
                "reoptimized_late": (r.get("reoptimized") or {}).get("late_count"),
                "saving_pct": ((r.get("saving") or {}).get("objective") or {}).get("pct"),
                "decisions": r.get("decisions", [])[:5],
            })
        cap_used = sum(c for _, c in util)
        hours = sorted(set(actual) | set(planned))
        delivered_win = [o for o in orders if o["status"] == "delivered" and in_win(o["delivered_min"])]
        late_win = [o for o in delivered_win if o["delivery_note"] == "late"]
        return {
            "window": {"from_min": from_min, "to_min": to_min, "runs_since_days": runs_since_days,
                       "clock": engine.clock, "shift": engine.sc.section("schedule")},
            "window_kpis": {
                "delivered": len(delivered_win), "late": len(late_win),
                "on_time_pct": round(1 - len(late_win) / len(delivered_win), 4) if delivered_win else None,
                "avg_delay_min": round(sum(o["delivered_min"] - o["deadline_min"] for o in late_win) / len(late_win), 1)
                if late_win else 0.0,
            },
            "actual_vs_planned": [{"hour": f"{h:02d}:00", "actual": sum(actual[h].values()),
                                   "planned": sum(planned[h].values())} for h in hours],
            "kpis": kpis,
            "deliveries_by_hour": {"actual": series(actual), "planned": series(planned), "vehicles": codes},
            "outcomes": {"actual": outcomes, "planned": predicted},
            "priorities": {p: dict(s) for p, s in prio.items()},
            "utilization": round(sum(l for l, _ in util) / cap_used, 4) if cap_used else 0.0,
            "per_vehicle": per_vehicle,
            "plan_metrics": meta["metrics"] if meta else None,
            "before_after": {
                "baseline": static_run.baseline if static_run else None,
                "optimized": static_run.metrics if static_run else None,
                "algorithm": static_run.algorithm if static_run else None,
                "improvement": (static_run.explanation or {}).get("improvement_vs_baseline") if static_run else None,
                "convergence": (static_run.explanation or {}).get("convergence") if static_run else None,
                "stages": (static_run.explanation or {}).get("stages") if static_run else None,
            },
            "algorithm_comparison": comparison.results if comparison else [],
            "events": ev_rows,
            "runs": [{"id": r.id, "kind": r.kind, "algorithm": r.algorithm, "time": min_to_hhmm(r.sim_min),
                      "objective": (r.metrics or {}).get("objective"), "distance_km": (r.metrics or {}).get("distance_km"),
                      "late_count": (r.metrics or {}).get("late_count"), "runtime_ms": r.runtime_ms}
                     for r in runs],
        }
