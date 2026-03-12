from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from ..models.pipeline import SandboxRunInfo
from ..config import get_settings
from .docker_backend import DockerSandboxConfig, run_in_docker_sandbox


@dataclass
class SandboxRequest:
    """
    High-level description of a sandboxed run.

    This abstraction is intentionally minimal for the MVP and can be extended
    later to include patch application details, baseline runs, or multiple
    distinct command phases.
    """

    repo_path: Path
    commands: Sequence[str]
    timeout_seconds: Optional[int] = None


class SandboxManager:
    """
    Entry point for running sandboxed commands against a repository.

    For the initial implementation, this manager delegates directly to the
    Docker-backed sandbox. It is designed so that additional backends or
    execution modes can be added later without changing call sites.
    """

    def __init__(self, config: Optional[DockerSandboxConfig] = None) -> None:
        if config is not None:
            self._config = config
        else:
            settings = get_settings()
            sandbox_cfg = settings.sandbox
            self._config = DockerSandboxConfig(
                image=sandbox_cfg.docker_image,
                workdir=sandbox_cfg.workdir,
                network_disabled=sandbox_cfg.network_disabled,
                cpus=sandbox_cfg.cpus,
                memory=sandbox_cfg.memory,
                additional_args=list(sandbox_cfg.additional_args),
            )

    def run(
        self,
        *,
        repo_path: str | Path,
        commands: Iterable[str],
        timeout_seconds: Optional[int] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> SandboxRunInfo:
        """
        Execute one or more commands in a sandboxed environment.

        Parameters
        ----------
        repo_path:
            Path to the repository root on the host filesystem.
        commands:
            Iterable of shell commands to execute inside the sandbox. These
            are executed in a single shell session joined with `&&`.
        timeout_seconds:
            Optional timeout applied to the entire command chain.
        env:
            Optional environment variables to expose to the sandbox process.

        Returns
        -------
        SandboxRunInfo
            Structured information about the sandboxed execution, suitable
            for attaching to a `ValidationResult`.
        """
        path = Path(repo_path).resolve()

        settings = get_settings()
        effective_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.sandbox.default_timeout_seconds
        )

        return run_in_docker_sandbox(
            repo_path=path,
            commands=list(commands),
            timeout_seconds=effective_timeout,
            env=env,
            config=self._config,
        )

