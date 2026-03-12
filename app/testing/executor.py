from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from ..models.pipeline import (
    SandboxRunInfo,
    TestCaseResult,
    TestSummary,
    ValidationResult,
)
from ..sandbox.manager import SandboxManager
from ..config import get_settings


@dataclass
class PytestExecutionConfig:
    """
    Configuration for running pytest inside the sandbox.
    """

    pytest_args: Sequence[str] = ()
    """
    Additional arguments to pass to the pytest command.

    Examples:
        - ("-q",)
        - ("-q", "--maxfail=1")
    """

    timeout_seconds: Optional[int] = None
    """
    Optional timeout for the entire pytest invocation.
    """


class PytestExecutor:
    """
    Execute pytest inside a sandboxed repository and aggregate results.

    This executor deliberately focuses on a robust, plugin-free integration:
    it parses the standard pytest summary line from stdout/stderr instead of
    relying on JSON reporting plugins. If the summary cannot be parsed, a
    best-effort `ValidationResult` is still returned with zeroed counters and
    an explanatory note.
    """

    def __init__(
        self,
        *,
        sandbox_manager: Optional[SandboxManager] = None,
        config: Optional[PytestExecutionConfig] = None,
    ) -> None:
        self._sandbox = sandbox_manager or SandboxManager()

        if config is not None:
            self._config = config
        else:
            settings = get_settings()
            testing_cfg = settings.testing
            self._config = PytestExecutionConfig(
                pytest_args=tuple(testing_cfg.default_pytest_args),
                timeout_seconds=testing_cfg.default_timeout_seconds,
            )

    def run_tests(
        self,
        *,
        repo_path: str | Path,
        pytest_args: Optional[Sequence[str]] = None,
        env: Optional[Mapping[str, str]] = None,
        timeout_seconds: Optional[int] = None,
    ) -> ValidationResult:
        """
        Run pytest for the given repository and return a `ValidationResult`.

        Parameters
        ----------
        repo_path:
            Path to the repository root on the host.
        pytest_args:
            Optional extra arguments to pass to pytest. These are appended
            after any default arguments from the executor configuration.
        env:
            Optional environment variables to expose to the sandboxed process.
        timeout_seconds:
            Optional timeout override for this run. If not provided, the
            value from the executor configuration is used.
        """
        repo = Path(repo_path)

        # Start from conservative default pytest flags that should work
        # in most projects without requiring additional plugins.
        cmd_parts: list[str] = ["pytest", "-q"]

        default_args = list(self._config.pytest_args)
        if default_args:
            cmd_parts.extend(default_args)

        if pytest_args:
            cmd_parts.extend(list(pytest_args))

        command = " ".join(cmd_parts)

        sandbox_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self._config.timeout_seconds
        )

        sandbox_info = self._sandbox.run(
            repo_path=repo,
            commands=[command],
            timeout_seconds=sandbox_timeout,
            env=env,
        )

        test_summary, test_results, parse_note = self._parse_pytest_output(
            sandbox_info
        )

        status = self._derive_status(sandbox_info, test_summary)

        # When parsing fails, fall back to a neutral summary so that callers
        # always receive a populated `ValidationResult`.
        if test_summary is None:
            test_summary = TestSummary(
                total=0,
                passed=0,
                failed=0,
                skipped=0,
                xfailed=0,
                xpassed=0,
                errors=0,
            )

        notes_parts = []
        if parse_note:
            notes_parts.append(parse_note)
        if sandbox_info.exit_code is None:
            notes_parts.append(
                "Sandbox reported no exit code; this typically indicates a "
                "timeout or infrastructure error."
            )
        notes = " ".join(notes_parts) if notes_parts else None

        return ValidationResult(
            status=status,
            baseline_status="unknown",
            test_summary=test_summary,
            test_results=test_results,
            sandbox=sandbox_info,
            regressions_detected=status in ("failed", "errored"),
            notes=notes,
        )

    @staticmethod
    def _derive_status(
        sandbox_info: SandboxRunInfo,
        summary: Optional[TestSummary],
    ) -> str:
        """
        Infer a high-level validation status from the sandbox result and
        parsed pytest summary.
        """
        if sandbox_info.exit_code is None:
            return "errored"

        if sandbox_info.exit_code == 0:
            # Pytest uses exit code 0 when all tests pass or are skipped.
            if summary is not None and summary.failed == 0 and summary.errors == 0:
                return "passed"
            return "partial"

        # Non-zero exit codes generally indicate failures or errors.
        if summary is not None and summary.errors > 0:
            return "errored"

        return "failed"

    @staticmethod
    def _parse_pytest_output(
        sandbox_info: SandboxRunInfo,
    ) -> Tuple[Optional[TestSummary], list[TestCaseResult], Optional[str]]:
        """
        Parse pytest output to produce a `TestSummary` and (optionally)
        per-test results.

        This implementation focuses on aggregating the summary line, e.g.::

            === 10 passed, 2 failed, 1 skipped in 0.50s ===

        If the standard summary line cannot be found, `(None, [], note)` is
        returned where `note` describes the limitation.
        """
        logs = sandbox_info.logs or ""
        if not logs:
            return None, [], "Pytest produced no logs; test counts are unknown."

        # Search from the end for the first line that looks like a pytest
        # summary. Pytest typically wraps the summary in '==' or '==' lines.
        summary_line: Optional[str] = None
        for line in reversed(logs.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("===") and "===" in stripped[3:]:
                summary_line = stripped
                break
            if stripped.startswith("==") and "==" in stripped[2:]:
                summary_line = stripped
                break

        if summary_line is None:
            return (
                None,
                [],
                "Could not locate a standard pytest summary line in logs; "
                "test counts are unavailable.",
            )

        # Extract the inner summary text between the surrounding '=' markers.
        # Example:
        #   "=== 10 passed, 2 failed in 0.50s ==="
        inner_match = re.search(r"=+\s*(.+?)\s*=+$", summary_line)
        if not inner_match:
            return (
                None,
                [],
                "Failed to parse pytest summary line; test counts are "
                "unavailable.",
            )

        inner = inner_match.group(1)

        # Remove trailing "in Xs" timing information if present.
        inner = re.sub(r",?\s*in\s+\d+(\.\d+)?s$", "", inner)

        counts = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "xfailed": 0,
            "xpassed": 0,
            "errors": 0,
        }

        # Each part is typically of the form "<number> <label>" separated by
        # commas, e.g. "10 passed, 2 failed, 1 skipped".
        for part in inner.split(","):
            part = part.strip()
            if not part:
                continue

            match = re.match(r"(\d+)\s+(\w+)", part)
            if not match:
                continue

            value = int(match.group(1))
            label = match.group(2).lower()

            if label in counts:
                counts[label] += value
            elif label in ("error", "errors"):
                counts["errors"] += value
            else:
                # Unknown label; ignore but keep parsing the rest.
                continue

        counts["total"] = (
            counts["passed"]
            + counts["failed"]
            + counts["skipped"]
            + counts["xfailed"]
            + counts["xpassed"]
            + counts["errors"]
        )

        summary = TestSummary(
            total=counts["total"],
            passed=counts["passed"],
            failed=counts["failed"],
            skipped=counts["skipped"],
            xfailed=counts["xfailed"],
            xpassed=counts["xpassed"],
            errors=counts["errors"],
        )

        # Per-test parsing is intentionally left as an enhancement; we return
        # an empty list for now.
        return summary, [], None

