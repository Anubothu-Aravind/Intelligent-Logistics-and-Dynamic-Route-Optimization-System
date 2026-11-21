from fastapi import HTTPException

from app.services.engine import ENGINE, Conflict


def engine():
    if not ENGINE.ready:
        raise HTTPException(503, ENGINE.boot_error or "The optimisation engine is still starting – retry in a moment")
    return ENGINE


def guard(fn, *args, **kwargs):
    """Translate domain errors to HTTP errors with readable messages."""
    try:
        return fn(*args, **kwargs)
    except Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, f"Not found: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
