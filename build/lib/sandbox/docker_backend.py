from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

from ..models.pipeline import SandboxRunInfo


@dataclass
class DockerSandboxConfig:
    """
    Configuration for running commands inside a Docker-based sandbox.

    This backend assumes that a suitable image already exists locally.
    The default image name is intentionally generic so that it can be
    overridden via configuration later without changing call sites.
    """

    image: str = "incident-agent-runner:latest"
    workdir: str = "/workspace"
    network_disabled: bool = True
    cpus: Optional[float] = 1.0
    memory: Optional[str] = "1g"
    additional_args: List[str] = field(default_factory=list)


def _build_docker_command(
    repo_path: Path,
    command: str,
    config: DockerSandboxConfig,
) -> List[str]:
    volume_spec = f"{repo_path.as_posix()}:{config.workdir}"

    args: List[str] = ["docker", "run", "--rm", "-v", volume_spec, "-w", config.workdir]

    if config.network_disabled:
        args.extend(["--network", "none"])

    if config.cpus is not None:
        args.extend(["--cpus", str(config.cpus)])

    if config.memory is not None:
        args.extend(["--memory", config.memory])

    # Restrict capabilities a bit; these flags are widely supported but may be
    # relaxed later if needed for specific workloads.
    args.extend(
        [
            "--pids-limit",
            "256",
            "--security-opt",
            "no-new-privileges",
        ]
    )

    if config.additional_args:
        args.extend(config.additional_args)

    # Use a POSIX shell inside the container to support command chaining.
    args.append(config.image)
    args.extend(["/bin/sh", "-lc", command])

    return args


def run_in_docker_sandbox(
    *,
    repo_path: Path,
    commands: Iterable[str],
    timeout_seconds: Optional[int] = None,
    env: Optional[Mapping[str, str]] = None,
    config: Optional[DockerSandboxConfig] = None,
) -> SandboxRunInfo:
    """
    Execute one or more shell commands inside a Docker container.

    The commands are executed in a single shell session joined with `&&`,
    so later commands only run if earlier ones succeed.
    """
    repo_path = repo_path.resolve()
    cfg = config or DockerSandboxConfig()

    # Join commands with `&&` so a failure short-circuits the rest.
    chained = " && ".join(commands)

    docker_cmd = _build_docker_command(repo_path=repo_path, command=chained, config=cfg)

    started_at = datetime.utcnow()

    # Ensure environment variables are strings and let the parent env
    # pass through by default.
    merged_env: Optional[Dict[str, str]]
    if env is not None:
        merged_env = {str(k): str(v) for k, v in env.items()}
    else:
        merged_env = None

    try:
        completed = subprocess.run(
            docker_cmd,
            input=None,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=merged_env,
        )
        finished_at = datetime.utcnow()

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        combined_logs = stdout + ("\n" if stdout and stderr else "") + stderr

        return SandboxRunInfo(
            started_at=started_at,
            finished_at=finished_at,
            command=chained,
            exit_code=completed.returncode,
            logs=combined_logs or None,
            metadata={
                "backend": "docker",
                "docker_command": " ".join(shlex.quote(a) for a in docker_cmd),
                "timeout_seconds": timeout_seconds,
            },
        )
    except subprocess.TimeoutExpired as exc:
        finished_at = datetime.utcnow()
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        combined_logs = stdout + ("\n" if stdout and stderr else "") + stderr

        return SandboxRunInfo(
            started_at=started_at,
            finished_at=finished_at,
            command=chained,
            exit_code=None,
            logs=combined_logs or None,
            metadata={
                "backend": "docker",
                "docker_command": " ".join(shlex.quote(a) for a in docker_cmd),
                "timeout_seconds": timeout_seconds,
                "error": "timeout",
            },
        )
    except FileNotFoundError:
        # Docker CLI is not available on the host; record this as a
        # sandbox-level error rather than raising to the caller.
        finished_at = datetime.utcnow()
        return SandboxRunInfo(
            started_at=started_at,
            finished_at=finished_at,
            command=chained,
            exit_code=None,
            logs=None,
            metadata={
                "backend": "docker",
                "error": "docker_cli_not_found",
            },
        )

