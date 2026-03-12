from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

from ..knowledge.vector_store import Document, InMemoryVectorStore


_PYTHON_FILE_PATTERNS: Sequence[str] = ("**/*.py",)

_DEFAULT_EXCLUDE_DIRS: Sequence[str] = (
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "venv",
    ".venv",
)


def _iter_python_files(root: Path) -> Iterable[Path]:
    """
    Yield Python source files underneath ``root``.

    This helper performs a simple recursive scan while skipping common
    virtual-environment and VCS directories. It is intentionally minimal
    and deterministic for the MVP implementation.
    """
    root = root.resolve()
    exclude: set[Path] = {root / name for name in _DEFAULT_EXCLUDE_DIRS}

    for pattern in _PYTHON_FILE_PATTERNS:
        for path in root.glob(pattern):
            if not path.is_file():
                continue

            # Skip files that live inside excluded directories.
            try:
                # `relative_to` will raise ValueError if `path` is not under
                # an excluded directory; we treat that as a signal to keep it.
                if any(path.is_relative_to(excluded) for excluded in exclude):
                    continue
            except AttributeError:
                # Python < 3.9 does not have Path.is_relative_to, but this
                # project targets Python 3.10+, so this is mainly defensive.
                # Fall back to a simpler prefix check.
                if any(str(path).startswith(str(excluded)) for excluded in exclude):
                    continue

            yield path


def _read_text(path: Path) -> str:
    """
    Read a source file using UTF-8 with a permissive fallback.
    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1", errors="ignore")


@dataclass
class RepositoryIndex:
    """
    Lightweight in-memory index over a Python repository.

    For the MVP, the index stores:
    - the repository root path,
    - a list of discovered Python files (relative POSIX-style paths),
    - an in-memory vector store built over full file contents.

    Higher-level search utilities can use this structure to perform
    approximate "semantic" search over files without bringing in an
    external embedding service.
    """

    root: Path
    files: List[str]
    store: InMemoryVectorStore

    @property
    def file_count(self) -> int:
        return len(self.files)


def build_repository_index(repo_root: str | Path) -> RepositoryIndex:
    """
    Build a `RepositoryIndex` for a local Python project.

    The indexer performs a best-effort scan of the repository root for
    ``*.py`` files, reads their contents, and creates a corresponding
    document in an `InMemoryVectorStore`. Each document's text is the full
    file content, and its metadata includes:

    - ``file_path``: path relative to the repository root (POSIX style),
    - ``kind``: currently fixed to ``"file"``.
    """
    root_path = Path(repo_root).resolve()

    files: List[str] = []
    documents: List[Document] = []

    for path in _iter_python_files(root_path):
        rel_path = path.relative_to(root_path).as_posix()
        text = _read_text(path)
        if not text.strip():
            continue

        files.append(rel_path)
        documents.append(
            Document(
                id=rel_path,
                text=text,
                metadata={
                    "file_path": rel_path,
                    "kind": "file",
                },
            )
        )

    store = InMemoryVectorStore()
    if documents:
        store.extend(documents)

    return RepositoryIndex(root=root_path, files=files, store=store)


__all__ = [
    "RepositoryIndex",
    "build_repository_index",
]

