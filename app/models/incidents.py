from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class RepoReference(BaseModel):
    """
    Minimal reference to the repository under investigation.
    Can be extended later with GitHub-specific fields.
    """

    local_path: Optional[str] = Field(
        default=None,
        description="Absolute path to a locally available checkout of the repository.",
    )
    git_url: Optional[str] = Field(
        default=None,
        description="Remote Git URL for the repository (if available).",
    )
    branch: Optional[str] = Field(
        default=None,
        description="Branch name associated with the incident.",
    )
    commit: Optional[str] = Field(
        default=None,
        description="Specific commit SHA associated with the incident.",
    )


class EnvironmentInfo(BaseModel):
    """
    Captures runtime and deployment environment details for the incident.
    """

    python_version: Optional[str] = Field(
        default=None,
        description="Python version where the incident occurred, e.g. '3.11.5'.",
    )
    os: Optional[str] = Field(
        default=None,
        description="Operating system details, e.g. 'linux', 'windows-10', 'ubuntu-22.04'.",
    )
    dependencies: Dict[str, str] = Field(
        default_factory=dict,
        description="Dependency versions, typically a subset of installed packages.",
    )
    extra: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary additional environment metadata.",
    )


class StackFrame(BaseModel):
    """
    Single frame from a stack trace associated with the incident.
    """

    file_path: Optional[str] = Field(
        default=None,
        description="File path (relative to repo root if possible).",
    )
    line_number: Optional[int] = Field(
        default=None,
        description="Line number within the file.",
    )
    function: Optional[str] = Field(
        default=None,
        description="Function or method name where the frame occurred.",
    )
    module: Optional[str] = Field(
        default=None,
        description="Logical module or component name.",
    )
    code_snippet: Optional[str] = Field(
        default=None,
        description="Optional short snippet or line content for additional context.",
    )


class StackTrace(BaseModel):
    """
    Structured representation of a stack trace.
    """

    frames: List[StackFrame] = Field(
        default_factory=list,
        description="Ordered list of frames from oldest to newest.",
    )
    error_type: Optional[str] = Field(
        default=None,
        description="High-level error type or exception name, e.g. 'ValueError'.",
    )
    message: Optional[str] = Field(
        default=None,
        description="Primary error message associated with the stack trace.",
    )
    raw: Optional[str] = Field(
        default=None,
        description="Raw textual representation of the stack trace as provided.",
    )


class LogEntry(BaseModel):
    """
    Individual log entry that may be relevant to the incident.
    """

    timestamp: Optional[datetime] = Field(
        default=None,
        description="Timestamp of this log entry, if available.",
    )
    level: Optional[Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]] = Field(
        default=None,
        description="Log severity level.",
    )
    message: str = Field(
        description="Human-readable log message.",
    )
    logger: Optional[str] = Field(
        default=None,
        description="Logger name or category, if available.",
    )
    extra: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured fields parsed from the log (e.g., JSON payload).",
    )


class IncidentInput(BaseModel):
    """
    Top-level model accepted by the incident resolution API.
    """

    incident_id: Optional[str] = Field(
        default=None,
        description="Optional external identifier for the incident (ticket ID, alert ID, etc.).",
    )
    title: Optional[str] = Field(
        default=None,
        description="Short summary of the incident.",
    )
    description: str = Field(
        description="Free-form textual description of what went wrong.",
    )
    logs: List[LogEntry] = Field(
        default_factory=list,
        description="Relevant logs leading up to and during the incident.",
    )
    stack_traces: List[StackTrace] = Field(
        default_factory=list,
        description="Zero or more stack traces captured for this incident.",
    )
    environment: Optional[EnvironmentInfo] = Field(
        default=None,
        description="Runtime and deployment environment details.",
    )
    repo: Optional[RepoReference] = Field(
        default=None,
        description="Reference to the code repository related to this incident.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary additional metadata (alert source, tags, etc.).",
    )


__all__ = [
    "RepoReference",
    "EnvironmentInfo",
    "StackFrame",
    "StackTrace",
    "LogEntry",
    "IncidentInput",
]

