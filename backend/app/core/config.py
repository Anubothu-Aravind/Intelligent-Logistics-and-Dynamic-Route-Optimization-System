"""Application settings.

Runtime/infrastructure settings come from environment variables (``.env``);
the scenario + algorithm parameters come from ``config/settings.yaml``.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


def _abs(path: str) -> str:
    """Relative paths in .env are relative to the project root, not the CWD."""
    p = Path(path)
    return str(p if p.is_absolute() else (PROJECT_DIR / p).resolve())


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Intelligent Logistics & Dynamic Route Optimization"
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'logistics.db'}"
    scenario_config: str = str(BACKEND_DIR / "config" / "settings.yaml")
    cors_origins: str = "*"
    random_seed: int | None = None
    order_count: int | None = None
    vehicle_count: int | None = None
    autostart_simulation: bool = False
    city_source: str | None = None          # osm | synthetic (overrides settings.yaml)
    map_tile_url: str | None = None
    map_tile_attribution: str | None = None
    carto_api_key: str | None = None

    @field_validator("database_url")
    @classmethod
    def _db_path(cls, v: str) -> str:
        prefix = "sqlite:///"
        if v.startswith(prefix) and not v.startswith(prefix + "/"):
            return prefix + _abs(v[len(prefix):])
        return v

    @field_validator("scenario_config")
    @classmethod
    def _cfg_path(cls, v: str) -> str:
        return _abs(v)

    @field_validator("random_seed", "order_count", "vehicle_count", "city_source", "map_tile_url",
                     "map_tile_attribution", "carto_api_key", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        return None if v == "" else v


def _deep_get(data: dict, dotted: str, default: Any = None) -> Any:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


class Scenario:
    """Thin read-only wrapper around the YAML scenario file."""

    def __init__(self, data: dict[str, Any]):
        self.data = data

    def get(self, dotted: str, default: Any = None) -> Any:
        return _deep_get(self.data, dotted, default)

    def section(self, name: str) -> dict[str, Any]:
        return dict(self.data.get(name, {}))


@lru_cache
def get_env() -> EnvSettings:
    return EnvSettings()


DATA_DIR = BACKEND_DIR / "data"


@lru_cache
def get_scenario() -> Scenario:
    env = get_env()
    with open(env.scenario_config, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    # environment overrides
    if env.random_seed is not None:
        data["random_seed"] = env.random_seed
    if env.order_count is not None:
        data.setdefault("orders", {})["initial_count"] = env.order_count
    if env.vehicle_count is not None:
        data.setdefault("fleet", {})["vehicle_count"] = env.vehicle_count
    if env.city_source:
        data.setdefault("city", {})["source"] = env.city_source
    ui = data.setdefault("ui", {})
    if env.map_tile_url:
        ui["map_tile_url"] = env.map_tile_url
    if env.map_tile_attribution:
        ui["map_tile_attribution"] = env.map_tile_attribution
    if env.carto_api_key:
        tile_url = ui.get("map_tile_url", "")
        if "{apikey}" in tile_url:
            ui["map_tile_url"] = tile_url.replace("{apikey}", env.carto_api_key)
        elif "cartocdn.com" in tile_url and "key=" not in tile_url:
            sep = "&" if "?" in tile_url else "?"
            ui["map_tile_url"] = f"{tile_url}{sep}key={env.carto_api_key}"
    return Scenario(data)
