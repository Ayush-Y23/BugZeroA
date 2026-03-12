from __future__ import annotations

from pathlib import Path
from typing import List

from .sources import classify_source, discover_knowledge_files
from .vector_store import Document, InMemoryVectorStore


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Best-effort fallback for non-UTF-8 encodings.
        return path.read_text(encoding="latin-1", errors="ignore")


def _extract_title(text: str, default: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return default


def build_knowledge_index(repo_root: str | Path) -> InMemoryVectorStore:
    """
    Build an in-memory index of documentation and known error patterns.

    This performs a lightweight scan of the repository root for documentation
    files and known error pattern definitions, then constructs an
    `InMemoryVectorStore` that can be queried by the knowledge retrieval agent.
    """
    root_path = Path(repo_root)

    store = InMemoryVectorStore()

    knowledge_files: List[Path] = discover_knowledge_files(root_path)
    if not knowledge_files:
        return store

    documents: List[Document] = []
    for path in knowledge_files:
        text = _read_text(path)
        if not text.strip():
            continue

        rel_id = path.relative_to(root_path).as_posix()
        source = classify_source(path)
        title = _extract_title(text, default=path.name)

        documents.append(
            Document(
                id=rel_id,
                text=text,
                metadata={
                    "file_path": rel_id,
                    "source": source,
                    "title": title,
                },
            )
        )

    if documents:
        store.extend(documents)

    return store


__all__ = [
    "build_knowledge_index",
]

