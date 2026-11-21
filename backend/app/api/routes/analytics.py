from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import engine
from app.db import models
from app.db.database import SessionLocal
from app.schemas.requests import BenchmarkIn
from app.services import analytics, benchmark

router = APIRouter(tags=["analytics & benchmarks"])


@router.get("/analytics/summary")
def summary(from_min: float | None = Query(None, ge=0, le=1440), to_min: float | None = Query(None, ge=0, le=1440),
            runs_since_days: float | None = Query(None, gt=0, le=3650), eng=Depends(engine)):
    if from_min is not None and to_min is not None and from_min > to_min:
        raise HTTPException(422, "from_min must be before to_min")
    return analytics.summary(eng, from_min, to_min, runs_since_days)


def _create_run(params: dict) -> int:
    with SessionLocal.begin() as db:
        run = models.BenchmarkRun(kind="experiments", params=params, results=[], status="running")
        db.add(run)
        db.flush()
        return run.id


def _save_run(run_id: int, results: dict, status: str) -> None:
    with SessionLocal.begin() as db:
        run = db.get(models.BenchmarkRun, run_id)
        if run:
            run.results = [results]
            run.status = status


@router.post("/benchmarks")
def start_benchmark(body: BenchmarkIn, eng=Depends(engine)):
    params = body.model_dump(exclude_none=True)
    if not benchmark.plan_jobs(eng.sc, params):
        raise HTTPException(422, "Nothing to run – select at least one algorithm and size")
    if not benchmark.start_async(eng.sc, params, _create_run, _save_run):
        raise HTTPException(409, "A benchmark is already running")
    return benchmark.STATUS


@router.post("/benchmarks/cancel")
def cancel_benchmark():
    if not benchmark.cancel():
        raise HTTPException(409, "No benchmark is running")
    return {"cancelling": True}


@router.get("/benchmarks/status")
def status():
    return benchmark.STATUS


@router.get("/benchmarks/runs")
def runs():
    with SessionLocal() as db:
        rows = db.query(models.BenchmarkRun).filter_by(kind="experiments").order_by(models.BenchmarkRun.id.desc()).limit(20)
        return {"runs": [{"id": r.id, "created_at": r.created_at, "status": r.status, "params": r.params,
                          "experiments": sum(len((r.results or [{}])[0].get(k, [])) for k in ("shortest_path", "vrp")) if r.results else 0}
                         for r in rows]}


@router.get("/benchmarks/runs/{run_id}")
def run_detail(run_id: int):
    with SessionLocal() as db:
        r = db.get(models.BenchmarkRun, run_id)
        if not r or r.kind != "experiments":
            raise HTTPException(404, "benchmark run not found")
        return {"id": r.id, "created_at": r.created_at, "status": r.status, "params": r.params,
                "results": (r.results or [None])[0]}


@router.get("/benchmarks/latest")
def latest():
    with SessionLocal() as db:
        r = db.query(models.BenchmarkRun).filter_by(kind="experiments").order_by(models.BenchmarkRun.id.desc()).first()
        if not r:
            return {"results": None}
        return {"id": r.id, "created_at": r.created_at, "status": r.status, "params": r.params,
                "results": (r.results or [None])[0]}


@router.get("/benchmarks/defaults")
def defaults(eng=Depends(engine)):
    from app.algorithms import ortools_solver
    return {**eng.sc.section("benchmark"), "vrp_labels": benchmark.VRP_LABELS, "sp_labels": benchmark.SP_LABELS,
            "ortools_available": ortools_solver.AVAILABLE}
