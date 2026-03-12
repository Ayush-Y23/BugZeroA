from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Tuple

from ..models.incidents import IncidentInput, StackFrame
from ..models.pipeline import EnvironmentInfo, IncidentContext, RepoReference, StageTrace


class IncidentUnderstandingLLM(Protocol):
    """
    Minimal protocol for an LLM client that can analyze an incident.

    This stays deliberately generic so that different providers (OpenAI, Anthropic,
    local models, etc.) can be wired in without changing the agent implementation.
    """

    def __call__(self, prompt: str) -> str:  # pragma: no cover - protocol definition
        ...


def _make_stage_trace(
    *,
    stage: str,
    started_at: datetime,
    finished_at: datetime,
    input_summary: str | None = None,
    output_summary: str | None = None,
    details: Dict[str, Any] | None = None,
) -> StageTrace:
    return StageTrace(
        stage=stage,
        started_at=started_at,
        finished_at=finished_at,
        input_summary=input_summary,
        output_summary=output_summary,
        details=details or {},
    )


def _summarize_incident(incident: IncidentInput) -> str:
    title = incident.title or "(no title)"
    desc = incident.description.strip()
    desc_preview = desc[:120] + ("…" if len(desc) > 120 else "")
    return f"title={title!r}, description_preview={desc_preview!r}"


def _extract_primary_error_message_from_structured(incident: IncidentInput) -> str | None:
    if incident.stack_traces:
        for trace in incident.stack_traces:
            if trace.message:
                return trace.message
    return incident.description.strip() or None


def _extract_suspected_components_from_frames(frames: Iterable[StackFrame]) -> List[str]:
    components: List[str] = []
    for frame in frames:
        if frame.module:
            components.append(frame.module)
        elif frame.file_path:
            components.append(frame.file_path)

    seen: set[str] = set()
    unique: List[str] = []
    for component in components:
        if component not in seen:
            seen.add(component)
            unique.append(component)
    return unique


def _build_llm_prompt(incident: IncidentInput) -> str:
    """
    Construct a prompt that asks the LLM to normalize the incident into
    the IncidentContext fields.
    """
    lines: List[str] = []
    lines.append(
        "You are an assistant that understands software incidents and "
        "normalizes them into a structured schema."
    )
    lines.append("")
    lines.append("You will be given a JSON payload representing an incident.")
    lines.append("Return a JSON object with the following fields:")
    lines.append(
        "- primary_error_message: string or null "
        "(key error message from descriptions/logs/stack traces)"
    )
    lines.append(
        "- error_codes: list of strings (HTTP status codes, error IDs, etc.; can be empty)"
    )
    lines.append(
        "- suspected_components: list of strings "
        "(module names, service names, or file paths; most likely related components)"
    )
    lines.append(
        "- environment_overrides: object with optional keys "
        "python_version, os, dependencies, extra (same semantics as EnvironmentInfo)"
    )
    lines.append(
        "- repo_overrides: object with optional keys "
        "local_path, git_url, branch, commit (same semantics as RepoReference)"
    )
    lines.append(
        "- uncertainty: float between 0.0 and 1.0 "
        "(higher means more uncertain about the interpretation)"
    )
    lines.append("")
    lines.append("Respond with ONLY valid JSON, no markdown, no comments.")
    lines.append("")
    payload = incident.model_dump()
    lines.append("Incident payload:")
    lines.append(json.dumps(payload, ensure_ascii=False))
    return "\n".join(lines)


def _safe_json_loads(content: str) -> Dict[str, Any] | None:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


