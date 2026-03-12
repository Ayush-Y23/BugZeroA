from __future__ import annotations

from datetime import datetime
from typing import List, Sequence, Tuple

from ..logging_utils import get_logger, log_pipeline_event, log_stage_trace
from ..models.incidents import IncidentInput
from ..models.pipeline import (
    CodeFinding,
    IncidentContext,
    KnowledgeSnippet,
    ProposedFix,
    ResolutionReport,
    StageTrace,
    TestSummary,
    ValidationResult,
)
from .code_analysis import CodeAnalysisAgent
from .fix_generation import FixGenerationAgent
from .incident_understanding import IncidentUnderstandingAgent
from .knowledge_retrieval import KnowledgeRetrievalAgent
from .reporting import ReportingAgent


def _make_stage_trace(
    stage: str,
    started_at: datetime,
    finished_at: datetime,
    input_summary: str | None = None,
    output_summary: str | None = None,
    details: dict | None = None,
) -> StageTrace:
    return StageTrace(
        stage=stage,
        started_at=started_at,
        finished_at=finished_at,
        input_summary=input_summary,
        output_summary=output_summary,
        details=details or {},
    )


def _run_code_analysis(
    context: IncidentContext,
) -> Tuple[List[CodeFinding], StageTrace]:
    """
    Run the code analysis stage using `CodeAnalysisAgent`.

    This thin wrapper exists so that the orchestrator retains a simple helper
    function interface while delegating the actual analysis logic to the agent
    implementation.
    """
    agent = CodeAnalysisAgent()
    return agent.run(context)


def _run_knowledge_retrieval(
    context: IncidentContext,
    findings: Sequence[CodeFinding],
) -> Tuple[List[KnowledgeSnippet], StageTrace]:
    agent = KnowledgeRetrievalAgent()
    return agent.run(context, findings)


def _run_fix_generation(
    context: IncidentContext,
    findings: Sequence[CodeFinding],
    snippets: Sequence[KnowledgeSnippet],
) -> Tuple[List[ProposedFix], StageTrace]:
    agent = FixGenerationAgent()
    return agent.run(context, findings, snippets)


def _run_validation(
    context: IncidentContext,
    chosen_fix: ProposedFix | None,
) -> Tuple[ValidationResult | None, StageTrace]:
    started_at = datetime.utcnow()

    # Full sandboxed validation is out of scope for the MVP orchestrator.
    # Return a minimal "not_run" ValidationResult when a fix exists; if no
    # fix was chosen, skip validation entirely.
    validation: ValidationResult | None
    if chosen_fix is None:
        validation = None
        output_summary = "validation_skipped_no_fix"
    else:
        validation = ValidationResult(
            status="not_run",
            baseline_status="unknown",
            test_summary=TestSummary(
                total=0,
                passed=0,
                failed=0,
                skipped=0,
                xfailed=0,
                xpassed=0,
                errors=0,
            ),
            test_results=[],
            sandbox=None,
            regressions_detected=False,
            notes=(
                "Validation has not been implemented yet; this is a stub "
                "result produced by the MVP orchestrator."
            ),
        )
        output_summary = "validation_status=not_run"

    finished_at = datetime.utcnow()

    trace = _make_stage_trace(
        stage="validation",
        started_at=started_at,
        finished_at=finished_at,
        input_summary=f"has_fix={chosen_fix is not None}",
        output_summary=output_summary,
        details={},
    )

    return validation, trace


def _run_reporting(
    context: IncidentContext,
    findings: Sequence[CodeFinding],
    chosen_fix: ProposedFix | None,
    alternative_fixes: Sequence[ProposedFix],
    validation: ValidationResult | None,
    traces: Sequence[StageTrace],
) -> Tuple[ResolutionReport, StageTrace]:
    """
    Run the reporting stage using `ReportingAgent`.

    This thin wrapper mirrors the helper structure used for other stages while
    delegating the actual report composition logic to the dedicated agent.
    """
    agent = ReportingAgent()
    return agent.run(
        context=context,
        findings=findings,
        chosen_fix=chosen_fix,
        alternative_fixes=alternative_fixes,
        validation=validation,
        traces=traces,
    )


def run_incident_resolution(incident: IncidentInput) -> ResolutionReport:
    """
    Run the full multi-stage incident-to-fix workflow.

    This implementation wires together agents that operate on the structured
    incident input. The incident understanding stage is handled by
    `IncidentUnderstandingAgent`, which can be backed by an external LLM or a
    deterministic heuristic implementation when no LLM client is provided.
    """
    logger = get_logger("orchestrator")
    incident_id = incident.incident_id

    log_pipeline_event(
        logger,
        event="pipeline_started",
        incident_id=incident_id,
        payload={
            "title": incident.title,
            "has_stack_traces": bool(incident.stack_traces),
            "has_logs": bool(incident.logs),
        },
    )

    all_traces: List[StageTrace] = []

    incident_agent = IncidentUnderstandingAgent()
    context, trace = incident_agent.run(incident)
    all_traces.append(trace)
    log_stage_trace(logger, trace=trace, incident_id=incident_id)

    findings, trace = _run_code_analysis(context)
    all_traces.append(trace)
    log_stage_trace(logger, trace=trace, incident_id=incident_id)

    snippets, trace = _run_knowledge_retrieval(context, findings)
    all_traces.append(trace)
    log_stage_trace(logger, trace=trace, incident_id=incident_id)

    fixes, trace = _run_fix_generation(context, findings, snippets)
    all_traces.append(trace)
    log_stage_trace(logger, trace=trace, incident_id=incident_id)

    chosen_fix: ProposedFix | None
    alternative_fixes: List[ProposedFix]
    if fixes:
        chosen_fix = fixes[0]
        alternative_fixes = list(fixes[1:])
    else:
        chosen_fix = None
        alternative_fixes = []

    validation, trace = _run_validation(context, chosen_fix)
    all_traces.append(trace)
    log_stage_trace(logger, trace=trace, incident_id=incident_id)

    report, reporting_trace = _run_reporting(
        context=context,
        findings=findings,
        chosen_fix=chosen_fix,
        alternative_fixes=alternative_fixes,
        validation=validation,
        traces=all_traces,
    )
    all_traces.append(reporting_trace)
    log_stage_trace(logger, trace=reporting_trace, incident_id=incident_id)

    # Ensure the final report contains the complete trace sequence.
    report.stage_traces = all_traces

    log_pipeline_event(
        logger,
        event="pipeline_completed",
        incident_id=incident_id,
        payload={
            "has_fix": report.chosen_fix is not None,
            "findings_count": len(report.findings),
            "risk_level": report.risk_level,
        },
    )

    return report

