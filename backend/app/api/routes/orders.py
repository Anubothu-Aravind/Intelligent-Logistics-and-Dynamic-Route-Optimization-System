"""Orders: server-side paginated listing straight from the database (indexed
filters), compact map markers, cancel vs permanent delete, bulk delete, clear."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select

from app.api.deps import engine, guard
from app.core.timeutil import min_to_hhmm
from app.db import models
from app.db.database import SessionLocal
from app.schemas.requests import GenerateOrdersIn, OrderIn

router = APIRouter(prefix="/orders", tags=["orders"])

SORTS = {"id": models.Order.id, "code": models.Order.id, "deadline": models.Order.deadline_min,
         "weight": models.Order.weight_kg, "priority": models.Order.priority, "status": models.Order.status,
         "delivered": models.Order.delivered_min, "created": models.Order.created_min}
FIELDS = ["id", "code", "customer_name", "address", "lat", "lon", "weight_kg", "priority", "ready_min",
          "deadline_min", "service_min", "status", "vehicle_id", "source", "created_min", "delivered_min", "delivery_note"]


def present(eng, o: dict) -> dict:
    v = eng.vehicles.get(o["vehicle_id"]) if o.get("vehicle_id") else None
    return {**o, "vehicle_code": v["code"] if v else None, "ready": min_to_hhmm(o["ready_min"]),
            "deadline": min_to_hhmm(o["deadline_min"]), "delivered": min_to_hhmm(o["delivered_min"]),
            "created": min_to_hhmm(o["created_min"])}


def _filters(stmt, status, priority, q):
    if status:
        stmt = stmt.where(models.Order.status.in_(status.split(",")))
    if priority:
        stmt = stmt.where(models.Order.priority == priority)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(models.Order.code.ilike(like), models.Order.customer_name.ilike(like),
                              models.Order.address.ilike(like)))
    return stmt


@router.get("")
def list_orders(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=500),
                status: str | None = None, priority: str | None = None, q: str | None = Query(None, max_length=80),
                sort: str = "id", direction: Literal["asc", "desc"] = "asc", eng=Depends(engine)):
    col = SORTS.get(sort, models.Order.id)
    with SessionLocal() as db:
        base = _filters(select(models.Order), status, priority, q)
        total = db.scalar(select(func.count()).select_from(base.subquery()))
        rows = db.execute(base.order_by(col.desc() if direction == "desc" else col.asc(), models.Order.id)
                          .offset((page - 1) * page_size).limit(page_size)).scalars().all()
        counts = dict(db.execute(_filters(select(models.Order.status, func.count()), None, priority, q)
                                 .group_by(models.Order.status)).all())
    items = [present(eng, {f: getattr(r, f) for f in FIELDS}) for r in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": max(1, -(-total // page_size)), "counts": counts,
            "priorities": list(eng.sc.get("orders.priorities"))}


@router.get("/markers")
def markers(status: str = "pending,assigned,in_transit", eng=Depends(engine)):
    """Minimal fields for map markers (no pagination needed, ~60 bytes per order)."""
    wanted = set(status.split(","))
    with eng.lock:
        return {"markers": [[o["id"], o["code"], round(o["lat"], 6), round(o["lon"], 6), o["status"], o["priority"]]
                            for o in eng.orders.values() if o["status"] in wanted],
                "fields": ["id", "code", "lat", "lon", "status", "priority"]}


@router.post("")
def create_order(body: OrderIn, eng=Depends(engine)):
    res = guard(eng.add_order, body.model_dump(exclude_none=True))
    return {**res, "order": present(eng, res["order"])}


@router.post("/generate")
def generate(body: GenerateOrdersIn, eng=Depends(engine)):
    return {"orders": [present(eng, o) for o in guard(eng.generate_orders, body.count)]}


@router.post("/{order_id}/cancel")
def cancel(order_id: int, eng=Depends(engine)):
    """Cancel keeps the record for history; it only leaves every route."""
    return present(eng, guard(eng.cancel_order, order_id))


class Selection(BaseModel):
    ids: list[int] | None = Field(None, max_length=100_000)
    filter: dict | None = None          # {status | statuses, priority, q}
    include_delivered: bool = False

    @model_validator(mode="after")
    def _one(self):
        if self.ids is None and self.filter is None:
            raise ValueError("Provide either ids or filter")
        return self


@router.delete("/{order_id}")
def delete_one(order_id: int, include_delivered: bool = False, eng=Depends(engine)):
    if order_id not in eng.orders:
        raise HTTPException(404, f"Order {order_id} not found")
    res = guard(eng.delete_orders, ids=[order_id], include_delivered=include_delivered)
    if res["deleted"] == 0:
        reason = "it is being delivered right now" if res["skipped_in_service"] else \
            "it is delivered – confirm deleting history" if res["skipped_delivered"] else "it no longer exists"
        raise HTTPException(400, f"Order was not deleted: {reason}")
    return res


@router.post("/bulk-delete/preview")
def preview(body: Selection, eng=Depends(engine)):
    return guard(eng.deletion_preview, body.ids, body.filter, body.include_delivered)


@router.post("/bulk-delete")
def bulk_delete(body: Selection, eng=Depends(engine)):
    return guard(eng.delete_orders, body.ids, body.filter, body.include_delivered)


class ClearIn(BaseModel):
    include_delivered: bool = False


@router.post("/clear")
def clear(body: ClearIn, eng=Depends(engine)):
    return guard(eng.delete_orders, None, {}, body.include_delivered)
