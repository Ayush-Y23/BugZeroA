from __future__ import annotations

from pathlib import Path
from typing import Iterable, List


def _iter_existing(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.exists():
            yield path


def discover_knowledge_roots(repo_root: Path) -> List[Path]:
    """
    Return top-level directories/files that should be considered for knowledge ingestion.

    For the MVP, we look for:
    - docs/ style directories
    - top-level README files
    - config/known-errors.* files
    """
    roots: List[Path] = []

    candidates = [
        repo_root / "docs",
        repo_root / "documentation",
        repo_root / "config",
    ]
    roots.extend(_iter_existing(candidates))

    # Common README locations.
    for name in (
        "README.md",
        "README.rst",
        "README.txt",
    ):
        candidate = repo_root / name
        if candidate.exists():
            roots.append(candidate)

    return roots


def classify_source(path: Path) -> str:
    """
    Best-effort classification of a knowledge source.
    """
    parts = {p.lower() for p in path.parts}

    if "known-errors.yml" in path.name.lower() or "known-errors.yaml" in path.name.lower():
        return "known-error-patterns"
    if "config" in parts and ("error" in path.name.lower() or "incident" in path.name.lower()):
        return "known-error-patterns"
    if "docs" in parts or "documentation" in parts:
        return "docs"

    return "docs"


def discover_knowledge_files(root: Path) -> List[Path]:
    """
    Discover individual knowledge files underneath the given repository root.
    """
    roots = discover_knowledge_roots(root)
    files: List[Path] = []

    for base in roots:
        if base.is_file():
            files.append(base)
            continue

        # Walk common documentation and config file types.
        for pattern in ("**/*.md", "**/*.rst", "**/*.txt", "**/*.yml", "**/*.yaml"):
            files.extend(base.glob(pattern))

    # Deduplicate while preserving order.
    seen: set[Path] = set()
    unique_files: List[Path] = []
    for path in files:
        if path not in seen:
            seen.add(path)
            unique_files.append(path)

    return unique_files


__all__ = [
    "discover_knowledge_files",
    "discover_knowledge_roots",
    "classify_source",
]

