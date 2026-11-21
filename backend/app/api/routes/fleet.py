from fastapi import APIRouter, Depends

from app.api.deps import engine, guard
from app.schemas.requests import DepotIn, VehicleIn, VehicleUpdate

router = APIRouter(tags=["fleet & depots"])


@router.get("/vehicles")
def vehicles(eng=Depends(engine)):
    with eng.lock:
        return {"vehicles": [{k: v for k, v in eng.vehicle_view(rt).items() if k not in ("stops", "motion")} | {"fuel_tank_l": eng.vehicles[rt.vehicle_id]["fuel_tank_l"],
                                                      "fuel_l_per_100km": eng.vehicles[rt.vehicle_id]["fuel_l_per_100km"]}
                             for rt in eng.runtime.values()],
                "types": eng.sc.get("fleet.types")}


@router.post("/vehicles")
def add_vehicle(body: VehicleIn, eng=Depends(engine)):
    return guard(eng.add_vehicle, body.model_dump(exclude_none=True))


@router.patch("/vehicles/{vehicle_id}")
def update_vehicle(vehicle_id: int, body: VehicleUpdate, eng=Depends(engine)):
    return guard(eng.update_vehicle, vehicle_id, body.model_dump(exclude_none=True))


@router.get("/vehicles/{vehicle_id}/alternatives")
def alternatives(vehicle_id: int, eng=Depends(engine)):
    return guard(eng.alternatives, vehicle_id)


@router.get("/vehicles/{vehicle_id}/route")
def vehicle_route(vehicle_id: int, eng=Depends(engine)):
    return guard(eng.vehicle_route, vehicle_id)


@router.get("/routes")
def all_routes(eng=Depends(engine)):
    return eng.all_routes()


@router.get("/depots")
def depots(eng=Depends(engine)):
    """Each hub with its active vehicles and the open orders clustered to it.
    A hub without vehicles is not used for planning (orders go to the nearest staffed hub)."""
    return {"depots": eng.depots_view()}


@router.post("/depots")
def add_depot(body: DepotIn, eng=Depends(engine)):
    return guard(eng.add_depot, body.model_dump(exclude_none=True))
