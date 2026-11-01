"""Trigger a classification run (like the `run` CLI command) and report its outcome."""

import threading
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from loguru import logger

from mailtag.config import CONFIG

from ..schemas import ErrorResponse, RunStatus

router = APIRouter()

RUN_THREAD = "mailtag-run"

_busy = threading.Lock()
_status = RunStatus(state="idle")


def reset() -> None:
    """Forget the last run (tests)."""
    global _status
    _status = RunStatus(state="idle")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _worker(provider: str, validate: bool) -> None:
    # src/ is on the path both in the container (PYTHONPATH) and under pytest
    from main import start_classification_run

    global _status
    errors: list[str] = []
    # run_classification logs connection failures instead of raising: count them as errors
    sink = logger.add(
        lambda m: errors.append(m.record["message"]),
        level="ERROR",
        filter=lambda r: r["thread"].name == RUN_THREAD,
    )
    try:
        start_classification_run(provider, validate)
    except Exception as exc:  # noqa: BLE001 - the outcome is reported through /run/status
        logger.exception("Run failed")
        errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        logger.remove(sink)
        _status = _status.model_copy(
            update={
                "state": "error" if errors else "ok",
                "finished_at": _now(),
                "error": "; ".join(errors) or None,
            }
        )
        _busy.release()


@router.post(
    "/run",
    status_code=202,
    response_model=RunStatus,
    responses={
        403: {"model": ErrorResponse, "description": "Move operations disabled"},
        409: {"model": ErrorResponse, "description": "A run is already in progress"},
    },
    summary="Start a classification run in the background",
)
def start_run(provider: Literal["imap", "gmail", "all"] = "all", validate: bool = False):
    """Run `main.py run --provider <provider> [--validate]`; poll `/run/status` for the outcome.

    `validate=true` is the read-only dry run. A real run moves mail, so it needs `allow_move`.
    """
    global _status
    if not validate and not CONFIG.webhook.allow_move:
        raise HTTPException(status_code=403, detail="Move operations are disabled")
    if not _busy.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A run is already in progress")

    _status = RunStatus(state="running", provider=provider, validate_only=validate, started_at=_now())
    threading.Thread(target=_worker, args=(provider, validate), name=RUN_THREAD, daemon=True).start()
    return _status


@router.get("/run/status", response_model=RunStatus, summary="Outcome of the last run")
def run_status():
    """`idle` before any run since startup, then `running`, `ok` or `error`."""
    return _status
