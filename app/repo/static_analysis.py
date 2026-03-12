from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

from ..models.pipeline import CodeSpan


@dataclass(frozen=True)
class EnclosingSymbol:
    """
    Represents a symbol (function or class) that encloses a given source location.
    """

    qualified_name: str
    kind: str  # "function" | "method" | "class" | "module"
    start_line: Optional[int]
    end_line: Optional[int]


def read_source(path: str | Path, encoding: str = "utf-8") -> str:
    """
    Read a Python source file from disk.

    This helper is intentionally small and synchronous; higher-level code can
    decide how to cache or parallelise file access.
    """
    p = Path(path)
    return p.read_text(encoding=encoding)


def _split_lines(source: str) -> list[str]:
    # Preserve line structure without trailing newline differences.
    return source.splitlines()


def slice_around_line(
    *,
    source: str,
    file_path: str,
    center_line: int,
    context_before: int = 3,
    context_after: int = 3,
) -> CodeSpan:
    """
    Return a `CodeSpan` that captures a small window of code around `center_line`.

    Line numbers are 1-based and inclusive.
    """
    if center_line <= 0:
        raise ValueError("center_line must be a positive 1-based line number")

    lines = _split_lines(source)
    total = len(lines)
    if total == 0:
        return CodeSpan(file_path=file_path, start_line=None, end_line=None, snippet=None)

    start = max(1, center_line - context_before)
    end = min(total, center_line + context_after)

    snippet = "\n".join(lines[start - 1 : end])

    return CodeSpan(
        file_path=file_path,
        start_line=start,
        end_line=end,
        snippet=snippet,
    )


def slice_for_node(
    *,
    source: str,
    file_path: str,
    node: ast.AST,
    extra_context: int = 0,
) -> CodeSpan:
    """
    Return a `CodeSpan` that covers the AST node's extent plus optional context.
    """
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None)

    if start is None or end is None:
        # Fallback: no concrete location information.
        return CodeSpan(file_path=file_path, start_line=None, end_line=None, snippet=None)

    lines = _split_lines(source)
    total = len(lines)

    start_line = max(1, start - extra_context)
    end_line = min(total, end + extra_context)
    snippet = "\n".join(lines[start_line - 1 : end_line])

    return CodeSpan(
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        snippet=snippet,
    )


def parse_module(source: str, *, filename: str = "<unknown>") -> ast.Module:
    """
    Parse Python source into an `ast.Module`.

    Callers may catch `SyntaxError` and optionally use `localise_syntax_error_span`
    to construct a `CodeSpan` for reporting.
    """
    return ast.parse(source, filename=filename, mode="exec")


def _iter_with_parents(node: ast.AST) -> Iterable[Tuple[ast.AST, Optional[ast.AST]]]:
    """
    Yield (node, parent) pairs for a depth-first walk of the AST.
    """
    stack: list[Tuple[ast.AST, Optional[ast.AST]]] = [(node, None)]
    while stack:
        current, parent = stack.pop()
        yield current, parent
        for child in ast.iter_child_nodes(current):
            stack.append((child, current))


def find_enclosing_symbol(
    tree: ast.AST,
    line: int,
) -> Optional[EnclosingSymbol]:
    """
    Find the innermost function, method, or class that encloses `line`.

    If no such symbol exists, returns a module-level `EnclosingSymbol`.
    """
    if line <= 0:
        raise ValueError("line must be a positive 1-based line number")

    candidates: list[Tuple[int, EnclosingSymbol]] = []

    module_start = getattr(tree, "lineno", 1)
    module_end = getattr(tree, "end_lineno", None)
    module_symbol = EnclosingSymbol(
        qualified_name="<module>",
        kind="module",
        start_line=module_start,
        end_line=module_end,
    )

    for node, parent in _iter_with_parents(tree):
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)
        if start is None or end is None:
            continue
        if line < start or line > end:
            continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if isinstance(parent, ast.ClassDef):
                qname = f"{parent.name}.{node.name}"
                kind = "method"
            else:
                qname = node.name
                kind = "function"
        elif isinstance(node, ast.ClassDef):
            qname = node.name
            kind = "class"
        else:
            # Not a symbol we care about for the public API.
            continue

        span_length = (end - start) + 1
        candidates.append(
            (
                span_length,
                EnclosingSymbol(qualified_name=qname, kind=kind, start_line=start, end_line=end),
            )
        )

    if not candidates:
        return module_symbol

    # Prefer the smallest enclosing symbol (closest to the line).
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def localise_syntax_error_span(
    *,
    source: str,
    file_path: str,
    error: SyntaxError,
    context_before: int = 1,
    context_after: int = 1,
) -> CodeSpan:
    """
    Create a `CodeSpan` that highlights where a `SyntaxError` occurred.
    """
    line = getattr(error, "lineno", None)
    if line is None:
        return CodeSpan(file_path=file_path, start_line=None, end_line=None, snippet=None)

    return slice_around_line(
        source=source,
        file_path=file_path,
        center_line=line,
        context_before=context_before,
        context_after=context_after,
    )


def localise_runtime_error_span(
    *,
    source: str,
    file_path: str,
    line: Optional[int],
    context_before: int = 3,
    context_after: int = 3,
) -> CodeSpan:
    """
    Construct a lightweight `CodeSpan` around a suspected runtime error location.

    This is designed to be used with stack frames (e.g., from tracebacks) where
    only a file path and line number are known.
    """
    if line is None:
        return CodeSpan(file_path=file_path, start_line=None, end_line=None, snippet=None)

    return slice_around_line(
        source=source,
        file_path=file_path,
        center_line=line,
        context_before=context_before,
        context_after=context_after,
    )


__all__ = [
    "EnclosingSymbol",
    "read_source",
    "slice_around_line",
    "slice_for_node",
    "parse_module",
    "find_enclosing_symbol",
    "localise_syntax_error_span",
    "localise_runtime_error_span",
]

