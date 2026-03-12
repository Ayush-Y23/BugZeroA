from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Sequence, Tuple

from ..knowledge.ingest import build_knowledge_index
from ..models.pipeline import CodeFinding, IncidentContext, KnowledgeSnippet, StageTrace


def _make_stage_trace(
    *,
    started_at: datetime,
    finished_at: datetime,
    context: IncidentContext,
    findings: Sequence[CodeFinding],
    snippets: Sequence[KnowledgeSnippet],
    knowledge_base_root: str | None,
) -> StageTrace:
    return StageTrace(
        stage="knowledge_retrieval",
        started_at=started_at,
        finished_at=finished_at,
        input_summary=(
            f"primary_error_message={context.primary_error_message!r}, "
            f"findings_count={len(findings)}"
        ),
        output_summary=f"snippets_count={len(snippets)}",
        details={
            "knowledge_base_root": knowledge_base_root,
        },
    )


def _build_query_text(context: IncidentContext, findings: Sequence[CodeFinding]) -> str:
    parts: List[str] = []

    if context.primary_error_message:
        parts.append(context.primary_error_message)

    if context.error_codes:
        parts.append(" ".join(context.error_codes))

    if context.suspected_components:
        parts.append(" ".join(context.suspected_components))

    for finding in findings[:3]:
        if finding.span.snippet:
            parts.append(finding.span.snippet)

    return "\n".join(part for part in parts if part)


class KnowledgeRetrievalAgent:
    """
    Agent responsible for retrieving relevant documentation and prior knowledge.

    The MVP implementation builds an in-memory index over local documentation
    (e.g., docs/ and README files) and performs simple token-overlap search.
    """

    def run(
        self,
        context: IncidentContext,
        findings: Sequence[CodeFinding],
    ) -> Tuple[List[KnowledgeSnippet], StageTrace]:
        started_at = datetime.utcnow()

        # Determine the root of the knowledge base. Prefer the repository root
        # associated with the incident, but fall back to the current working
        # directory when not provided.
        kb_root: Path
        if context.repo and context.repo.local_path:
            kb_root = Path(context.repo.local_path)
        else:
            kb_root = Path.cwd()

        index = build_knowledge_index(kb_root)

        query_text = _build_query_text(context, findings)
        snippets: List[KnowledgeSnippet] = []

        if query_text.strip() and index.document_count:
            results = index.query(query_text, top_k=5, min_score=0.0)
            for score, doc in results:
                metadata = dict(doc.metadata)
                source = metadata.get("source", "docs")
                title = metadata.get("title")

                snippets.append(
                    KnowledgeSnippet(
                        id=str(doc.id),
                        source=str(source),
                        title=title,
                        content=doc.text,
                        score=score,
                        metadata=metadata,
                    )
                )

        finished_at = datetime.utcnow()

        trace = _make_stage_trace(
            started_at=started_at,
            finished_at=finished_at,
            context=context,
            findings=findings,
            snippets=snippets,
            knowledge_base_root=str(kb_root),
        )

        return snippets, trace


__all__ = [
    "KnowledgeRetrievalAgent",
]

