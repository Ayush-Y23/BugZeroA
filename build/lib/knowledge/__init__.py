from __future__ import annotations

"""
Knowledge retrieval subsystem.

This package provides:
- A lightweight in-memory "vector store" abstraction.
- Utilities to ingest documentation and known error pattern files.
- A retrieval surface that agents can use to fetch relevant snippets.
"""

__all__ = [
    "vector_store",
    "sources",
    "ingest",
]