class IncidentUnderstandingAgent:
    """
    LLM-backed incident understanding agent.

    This agent converts a raw `IncidentInput` (ticket description, logs, stack
    traces, environment, repo reference) into an `IncidentContext`.

    It is designed to be LLM-first, but falls back to a deterministic heuristic
    implementation if an LLM client is not provided or produces unusable output.
    """

    def __init__(self, llm: Optional[IncidentUnderstandingLLM] = None) -> None:
        self._llm = llm

    def run(self, incident: IncidentInput) -> Tuple[IncidentContext, StageTrace]:
        started_at = datetime.utcnow()

        # Try LLM-based understanding first, then fall back to heuristics.
        if self._llm is not None:
            context = self._run_with_llm(incident)
        else:
            context = self._run_with_heuristics(incident)

        finished_at = datetime.utcnow()

        trace = _make_stage_trace(
            stage="incident_understanding",
            started_at=started_at,
            finished_at=finished_at,
            input_summary=_summarize_incident(incident),
            output_summary=(
                f"primary_error_message={context.primary_error_message!r}, "
                f"suspected_components={context.suspected_components!r}"
            ),
            details={
                "stack_trace_count": len(incident.stack_traces),
                "log_entry_count": len(incident.logs),
                "used_llm": self._llm is not None,
            },
        )

        return context, trace

    # Internal helpers -------------------------------------------------

    def _run_with_heuristics(self, incident: IncidentInput) -> IncidentContext:
        primary_error_message = _extract_primary_error_message_from_structured(incident)

        all_frames: List[StackFrame] = []
        for trace in incident.stack_traces:
            all_frames.extend(trace.frames)

        suspected_components = _extract_suspected_components_from_frames(all_frames)

        # Slightly adjust uncertainty depending on how much structured signal we have.
        if incident.stack_traces:
            base_uncertainty = 0.45
        elif incident.logs:
            base_uncertainty = 0.55
        else:
            base_uncertainty = 0.7

        return IncidentContext(
            incident=incident,
            primary_error_message=primary_error_message,
            error_codes=[],
            suspected_components=suspected_components,
            environment=incident.environment,
            repo=incident.repo,
            uncertainty=base_uncertainty,
        )

    def _run_with_llm(self, incident: IncidentInput) -> IncidentContext:
        assert self._llm is not None

        prompt = _build_llm_prompt(incident)
        raw_response = self._llm(prompt)
        data = _safe_json_loads(raw_response)

        if not isinstance(data, dict):
            # Fall back to heuristics if we cannot parse a valid JSON object.
            return self._run_with_heuristics(incident)

        primary_error_message = (
            data.get("primary_error_message")
            or _extract_primary_error_message_from_structured(incident)
        )

        error_codes_raw = data.get("error_codes") or []
        if isinstance(error_codes_raw, list):
            error_codes = [str(code) for code in error_codes_raw]
        else:
            error_codes = []

        suspected_components_raw = data.get("suspected_components") or []
        if isinstance(suspected_components_raw, list):
            suspected_components = [str(component) for component in suspected_components_raw]
        else:
            suspected_components = []

        # Environment overrides
        environment_overrides = data.get("environment_overrides") or {}
        environment = incident.environment
        if isinstance(environment_overrides, dict):
            environment = self._merge_environment(incident.environment, environment_overrides)

        # Repo overrides
        repo_overrides = data.get("repo_overrides") or {}
        repo = incident.repo
        if isinstance(repo_overrides, dict):
            repo = self._merge_repo(incident.repo, repo_overrides)

        # Uncertainty
        uncertainty_raw = data.get("uncertainty")
        try:
            uncertainty = float(uncertainty_raw)
        except (TypeError, ValueError):
            uncertainty = None

        if uncertainty is not None:
            # Clamp into [0.0, 1.0]
            uncertainty = max(0.0, min(1.0, uncertainty))
        else:
            # Default based on available signal.
            if incident.stack_traces:
                uncertainty = 0.4
            elif incident.logs:
                uncertainty = 0.55
            else:
                uncertainty = 0.75

        # If the LLM omitted suspected components, fall back to a stack-trace
        # based heuristic to avoid losing useful signals.
        if not suspected_components:
            all_frames: List[StackFrame] = []
            for trace in incident.stack_traces:
                all_frames.extend(trace.frames)
            suspected_components = _extract_suspected_components_from_frames(all_frames)

        return IncidentContext(
            incident=incident,
            primary_error_message=primary_error_message,
            error_codes=error_codes,
            suspected_components=suspected_components,
            environment=environment,
            repo=repo,
            uncertainty=uncertainty,
        )

    @staticmethod
    def _merge_environment(
        base: Optional[EnvironmentInfo], overrides: Dict[str, Any]
    ) -> EnvironmentInfo:
        base = base or EnvironmentInfo()
        return EnvironmentInfo(
            python_version=str(overrides.get("python_version") or base.python_version)
            if overrides.get("python_version") is not None
            else base.python_version,
            os=str(overrides.get("os") or base.os)
            if overrides.get("os") is not None
            else base.os,
            dependencies={
                **base.dependencies,
                **(
                    overrides.get("dependencies")
                    if isinstance(overrides.get("dependencies"), dict)
                    else {}
                ),
            },
            extra={
                **base.extra,
                **(
                    overrides.get("extra")
                    if isinstance(overrides.get("extra"), dict)
                    else {}
                ),
            },
        )

    @staticmethod
    def _merge_repo(
        base: Optional[RepoReference], overrides: Dict[str, Any]
    ) -> RepoReference:
        base = base or RepoReference()
        # We intentionally do not coerce to str here in case callers want to use
        # richer types later; for now, this mirrors the Pydantic model fields.
        return RepoReference(
            local_path=overrides.get("local_path", base.local_path),
            git_url=overrides.get("git_url", base.git_url),
            branch=overrides.get("branch", base.branch),
            commit=overrides.get("commit", base.commit),
        )


__all__ = [
    "IncidentUnderstandingAgent",
    "IncidentUnderstandingLLM",
]

