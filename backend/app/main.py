"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.routes import analytics, fleet, network, optimization, orders, simulation
from app.core.config import get_env
from app.services.engine import ENGINE

log = logging.getLogger("logistics")
SHUTDOWN = asyncio.Event()


async def simulation_loop() -> None:
    while True:
        interval = float(ENGINE.sc.get("simulation.tick_interval_s")) if ENGINE.ready else 1.0
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(ENGINE.tick)
        except Exception:  # keep the loop alive, surface in logs
            log.exception("simulation tick failed")


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(ENGINE.bootstrap)
    if get_env().autostart_simulation:
        ENGINE.set_running(True)
    task = asyncio.create_task(simulation_loop())
    yield
    SHUTDOWN.set()
    task.cancel()


env = get_env()
app = FastAPI(title=env.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in env.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])

for r in (network.router, orders.router, fleet.router, optimization.router, simulation.router, analytics.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok" if not ENGINE.boot_error else "error", "ready": ENGINE.ready,
            "error": ENGINE.boot_error, "persistence_error": ENGINE.persistence_error,
            "city": getattr(ENGINE, "city", {}).get("city") if ENGINE.ready else None}


@app.get("/api/config")
def config():
    """Read-only view of the algorithm-related configuration (used by the Algorithm Lab docs)."""
    if not ENGINE.ready:
        return {"ready": False}
    sc = ENGINE.sc
    return {"ready": True, "algorithms": sc.section("algorithms"), "objective": sc.section("objective"),
            "simulation": sc.section("simulation"), "benchmark": sc.section("benchmark"),
            "network": {k: v for k, v in ENGINE.city.items() if k != "street_names"}}


@app.websocket("/ws")
async def ws(socket: WebSocket):
    """Pushes a fresh simulation snapshot whenever the engine revision changes."""
    await socket.accept()
    last = -1
    try:
        while not SHUTDOWN.is_set():
            if ENGINE.ready and ENGINE.revision != last:
                snap = await asyncio.to_thread(ENGINE.snapshot)
                last = snap["revision"]
                await socket.send_json(snap)
            await asyncio.sleep(0.25)
    except (WebSocketDisconnect, RuntimeError):
        return
