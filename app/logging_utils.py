from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from .models.pipeline import StageTrace


_LOGGER_CONFIGURED = False
_ROOT_LOGGER_NAME = "incident_agent"


class StructuredJsonFormatter(logging.Formatter):
    """
    Minimal JSON formatter for structured logs.

    The formatter keeps the payload intentionally small and focuses on fields
    that are useful when debugging the multi-stage pipeline in production.
    """

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "logger": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }

        extra_data = getattr(record, "extra_data", None)
        if isinstance(extra_data, dict):
            payload.update(extra_data)

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _configure_root_logger() -> None:
    """
    Configure the root application logger once.
    """

    global _LOGGER_CONFIGURED
    if _LOGGER_CONFIGURED:
        return

    logger = logging.getLogger(_ROOT_LOGGER_NAME)
    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJsonFormatter())
    logger.addHandler(handler)

    # Avoid double-logging through the Python root logger in typical FastAPI/Uvicorn setups.
    logger.propagate = False

    _LOGGER_CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a namespaced logger for the incident agent service.
    """

    _configure_root_logger()
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")


def _serialise_datetime(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat(timespec="milliseconds") + "Z"


def log_stage_trace(
    logger: logging.Logger,
    *,
    trace: StageTrace,
    incident_id: Optional[str] = None,
    extra_details: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Emit a structured log entry for a single pipeline stage trace.
    """

    logger.info(
        "stage_completed",
        extra={
            "extra_data": {
                "event": "stage_trace",
                "stage": trace.stage,
                "incident_id": incident_id,
                "started_at": _serialise_datetime(trace.started_at),
                "finished_at": _serialise_datetime(trace.finished_at),
                "input_summary": trace.input_summary,
                "output_summary": trace.output_summary,
                "details": trace.details,
                **(extra_details or {}),
            }
        },
    )


def log_pipeline_event(
    logger: logging.Logger,
    *,
    event: str,
    incident_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Emit a high-level structured log event related to the incident pipeline.
    """

    logger.info(
        event,
        extra={
            "extra_data": {
                "event": event,
                "incident_id": incident_id,
                **(payload or {}),
            }
        },
    )


