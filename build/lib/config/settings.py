from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelSettings(BaseModel):
    """
    Configuration for the LLM/model layer.

    This keeps provider-agnostic parameters in one place so that different
    backends (OpenAI, Anthropic, local models, etc.) can be swapped in
    without touching call sites.
    """

    provider: str = "openai"
    model_name: str = "gpt-4.1-mini"
    request_timeout_seconds: int = 30
    max_output_tokens: int = 2048
    temperature: float = 0.2


class SandboxSettings(BaseModel):
    """
    Configuration for sandboxed execution.

    These settings primarily flow into the Docker-based sandbox backend.
    """

    docker_image: str = "incident-agent-runner:latest"
    workdir: str = "/workspace"
    network_disabled: bool = True
    cpus: Optional[float] = 1.0
    memory: Optional[str] = "1g"
    additional_args: Sequence[str] = Field(default_factory=list)

    # Default timeout applied to sandboxed command chains when a caller does
    # not provide an explicit override.
    default_timeout_seconds: Optional[int] = 600


class TestingSettings(BaseModel):
    """
    Configuration for test execution inside the sandbox.
    """

    # Extra pytest flags appended after the default minimal flags.
    default_pytest_args: Sequence[str] = Field(default_factory=tuple)

    # Default timeout for pytest runs when a caller does not provide an
    # explicit value.
    default_timeout_seconds: Optional[int] = 600


class TimeoutSettings(BaseModel):
    """
    High-level timeouts for individual pipeline stages.
    """

    incident_understanding_seconds: Optional[int] = 60
    code_analysis_seconds: Optional[int] = 60
    knowledge_retrieval_seconds: Optional[int] = 60
    fix_generation_seconds: Optional[int] = 60
    validation_seconds: Optional[int] = 600


class AppSettings(BaseSettings):
    """
    Top-level application configuration.

    Values can be overridden via environment variables using the
    `INCIDENT_AGENT_` prefix and `__` as a nested delimiter. For example:

        INCIDENT_AGENT_SANDBOX__DOCKER_IMAGE=my-image:latest
        INCIDENT_AGENT_TESTING__DEFAULT_TIMEOUT_SECONDS=900
    """

    model_config = SettingsConfigDict(
        env_prefix="INCIDENT_AGENT_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    environment: str = "dev"
    base_repo_root: Optional[Path] = None

    models: ModelSettings = ModelSettings()
    sandbox: SandboxSettings = SandboxSettings()
    testing: TestingSettings = TestingSettings()
    timeouts: TimeoutSettings = TimeoutSettings()


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """
    Return a cached singleton instance of `AppSettings`.

    This keeps configuration lookup cheap while still allowing overrides via
    environment variables at process start.
    """

    return AppSettings()

