from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from ..models.pipeline import (
    CodeFinding,
    CodeSpan,
    IncidentContext,
    StageTrace,
    SuspicionScore,
)
from ..repo import static_analysis


def _make_stage_trace(
    *,
    started_at: datetime,
    finished_at: datetime,
    context: IncidentContext,
    findings: List[CodeFinding],
    extra_details: Optional[dict] = None,
) -> StageTrace:
    return StageTrace(
        stage="code_analysis",
        started_at=started_at,
        finished_at=finished_at,
        input_summary=f"incident_id={context.incident.incident_id!r}",
        output_summary=f"findings_count={len(findings)}",
        details={
            "has_stack_traces": bool(context.incident.stack_traces),
            "repo_local_path": context.incident.repo.local_path
            if context.incident.repo
            else None,
            **(extra_details or {}),
        },
    )


def _normalise_relative_path(path: str) -> str:
    """
    Normalise a file path to a POSIX-style relative path for use in `CodeSpan`.
    """
    return Path(path).as_posix()


def _resolve_filesystem_path(
    repo_root: Optional[str],
    frame_path: Optional[str],
) -> Tuple[str, Optional[Path]]:
    """
    Resolve a stack frame file path to a display path and a concrete filesystem path.

    - If `repo_root` is provided, treat `frame_path` as relative to that root.
    - If `frame_path` is absolute and exists, use it directly.
    - If resolution fails, return a display path and `None` for the filesystem path.
    """
    if not frame_path:
        return "<unknown>", None

    raw = Path(frame_path)

    # Prefer interpreting as relative to the repository root when available.
    if repo_root is not None:
        repo_root_path = Path(repo_root)
        candidate = repo_root_path / raw
        if candidate.exists():
            display = _normalise_relative_path(raw.as_posix())
            return display, candidate

    # Fall back to using the raw path if it exists on disk.
    if raw.is_absolute() and raw.exists():
        display = _normalise_relative_path(raw.name)
        return display, raw

    # Resolution failed; keep the original string as a best-effort display path.
    return _normalise_relative_path(frame_path), None


class CodeAnalysisAgent:
    """
    Agent responsible for mapping an `IncidentContext` to concrete code regions.

    The MVP implementation focuses on:
    - Leveraging stack traces to locate source files and line numbers.
    - Using static analysis helpers to construct informative `CodeSpan`s.
    - Enriching findings with enclosing symbol information when available.

    It deliberately avoids any heavy-weight indexing or embedding-based search,
    which are planned for later phases.
    """

    def run(
        self,
        context: IncidentContext,
    ) -> Tuple[List[CodeFinding], StageTrace]:
        started_at = datetime.utcnow()

        findings: List[CodeFinding] = []

        repo_root = context.incident.repo.local_path if context.incident.repo else None

        total_frames = 0
        frames_with_source = 0
        frames_with_symbol = 0

        for trace_index, trace in enumerate(context.incident.stack_traces, start=1):
            for frame_index, frame in enumerate(trace.frames, start=1):
                total_frames += 1

                display_path, fs_path = _resolve_filesystem_path(
                    repo_root=repo_root,
                    frame_path=frame.file_path,
                )

                code_span: CodeSpan
                metadata: dict = {
                    "stack_trace_index": trace_index,
                    "frame_index": frame_index,
                    "stack_trace_error_type": trace.error_type,
                    "stack_trace_message": trace.message,
                }

                enclosing_symbol_dict: Optional[dict] = None

                if fs_path is not None and frame.line_number is not None:
                    try:
                        source = static_analysis.read_source(fs_path)
                        frames_with_source += 1

                        # Localise the runtime error region.
                        code_span = static_analysis.localise_runtime_error_span(
                            source=source,
                            file_path=display_path,
                            line=frame.line_number,
                        )

                        # Attempt to identify the enclosing symbol for richer context.
                        try:
                            tree = static_analysis.parse_module(
                                source, filename=str(display_path)
                            )
                            symbol = static_analysis.find_enclosing_symbol(
                                tree=tree,
                                line=frame.line_number,
                            )
                            if symbol is not None:
                                frames_with_symbol += 1
                                enclosing_symbol_dict = asdict(symbol)
                        except SyntaxError as parse_error:
                            # Fall back to a syntax-error span if parsing fails.
                            code_span = static_analysis.localise_syntax_error_span(
                                source=source,
                                file_path=display_path,
                                error=parse_error,
                            )
                    except OSError:
                        # If we cannot read the file from disk, fall back to
                        # a minimal span using only the stack frame information.
                        code_span = CodeSpan(
                            file_path=display_path,
                            start_line=frame.line_number,
                            end_line=frame.line_number,
                            snippet=frame.code_snippet,
                        )
                else:
                    # No concrete file or line information is available.
                    code_span = CodeSpan(
                        file_path=display_path,
                        start_line=frame.line_number,
                        end_line=frame.line_number,
                        snippet=frame.code_snippet,
                    )

                if enclosing_symbol_dict is not None:
                    metadata["enclosing_symbol"] = enclosing_symbol_dict

                # Heuristic suspicion scoring: prefer frames we could localise
                # precisely in source code, otherwise fall back to a moderate score.
                if fs_path is not None and frame.line_number is not None:
                    suspicion_value = 0.9
                    suspicion_rationale = (
                        "High suspicion: frame mapped to concrete source location "
                        "with enclosing symbol information when available."
                    )
                elif frame.line_number is not None:
                    suspicion_value = 0.7
                    suspicion_rationale = (
                        "Moderate suspicion: stack frame includes a line number but "
                        "source file could not be fully resolved."
                    )
                else:
                    suspicion_value = 0.5
                    suspicion_rationale = (
                        "Lower suspicion: stack frame lacks precise line information."
                    )

                suspicion = SuspicionScore(
                    value=suspicion_value,
                    rationale=suspicion_rationale,
                )

                findings.append(
                    CodeFinding(
                        id=f"trace-{trace_index}-frame-{frame_index}",
                        span=code_span,
                        related_frames=[frame],
                        description=(
                            "Code region derived from incident stack trace; "
                            "mapped to the surrounding source context using "
                            "static analysis helpers where possible."
                        ),
                        kind="unknown",
                        suspicion=suspicion,
                        metadata=metadata,
                    )
                )

        finished_at = datetime.utcnow()

        trace = _make_stage_trace(
            started_at=started_at,
            finished_at=finished_at,
            context=context,
            findings=findings,
            extra_details={
                "total_frames": total_frames,
                "frames_with_source": frames_with_source,
                "frames_with_symbol": frames_with_symbol,
            },
        )

        return findings, trace


__all__ = [
    "CodeAnalysisAgent",
]

