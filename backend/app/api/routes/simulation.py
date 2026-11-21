from fastapi import APIRouter, Depends

from app.api.deps import engine, guard
from app.schemas.requests import ClosureIn, CongestionIn, OrderIn, RandomEventsIn, ResetIn, SpeedIn

router = APIRouter(prefix="/simulation", tags=["simulation & dynamic events"])


@router.get("/state")
def state(eng=Depends(engine)):
    return eng.snapshot()


@router.post("/start")
def start(eng=Depends(engine)):
    return guard(eng.set_running, True)


@router.post("/pause")
def pause(eng=Depends(engine)):
    return eng.set_running(False)


@router.post("/stop")
def stop(eng=Depends(engine)):
    return guard(eng.stop_run)


@router.post("/step")
def step(eng=Depends(engine)):
    with eng.lock:
        was = eng.running
        if not eng.dispatched:
            guard(eng.set_running, True)
        eng.running = True
        eng.tick()
        eng.running = was
    return eng.snapshot()


@router.post("/speed")
def speed(body: SpeedIn, eng=Depends(engine)):
    eng.set_speed(body.minutes_per_tick)
    return {"minutes_per_tick": eng.minutes_per_tick}


@router.post("/random-events")
def random_events(body: RandomEventsIn, eng=Depends(engine)):
    with eng.lock:
        eng.random_events = body.enabled
        eng._bump()
    return {"enabled": eng.random_events}


@router.post("/reset")
def reset(body: ResetIn, eng=Depends(engine)):
    if body.regenerate:
        eng.bootstrap(reseed=True, seed=body.seed)
    else:
        eng.reset_simulation(drop_dynamic_orders=True, clear_plan=not body.keep_plan)
    return eng.snapshot()


@router.post("/events/new-order")
def new_order(body: OrderIn, eng=Depends(engine)):
    return guard(eng.event_new_order, body.model_dump(exclude_none=True))


@router.post("/events/congestion")
def congestion(body: CongestionIn, eng=Depends(engine)):
    return guard(eng.event_congestion, body.model_dump(exclude_none=True))


@router.post("/events/closure")
def closure(body: ClosureIn, eng=Depends(engine)):
    return guard(eng.event_closure, body.model_dump(exclude_none=True))


@router.post("/events/clear-traffic")
def clear(eng=Depends(engine)):
    return eng.clear_traffic()
