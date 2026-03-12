from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

from .indexer import RepositoryIndex, build_repository_index


@dataclass
class CodeSearchResult:
    """
    Result of querying a `RepositoryIndex` for relevant code.

    The MVP representation focuses on file-level matches; future iterations
    can be extended with symbol-level metadata and `CodeSpan` details.
    """

    file_path: str
    score: float
    metadata: dict


def index_repository(repo_root: str) -> RepositoryIndex:
    """
    Convenience wrapper for building a `RepositoryIndex`.

    This mirrors the terminology in the architecture plan while delegating
    the actual indexing work to `build_repository_index`.
    """
    return build_repository_index(repo_root)


def search_repository(
    index: RepositoryIndex,
    query_text: str,
    *,
    top_k: int = 10,
    min_score: float = 0.0,
) -> List[CodeSearchResult]:
    """
    Perform a simple token-overlap search over the indexed repository.

    The search is backed by the same in-memory vector store used for
    documentation, providing deterministic and dependency-free ranking that
    is sufficient for an MVP.
    """
    if not query_text.strip() or index.store.document_count == 0:
        return []

    results: List[CodeSearchResult] = []
    raw_results: Sequence[Tuple[float, object]] = index.store.query(
        query_text,
        top_k=top_k,
        min_score=min_score,
    )

    for score, doc in raw_results:
        metadata = dict(getattr(doc, "metadata", {}) or {})
        file_path = metadata.get("file_path", getattr(doc, "id", ""))

        results.append(
            CodeSearchResult(
                file_path=str(file_path),
                score=float(score),
                metadata=metadata,
            )
        )

    return results


__all__ = [
    "CodeSearchResult",
    "index_repository",
    "search_repository",
]

