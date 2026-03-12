from __future__ import annotations

from fastapi import FastAPI

from .routes import incidents


app = FastAPI(
    title="Autonomous Incident Fix Agent",
    version="0.1.0",
    description=(
        "Service that accepts incident information and runs a staged agent "
        "pipeline to analyze and propose minimal fixes."
    ),
)


app.include_router(incidents.router, prefix="/incidents")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """
    Lightweight liveness/readiness probe for the service.
    """
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    """
    Simple root endpoint to verify that the service is running.
    """
    return {"service": "autonomous-incident-fix-agent", "status": "ok"}

