from __future__ import annotations

from fastapi import APIRouter

from ..agents.orchestrator import run_incident_resolution
from ..models.incidents import IncidentInput
from ..models.pipeline import ResolutionReport


router = APIRouter()


@router.post(
    "/resolve",
    response_model=ResolutionReport,
    summary="Run the incident resolution pipeline for a given incident.",
    tags=["incidents"],
)
def resolve_incident(incident: IncidentInput) -> ResolutionReport:
    """
    Resolve an incident using the multi-stage incident-to-fix pipeline.
    """
    return run_incident_resolution(incident)

