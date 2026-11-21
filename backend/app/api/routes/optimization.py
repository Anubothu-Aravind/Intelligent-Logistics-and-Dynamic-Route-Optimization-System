from fastapi import APIRouter, Depends, HTTPException

from app.algorithms import ortools_solver
from app.api.deps import engine, guard
from app.db import models
from app.db.database import SessionLocal
from app.services import optimizer
from app.schemas.requests import CompareIn, OptimizeIn, ReoptimizeIn

router = APIRouter(prefix="/optimization", tags=["optimisation"])


@router.get("/algorithms")
def algorithms(eng=Depends(engine)):
    return {
        "routing": [{"id": k, "label": v, "available": k != "ortools" or ortools_solver.AVAILABLE}
                    for k, v in optimizer.ROUTING_ALGORITHMS.items()],
        "shortest_path": ["dijkstra", "astar", "bidirectional_dijkstra"],
        "operators": optimizer.LOCAL_SEARCH_OPERATORS,
        "strategies": ["insertion", "insertion_plus_local_search", "full"],
        "defaults": {"algorithm": eng.sc.get("algorithms.default_construction"),
                     "shortest_path": eng.sc.get("algorithms.default_shortest_path"),
                     "operators": eng.sc.get("algorithms.default_improvement"),
                     "weights": eng.sc.section("objective"),
                     "ga": eng.sc.section("algorithms")["genetic"],
                     "strategy": eng.sc.get("simulation.reoptimize_strategy")},
        "active": eng.active_settings,
    }


@router.post("/run")
def run(body: OptimizeIn, eng=Depends(engine)):
    req = body.model_dump(exclude_none=True)
    return guard(eng.optimize, req)


@router.post("/reoptimize")
def reoptimize(body: ReoptimizeIn, eng=Depends(engine)):
    return guard(eng.reoptimize, "manual", body.strategy)


@router.post("/compare")
def compare(body: CompareIn, eng=Depends(engine)):
    return {"results": guard(eng.compare_algorithms, body.algorithms)}


@router.get("/plan")
def plan(eng=Depends(engine)):
    with eng.lock:
        return {"plan": eng.plan, "meta": eng.plan_meta, "settings": eng.active_settings}


@router.get("/runs/{run_id}")
def get_run(run_id: int):
    with SessionLocal() as db:
        r = db.get(models.OptimizationRun, run_id)
        if not r:
            raise HTTPException(404, "run not found")
        return {"id": r.id, "kind": r.kind, "algorithm": r.algorithm, "params": r.params, "metrics": r.metrics,
                "baseline": r.baseline, "explanation": r.explanation, "runtime_ms": r.runtime_ms}
