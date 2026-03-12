from __future__ import annotations

from datetime import datetime
import re
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from ..models.pipeline import (
    CodeFinding,
    FilePatch,
    IncidentContext,
    KnowledgeSnippet,
    PatchHunk,
    ProposedFix,
    StageTrace,
)


def _make_stage_trace(
    *,
    started_at: datetime,
    finished_at: datetime,
    findings: Sequence[CodeFinding],
    snippets: Sequence[KnowledgeSnippet],
    fixes: Sequence[ProposedFix],
) -> StageTrace:
    return StageTrace(
        stage="fix_generation",
        started_at=started_at,
        finished_at=finished_at,
        input_summary=(
            f"findings_count={len(findings)}, snippets_count={len(snippets)}"
        ),
        output_summary=f"proposed_fixes_count={len(fixes)}",
        details={},
    )


def _resolve_filesystem_path(
    repo_root: Optional[str],
    logical_path: str,
) -> Optional[Path]:
    """
    Resolve a logical file path from a `CodeSpan` to a concrete filesystem path.

    The implementation mirrors the assumptions used in the code analysis stage:
    - When a repository root is available, treat the logical path as relative
      to that root.
    - Otherwise, fall back to interpreting the logical path as an absolute or
      current-working-directory-relative path.
    """
    if repo_root:
        candidate = Path(repo_root) / logical_path
        if candidate.exists():
            return candidate

    candidate = Path(logical_path)
    if candidate.exists():
        return candidate

    return None


def _build_investigation_comment(
    context: IncidentContext,
    finding: CodeFinding,
) -> str:
    """
    Construct a concise, human-readable comment describing why this region is
    being marked for investigation.
    """
    parts: List[str] = ["TODO: Investigate incident-related issue here."]

    if context.primary_error_message:
        parts.append(f"Primary error: {context.primary_error_message}")

    if finding.metadata.get("stack_trace_error_type"):
        parts.append(
            f"Error type: {finding.metadata['stack_trace_error_type']}"
        )

    return " ".join(parts)


def _build_bytes_like_mismatch_patch(
    *,
    context: IncidentContext,
    fs_path: Path,
    logical_path: str,
    source: str,
    finding: CodeFinding,
) -> Optional[FilePatch]:
    """
    Attempt a targeted fix for the classic
    "a bytes-like object is required, not 'str'" runtime error.

    This heuristic looks for usages of `bcrypt` in the same file and, when a
    variable named `password` is passed without encoding, wraps that variable
    in `.encode("utf-8")`. The goal is to propose a minimal, concrete change
    while keeping the behaviour easy to audit.
    """
    primary_error = (context.primary_error_message or "").lower()
    if "bytes-like object is required, not 'str'" not in primary_error:
        return None

    lines = source.splitlines()
    if not lines:
        return None

    bcrypt_line_index: Optional[int] = None

    for i, line in enumerate(lines):
        if "bcrypt." in line and "password" in line and ".encode(" not in line:
            bcrypt_line_index = i
            break

    if bcrypt_line_index is None:
        return None

    original_line = lines[bcrypt_line_index]

    # Perform a conservative substitution: only the first occurrence of the
    # bare word "password" is wrapped in `.encode("utf-8")`.
    new_line, count = re.subn(
        r"\bpassword\b",
        "password.encode('utf-8')",
        original_line,
        count=1,
    )
    if count == 0 or new_line == original_line:
        return None

    line_no = bcrypt_line_index + 1

    header = f"@@ -{line_no},1 +{line_no},1 @@"
    body_lines = [
        f"-{original_line}",
        f"+{new_line}",
    ]

    return FilePatch(
        file_path=logical_path,
        hunks=[
            PatchHunk(
                header=header,
                body="\n".join(body_lines),
            )
        ],
    )


