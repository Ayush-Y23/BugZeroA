from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Sequence, Tuple


_TOKEN_PATTERN = re.compile(r"\w+")


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return _TOKEN_PATTERN.findall(text.lower())


@dataclass
class Document:
    """
    Minimal representation of a document stored in the knowledge base.
    """

    id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class InMemoryVectorStore:
    """
    Very small, in-memory "vector store" backed by token overlap scoring.

    This avoids external dependencies while providing a simple, deterministic
    relevance ranking suitable for the MVP.
    """

    def __init__(self) -> None:
        self._documents: List[Document] = []

    @property
    def document_count(self) -> int:
        return len(self._documents)

    def add_document(self, doc_id: str, text: str, metadata: Dict[str, Any] | None = None) -> None:
        self._documents.append(
            Document(
                id=doc_id,
                text=text,
                metadata=metadata or {},
            )
        )

    def extend(self, documents: Sequence[Document]) -> None:
        self._documents.extend(documents)

    def query(
        self,
        query_text: str,
        *,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[Tuple[float, Document]]:
        """
        Return up to `top_k` documents ranked by simple token-overlap score.

        The score is a float in [0, 1], representing the fraction of query
        tokens that also appear in the candidate document.
        """
        query_tokens = _tokenize(query_text)
        if not query_tokens or not self._documents:
            return []

        query_set = set(query_tokens)
        results: List[Tuple[float, Document]] = []

        for doc in self._documents:
            doc_tokens = _tokenize(doc.text)
            if not doc_tokens:
                continue

            doc_set = set(doc_tokens)
            overlap_count = len(query_set & doc_set)
            if overlap_count == 0:
                continue

            score = overlap_count / float(len(query_set))
            if score >= min_score:
                results.append((score, doc))

        results.sort(key=lambda item: item[0], reverse=True)
        if top_k <= 0:
            return results
        return results[:top_k]


__all__ = [
    "Document",
    "InMemoryVectorStore",
]

