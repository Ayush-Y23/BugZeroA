from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from .incidents import EnvironmentInfo, IncidentInput, RepoReference, StackFrame


class SuspicionScore(BaseModel):
    """
    Encodes how strongly a particular hypothesis or code region is suspected.
    """

    value: float = Field(
        ge=0.0,
        le=1.0,
        description="Normalized suspicion score in [0, 1].",
    )
    rationale: Optional[str] = Field(
        default=None,
        description="Short explanation of how this score was derived.",
    )


class IncidentContext(BaseModel):
    """
    Structured representation of the incident after the understanding stage.
    """

    incident: IncidentInput = Field(
        description="Original incident input payload.",
    )
    primary_error_message: Optional[str] = Field(
        default=None,
        description="Key error message extracted from descriptions, logs, or stack traces.",
    )
    error_codes: List[str] = Field(
        default_factory=list,
        description="Machine-readable error codes, if available (e.g., HTTP 500, custom error IDs).",
    )
    suspected_components: List[str] = Field(
        default_factory=list,
        description="List of component or module identifiers likely related to the incident.",
    )
    environment: Optional[EnvironmentInfo] = Field(
        default=None,
        description="Environment context inferred or copied from the incident.",
    )
    repo: Optional[RepoReference] = Field(
        default=None,
        description="Repository reference associated with the incident.",
    )
    uncertainty: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Overall uncertainty level in [0, 1], where higher means more uncertain.",
    )


class CodeSpan(BaseModel):
    """
    Represents a contiguous region of code within a file.
    """

    file_path: str = Field(
        description="Path to the file relative to the repository root.",
    )
    start_line: Optional[int] = Field(
        default=None,
        description="1-based inclusive starting line number.",
    )
    end_line: Optional[int] = Field(
        default=None,
        description="1-based inclusive ending line number.",
    )
    snippet: Optional[str] = Field(
        default=None,
        description="Optional code snippet corresponding to this span.",
    )


class CodeFinding(BaseModel):
    """
    Result of mapping the incident context to specific code regions.
    """

    id: str = Field(
        description="Stable identifier for this finding within the pipeline trace.",
    )
    span: CodeSpan = Field(
        description="Primary code region associated with this finding.",
    )
    related_frames: List[StackFrame] = Field(
        default_factory=list,
        description="Stack frames that point to or support this finding.",
    )
    description: str = Field(
        description="Natural-language explanation of why this code is suspicious.",
    )
    kind: Optional[Literal["syntax", "type", "logic", "performance", "configuration", "unknown"]] = (
        Field(
            default=None,
            description="High-level category of suspected issue.",
        )
    )
    suspicion: Optional[SuspicionScore] = Field(
        default=None,
        description="How strongly this code region is believed to be related to the incident.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional structured data from static analysis or search.",
    )


class KnowledgeSnippet(BaseModel):
    """
    Documentation or prior-incident snippet retrieved to assist fix generation.
    """

    id: str = Field(
        description="Stable identifier of this snippet in the knowledge store.",
    )
    source: str = Field(
        description="Origin of this snippet, e.g., 'docs', 'README', 'known-error-patterns', 'incident-history'.",
    )
    title: Optional[str] = Field(
        default=None,
        description="Short title or heading for the snippet.",
    )
    content: str = Field(
        description="Full text content of the snippet.",
    )
    score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Relevance score in [0, 1] as returned by the vector store.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (file path, line numbers, tags, etc.).",
    )


class PatchHunk(BaseModel):
    """
    One contiguous diff hunk within a file.
    """

    header: Optional[str] = Field(
        default=None,
        description="Optional unified-diff style hunk header (e.g., '@@ -1,3 +1,4 @@').",
    )
    body: str = Field(
        description="Unified-diff formatted body of the hunk.",
    )


class FilePatch(BaseModel):
    """
    Minimal diff for a single file.
    """

    file_path: str = Field(
        description="Path to the target file relative to the repository root.",
    )
    hunks: List[PatchHunk] = Field(
        default_factory=list,
        description="List of diff hunks that should be applied to this file.",
    )


class ProposedFix(BaseModel):
    """
    Candidate fix proposed by the fix generation agent.
    """

    id: str = Field(
        description="Stable identifier for this proposed fix.",
    )
    title: Optional[str] = Field(
        default=None,
        description="Short human-readable summary of the fix.",
    )
    description: str = Field(
        description="Detailed explanation of the proposed change and rationale.",
    )
    patches: List[FilePatch] = Field(
        default_factory=list,
        description="Collection of file-level patches that together form this fix.",
    )
    based_on_findings: List[str] = Field(
        default_factory=list,
        description="IDs of CodeFindings that motivated this fix.",
    )
    knowledge_snippets: List[KnowledgeSnippet] = Field(
        default_factory=list,
        description="Knowledge snippets that informed this fix.",
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Model-estimated confidence in [0, 1] that this fix resolves the incident without regressions.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional fields, e.g., model ID, temperature, or prompt version.",
    )