def _build_file_patch_for_finding(
    *,
    context: IncidentContext,
    finding: CodeFinding,
) -> Optional[FilePatch]:
    """
    Build a minimal unified-diff style `FilePatch` for a given finding.

    The function first attempts a targeted fix for well-known error patterns
    (e.g., bytes/str mismatches around bcrypt). If no specialised fix applies,
    it falls back to inserting a single investigation comment near the
    suspected error location.
    """
    span = finding.span
    if not span.file_path:
        return None

    repo_root = (
        context.incident.repo.local_path if context.incident.repo else None
    )
    fs_path = _resolve_filesystem_path(repo_root, span.file_path)
    if fs_path is None:
        return None

    try:
        source = fs_path.read_text(encoding="utf-8")
    except OSError:
        return None

    # First, attempt a targeted fix for bytes/str mismatch incidents that
    # involve bcrypt usage.
    specialised_patch = _build_bytes_like_mismatch_patch(
        context=context,
        fs_path=fs_path,
        logical_path=span.file_path,
        source=source,
        finding=finding,
    )
    if specialised_patch is not None:
        return specialised_patch

    lines = source.splitlines()
    if not lines:
        return None

    # Prefer the start of the `CodeSpan` when available; otherwise, use the
    # first related frame's line number or default to the first line.
    if span.start_line is not None and span.start_line > 0:
        insert_line = span.start_line
    elif finding.related_frames and finding.related_frames[0].line_number:
        insert_line = finding.related_frames[0].line_number  # type: ignore[assignment]
    else:
        insert_line = 1

    # Clamp to the bounds of the file.
    insert_line = max(1, min(insert_line, len(lines)))

    # We construct a very small hunk that inserts a single comment line at
    # `insert_line` without removing any existing lines.
    comment = f"# {_build_investigation_comment(context, finding)}"

    # The original hunk covers the existing line at `insert_line` only.
    orig_start = insert_line
    orig_len = 1
    new_len = orig_len + 1

    original_line = lines[insert_line - 1]

    header = f"@@ -{orig_start},{orig_len} +{orig_start},{new_len} @@"
    body_lines = [
        f"+{comment}",
        f" {original_line}",
    ]

    return FilePatch(
        file_path=span.file_path,
        hunks=[
            PatchHunk(
                header=header,
                body="\n".join(body_lines),
            )
        ],
    )


class FixGenerationAgent:
    """
    Agent responsible for proposing minimal, human-auditable Python patches.

    The implementation prioritises:
    - Small, targeted fixes for well-known error patterns (e.g., bytes/str
      mismatches around bcrypt usage), and
    - Fallback investigation comments when no safe automatic change can be
      inferred.

    This keeps changes interpretable while leaving room for more advanced
    automated repairs in later phases.
    """

    def run(
        self,
        context: IncidentContext,
        findings: Sequence[CodeFinding],
        snippets: Sequence[KnowledgeSnippet],
    ) -> Tuple[List[ProposedFix], StageTrace]:
        started_at = datetime.utcnow()

        # Prioritise findings with an explicit suspicion score, highest first.
        sorted_findings = sorted(
            findings,
            key=lambda f: (f.suspicion.value if f.suspicion else 0.0),
            reverse=True,
        )

        proposed_fixes: List[ProposedFix] = []

        for finding in sorted_findings[:3]:
            file_patch = _build_file_patch_for_finding(
                context=context,
                finding=finding,
            )
            if file_patch is None:
                continue

            description_parts: List[str] = [
                "Insert an investigation comment near the stack-trace-derived "
                "code region to guide human review.",
            ]

            if context.primary_error_message:
                description_parts.append(
                    f"Primary error message: {context.primary_error_message}."
                )

            if snippets:
                description_parts.append(
                    "Relevant knowledge snippets were retrieved to provide "
                    "additional context for debugging."
                )

            description = " ".join(description_parts)

            proposed_fixes.append(
                ProposedFix(
                    id=f"fix-from-{finding.id}",
                    title=(
                        f"Add investigation comment in {file_patch.file_path}"
                    ),
                    description=description,
                    patches=[file_patch],
                    based_on_findings=[finding.id],
                    knowledge_snippets=list(snippets),
                    confidence=0.3,
                    metadata={},
                )
            )

        finished_at = datetime.utcnow()

        trace = _make_stage_trace(
            started_at=started_at,
            finished_at=finished_at,
            findings=findings,
            snippets=snippets,
            fixes=proposed_fixes,
        )

        return proposed_fixes, trace


__all__ = [
    "FixGenerationAgent",
]

