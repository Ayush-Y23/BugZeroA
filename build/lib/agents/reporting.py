from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence, Tuple

from ..models.pipeline import (
    CodeFinding,
    IncidentContext,
    ProposedFix,
    ResolutionReport,
    StageTrace,
    ValidationResult,
)


def _make_stage_trace(
    *,
    started_at: datetime,
    finished_at: datetime,
    findings_count: int,
    has_fix: bool,
) -> StageTrace:
    return StageTrace(
        stage="reporting",
        started_at=started_at,
        finished_at=finished_at,
        input_summary=f"findings_count={findings_count}, has_fix={has_fix}",
        output_summary="resolution_report_created",
        details={},
    )


def _derive_risk_level(validation: Optional[ValidationResult], has_fix: bool) -> str:
    """
    Derive a coarse-grained deployment risk level based on validation outcome.

    The heuristics are intentionally conservative for the MVP:
    - If no fix is proposed, risk is "unknown".
    - If validation reports regressions or an explicit failure, risk is "high".
    - If validation passed without regressions, risk is "low".
    - If validation did not run, risk is "medium" when a fix exists.
    """
    if not has_fix:
        return "unknown"

    if validation is None:
        return "medium"

    if validation.regressions_detected or validation.status in {"failed", "errored"}:
        return "high"

    if validation.status == "passed":
        return "low"

    # Covers "not_run" and "partial".
    return "medium"


def _derive_confidence(
    chosen_fix: Optional[ProposedFix],
    validation: Optional[ValidationResult],
) -> Optional[float]:
    """
    Derive an overall confidence score that the incident is resolved.

    The MVP reuses the fix-level confidence when available and adjusts it
    slightly based on the validation outcome.
    """
    if chosen_fix is None:
        return None

    base = chosen_fix.confidence if chosen_fix.confidence is not None else 0.3

    if validation is None:
        return base

    if validation.regressions_detected or validation.status in {"failed", "errored"}:
        return max(0.05, base * 0.3)

    if validation.status == "passed":
        return min(0.95, base + 0.2)

    # For "partial" or "not_run", keep the base estimate.
    return base


def _build_root_cause_explanation(
    context: IncidentContext,
    findings: Sequence[CodeFinding],
) -> str:
    if context.primary_error_message:
        prefix = (
            "Preliminary root cause based on the primary error message and "
            "stack-trace-derived code regions: "
        )
        details = context.primary_error_message
    else:
        prefix = (
            "Root cause could not be precisely determined; this explanation "
            "summarises the most suspicious code regions inspected."
        )
        details = ""

    if findings:
        top = findings[0]
        location = top.span.file_path or "<unknown file>"
        if top.span.start_line is not None:
            location = f"{location}:{top.span.start_line}"
        location_fragment = f" The most suspicious region is around {location}."
    else:
        location_fragment = ""

    return (prefix + details).strip() + location_fragment


def _build_summary_paragraph(
    *,
    context: IncidentContext,
    findings: Sequence[CodeFinding],
    chosen_fix: Optional[ProposedFix],
    validation: Optional[ValidationResult],
    risk_level: str,
) -> str:
    parts: List[str] = []

    title = context.incident.title or "Unnamed incident"
    parts.append(
        f"The incident '{title}' was processed by the multi-stage "
        "incident-to-fix pipeline."
    )

    parts.append(
        f"Code analysis identified {len(findings)} suspicious code region(s) "
        "derived primarily from stack traces."
    )

    if chosen_fix is None:
        parts.append(
            "No concrete code change was proposed; the report focuses on "
            "highlighting suspicious locations for manual investigation."
        )
    else:
        parts.append(
            "A minimal, human-auditable fix was proposed that annotates one "
            "of the suspicious regions with an investigation comment."
        )

    if validation is None:
        parts.append("Sandboxed validation was not executed in this MVP build.")
    else:
        parts.append(
            f"Validation stage completed with status '{validation.status}'."
        )

    parts.append(f"The overall deployment risk is assessed as '{risk_level}'.")

    return " ".join(parts)


class ReportingAgent:
    """
    Agent responsible for composing the final `ResolutionReport`.

    The MVP implementation focuses on:
    - Turning structured pipeline artefacts into a human-readable summary.
    - Providing a coarse risk level and confidence score.
    - Capturing the full stage trace for auditability.
    """

    def run(
        self,
        *,
        context: IncidentContext,
        findings: Sequence[CodeFinding],
        chosen_fix: Optional[ProposedFix],
        alternative_fixes: Sequence[ProposedFix],
        validation: Optional[ValidationResult],
        traces: Sequence[StageTrace],
    ) -> Tuple[ResolutionReport, StageTrace]:
        started_at = datetime.utcnow()

        has_fix = chosen_fix is not None
        risk_level = _derive_risk_level(validation, has_fix=has_fix)
        confidence = _derive_confidence(chosen_fix, validation)

        root_cause_explanation = _build_root_cause_explanation(context, findings)
        summary = _build_summary_paragraph(
            context=context,
            findings=findings,
            chosen_fix=chosen_fix,
            validation=validation,
            risk_level=risk_level,
        )

        report = ResolutionReport(
            incident_id=context.incident.incident_id,
            incident=context.incident,
            context=context,
            findings=list(findings),
            chosen_fix=chosen_fix,
            alternative_fixes=list(alternative_fixes),
            validation=validation,
            root_cause_explanation=root_cause_explanation,
            summary=summary,
            risk_level=risk_level,  # type: ignore[assignment]
            confidence=confidence,
            stage_traces=list(traces),
            metadata={},
        )

        finished_at = datetime.utcnow()
        trace = _make_stage_trace(
            started_at=started_at,
            finished_at=finished_at,
            findings_count=len(findings),
            has_fix=has_fix,
        )

        return report, trace


__all__ = [
    "ReportingAgent",
]