class TestCaseResult(BaseModel):
    """
    Result of running a single test case inside the sandbox.
    """

    name: str = Field(
        description="Fully qualified name of the test case (e.g., 'tests/test_module.py::test_something').",
    )
    status: Literal["passed", "failed", "skipped", "xfailed", "xpassed", "error"] = Field(
        description="Outcome of this test case.",
    )
    duration_seconds: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Execution time in seconds, if available.",
    )
    message: Optional[str] = Field(
        default=None,
        description="Short summary or failure message.",
    )
    details: Optional[str] = Field(
        default=None,
        description="Long-form details such as the full traceback or captured logs.",
    )


class TestSummary(BaseModel):
    """
    Aggregated test results for a validation run.
    """

    total: int = Field(
        description="Total number of discovered test cases.",
    )
    passed: int = Field(
        description="Number of passing tests.",
    )
    failed: int = Field(
        description="Number of failing tests.",
    )
    skipped: int = Field(
        description="Number of skipped tests.",
    )
    xfailed: int = Field(
        description="Number of expected failures.",
    )
    xpassed: int = Field(
        description="Number of unexpected passes.",
    )
    errors: int = Field(
        description="Number of tests that errored before assertions.",
    )


class SandboxRunInfo(BaseModel):
    """
    Metadata about a sandboxed validation run.
    """

    started_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the sandbox run started.",
    )
    finished_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the sandbox run finished.",
    )
    command: Optional[str] = Field(
        default=None,
        description="Command that was executed inside the sandbox (e.g., 'pytest').",
    )
    exit_code: Optional[int] = Field(
        default=None,
        description="Exit code returned by the sandboxed command.",
    )
    logs: Optional[str] = Field(
        default=None,
        description="Combined stdout/stderr logs from the sandbox run.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional backend-specific metadata (container ID, resource usage, etc.).",
    )


class ValidationResult(BaseModel):
    """
    Outcome of validating a proposed fix in a sandbox.
    """

    status: Literal["not_run", "passed", "failed", "errored", "partial"] = Field(
        description="High-level status of the validation stage.",
    )
    baseline_status: Optional[Literal["unknown", "passing", "failing"]] = Field(
        default=None,
        description="Status of the baseline run without the fix, if such a run was performed.",
    )
    test_summary: Optional[TestSummary] = Field(
        default=None,
        description="Aggregated test counts.",
    )
    test_results: List[TestCaseResult] = Field(
        default_factory=list,
        description="Per-test case results.",
    )
    sandbox: Optional[SandboxRunInfo] = Field(
        default=None,
        description="Details about the sandbox runtime execution.",
    )
    regressions_detected: bool = Field(
        default=False,
        description="Whether the validation detected regressions compared to the baseline, if available.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Additional human-readable notes about this validation outcome.",
    )


class StageTrace(BaseModel):
    """
    Trace information for a single pipeline stage.
    """

    stage: str = Field(
        description="Identifier of the stage (e.g., 'incident_understanding', 'code_analysis').",
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when this stage started.",
    )
    finished_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when this stage finished.",
    )
    input_summary: Optional[str] = Field(
        default=None,
        description="Short summary of the inputs given to this stage.",
    )
    output_summary: Optional[str] = Field(
        default=None,
        description="Short summary of the outputs produced by this stage.",
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured details for debugging or audit.",
    )


class ResolutionReport(BaseModel):
    """
    Final structured report produced by the orchestrator.
    """

    incident_id: Optional[str] = Field(
        default=None,
        description="Identifier of the incident that this report corresponds to.",
    )
    incident: IncidentInput = Field(
        description="Original incident input for reference.",
    )
    context: IncidentContext = Field(
        description="Structured interpretation of the incident.",
    )
    findings: List[CodeFinding] = Field(
        default_factory=list,
        description="Ranked list of code findings considered during analysis.",
    )
    chosen_fix: Optional[ProposedFix] = Field(
        default=None,
        description="Fix that was selected for sandbox validation and recommendation, if any.",
    )
    alternative_fixes: List[ProposedFix] = Field(
        default_factory=list,
        description="Other candidate fixes that were considered but not selected.",
    )
    validation: Optional[ValidationResult] = Field(
        default=None,
        description="Outcome of validating the chosen fix in a sandbox.",
    )
    root_cause_explanation: Optional[str] = Field(
        default=None,
        description="Human-readable explanation of the root cause.",
    )
    summary: Optional[str] = Field(
        default=None,
        description="High-level summary of what happened and how it was addressed.",
    )
    risk_level: Optional[Literal["low", "medium", "high", "unknown"]] = Field(
        default=None,
        description="Estimated deployment risk associated with applying the chosen fix.",
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence in [0, 1] that the fix resolves the incident without regressions.",
    )
    stage_traces: Sequence[StageTrace] = Field(
        default_factory=list,
        description="Trace information for each pipeline stage executed.",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when this report object was created.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional implementation-specific metadata.",
    )


__all__ = [
    "SuspicionScore",
    "IncidentContext",
    "CodeSpan",
    "CodeFinding",
    "KnowledgeSnippet",
    "PatchHunk",
    "FilePatch",
    "ProposedFix",
    "TestCaseResult",
    "TestSummary",
    "SandboxRunInfo",
    "ValidationResult",
    "StageTrace",
    "ResolutionReport",
]

