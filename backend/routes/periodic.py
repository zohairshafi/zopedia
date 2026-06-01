"""Periodic research routes — CRUD + trigger endpoints."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from periodic_scheduler import _compute_next_run

logger = logging.getLogger(__name__)

router = APIRouter()


class CreatePeriodicRequest(BaseModel):
    topic: str
    rounds: int = 3
    sources_per_round: int = 10
    auto_mode: bool = True
    trusted_sources: list[str] = []
    blocked_sources: list[str] = []
    research_depth: str = "standard"
    source_types: list[str] = []
    timelimit: str = "m"
    periodic_interval: str = "daily"  # hourly, daily, weekly, monthly
    periodic_hour: int | None = None  # 0-23
    periodic_dow: int | None = None   # 0=Mon..6=Sun, for weekly
    periodic_dom: int | None = None   # 1-31, for monthly (clamped to last day)


async def _get_username(request: Request) -> str:
    """Get the current authenticated username.

    Uses require_valid_subject so that expired JWTs trigger a 401,
    which tells the frontend to refresh its token and retry.
    The 401 must propagate — do not catch HTTPException here.
    """
    require_valid = getattr(request.app.state, "require_valid_subject", None)
    if require_valid:
        return await require_valid(request)
    return "default"


@router.post("/api/research/periodic")
async def create_periodic(request: Request, body: CreatePeriodicRequest):
    """Create a new periodic research config."""
    from periodic_store import create_config  # lazy to avoid import issues at startup
    from periodic_scheduler import PeriodicScheduler

    username = await _get_username(request)
    interval = body.periodic_interval
    if interval not in ("hourly", "daily", "weekly", "monthly"):
        raise HTTPException(status_code=400, detail=f"Invalid interval: {interval}")

    config_data = {
        "topic": body.topic,
        "rounds": body.rounds,
        "sources_per_round": body.sources_per_round,
        "auto_mode": True,  # always auto for periodic
        "trusted_sources": body.trusted_sources,
        "blocked_sources": body.blocked_sources,
        "research_depth": body.research_depth,
        "source_types": body.source_types,
        "timelimit": body.timelimit,
    }

    run_hour = body.periodic_hour
    run_dow = body.periodic_dow
    run_dom = body.periodic_dom
    next_run = _compute_next_run(interval, run_hour=run_hour, run_dow=run_dow, run_dom=run_dom)

    config_id = create_config(
        username=username,
        topic=body.topic,
        config=config_data,
        interval_type=interval,
        next_run_at=next_run,
        run_hour=run_hour,
        run_dow=run_dow,
        run_dom=run_dom,
    )

    # Schedule it
    scheduler = getattr(request.app.state, "periodic_scheduler", None)
    if scheduler:
        await scheduler.add_config(config_id, username)

    return {"id": config_id, "next_run_at": next_run}


@router.get("/api/research/periodic")
async def list_periodic(request: Request):
    """List all periodic configs for the current user."""
    from periodic_store import list_configs

    username = await _get_username(request)
    configs = list_configs(username)
    # Parse config_json for display
    result = []
    for c in configs:
        try:
            cfg = json.loads(c.get("config_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            cfg = {}
        result.append({
            "id": c["id"],
            "topic": c["topic"],
            "interval_type": c["interval_type"],
            "enabled": bool(c["enabled"]),
            "run_hour": c.get("run_hour"),
            "run_dow": c.get("run_dow"),
            "run_dom": c.get("run_dom"),
            "last_run_at": c.get("last_run_at"),
            "next_run_at": c.get("next_run_at"),
            "created_at": c["created_at"],
            "trusted_count": len(cfg.get("trusted_sources", [])),
            "rounds": cfg.get("rounds", 3),
            "sources_per_round": cfg.get("sources_per_round", 10),
        })
    return {"configs": result}


@router.delete("/api/research/periodic/{config_id}")
async def delete_periodic(request: Request, config_id: str):
    """Delete a periodic config and cancel its task."""
    from periodic_store import delete_config

    username = await _get_username(request)
    scheduler = getattr(request.app.state, "periodic_scheduler", None)
    if scheduler:
        scheduler.remove_config(config_id)
    deleted = delete_config(config_id, username)
    if not deleted:
        raise HTTPException(status_code=404, detail="Config not found")
    return {"status": "deleted"}


@router.get("/api/research/periodic/{config_id}")
async def get_periodic(request: Request, config_id: str):
    """Get a single periodic config with full details for editing."""
    from periodic_store import get_config

    username = await _get_username(request)
    cfg = get_config(config_id, username)
    if not cfg:
        raise HTTPException(status_code=404, detail="Config not found")

    try:
        config_data = json.loads(cfg.get("config_json", "{}"))
    except (json.JSONDecodeError, TypeError):
        config_data = {}

    return {
        "id": cfg["id"],
        "topic": cfg["topic"],
        "interval_type": cfg["interval_type"],
        "enabled": bool(cfg["enabled"]),
        "run_hour": cfg.get("run_hour"),
        "run_dow": cfg.get("run_dow"),
        "run_dom": cfg.get("run_dom"),
        "last_run_at": cfg.get("last_run_at"),
        "next_run_at": cfg.get("next_run_at"),
        "created_at": cfg["created_at"],
        # Full research config
        "rounds": config_data.get("rounds", 3),
        "sources_per_round": config_data.get("sources_per_round", 10),
        "trusted_sources": config_data.get("trusted_sources", []),
        "blocked_sources": config_data.get("blocked_sources", []),
        "research_depth": config_data.get("research_depth", "standard"),
        "source_types": config_data.get("source_types", []),
        "timelimit": config_data.get("timelimit", "m"),
    }


@router.put("/api/research/periodic/{config_id}")
async def update_periodic(request: Request, config_id: str, body: CreatePeriodicRequest):
    """Update an existing periodic research config."""
    from periodic_store import get_config, update_config

    username = await _get_username(request)
    existing = get_config(config_id, username)
    if not existing:
        raise HTTPException(status_code=404, detail="Config not found")

    interval = body.periodic_interval
    if interval not in ("hourly", "daily", "weekly", "monthly"):
        raise HTTPException(status_code=400, detail=f"Invalid interval: {interval}")

    config_data = {
        "topic": body.topic,
        "rounds": body.rounds,
        "sources_per_round": body.sources_per_round,
        "auto_mode": True,
        "trusted_sources": body.trusted_sources,
        "blocked_sources": body.blocked_sources,
        "research_depth": body.research_depth,
        "source_types": body.source_types,
        "timelimit": body.timelimit,
    }

    run_hour = body.periodic_hour
    run_dow = body.periodic_dow
    run_dom = body.periodic_dom
    next_run = _compute_next_run(interval, run_hour=run_hour, run_dow=run_dow, run_dom=run_dom)

    update_config(
        config_id, username,
        topic=body.topic,
        config_json=json.dumps(config_data),
        interval_type=interval,
        next_run_at=next_run,
        run_hour=run_hour,
        run_dow=run_dow,
        run_dom=run_dom,
    )

    # Re-schedule
    scheduler = getattr(request.app.state, "periodic_scheduler", None)
    if scheduler:
        await scheduler.update_config(config_id, username)

    return {"id": config_id, "next_run_at": next_run}


class TogglePeriodicRequest(BaseModel):
    enabled: bool


@router.patch("/api/research/periodic/{config_id}")
async def toggle_periodic(request: Request, config_id: str, body: TogglePeriodicRequest):
    """Enable or disable a periodic research config."""
    from periodic_store import get_config, update_config

    username = await _get_username(request)
    existing = get_config(config_id, username)
    if not existing:
        raise HTTPException(status_code=404, detail="Config not found")

    update_config(config_id, username, enabled=int(body.enabled))

    scheduler = getattr(request.app.state, "periodic_scheduler", None)
    if scheduler:
        if body.enabled:
            # Re-compute next run when re-enabling
            cfg = get_config(config_id, username)
            run_hour = cfg.get("run_hour")
            run_dow = cfg.get("run_dow")
            run_dom = cfg.get("run_dom")
            next_run = _compute_next_run(
                cfg["interval_type"],
                run_hour=run_hour, run_dow=run_dow, run_dom=run_dom,
            )
            update_config(config_id, username, next_run_at=next_run)
            await scheduler.add_config(config_id, username)
        else:
            scheduler.remove_config(config_id)

    return {"enabled": body.enabled}


@router.post("/api/research/periodic/{config_id}/run-now")
async def run_now_periodic(request: Request, config_id: str):
    """Trigger immediate execution of a periodic research config."""
    username = await _get_username(request)
    scheduler = getattr(request.app.state, "periodic_scheduler", None)
    if not scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    try:
        await scheduler.run_now(config_id, username)
    except ValueError:
        raise HTTPException(status_code=404, detail="Config not found")
    return {"status": "started"}
