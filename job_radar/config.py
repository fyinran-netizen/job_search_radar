"""Configuration loading helpers and runtime settings."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from job_radar.infra.paths import CONFIG_DIR
from job_radar.profile.models import MatchingRules, UserProfile


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


@dataclass(frozen=True)
class LLMTaskSettings:
    """Provider/model/timeout settings for one model-backed task."""

    provider: str
    model: str
    timeout_seconds: int


@dataclass(frozen=True)
class RuntimeSettings:
    """Resolved runtime settings for model-backed Job Radar workflows."""

    ollama_base_url: str
    page_processing: LLMTaskSettings
    extraction: LLMTaskSettings
    understanding: LLMTaskSettings
    match: LLMTaskSettings


def load_project_env(env_path: Path = ENV_PATH) -> None:
    """Load private project .env values without overriding existing environment."""

    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name:
            os.environ.setdefault(name, value)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return int(value)


def load_runtime_settings() -> RuntimeSettings:
    """Return provider and model settings from the project configuration."""

    return RuntimeSettings(
        ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        page_processing=LLMTaskSettings(
            provider=os.environ.get(
                "JOB_RADAR_PAGE_PROCESSING_PROVIDER",
                "ollama",
            ),
            model=os.environ.get(
                "JOB_RADAR_PAGE_PROCESSING_MODEL",
                "gpt-oss:20b-cloud",
            ),
            timeout_seconds=_env_int("JOB_RADAR_PAGE_PROCESSING_TIMEOUT_SECONDS", 90),
        ),
        extraction=LLMTaskSettings(
            provider=os.environ.get("JOB_RADAR_EXTRACTION_PROVIDER", "ollama"),
            model=os.environ.get(
                "JOB_RADAR_EXTRACTION_MODEL",
                os.environ.get("JOB_RADAR_EXTRACTION_OLLAMA_MODEL", "gpt-oss:20b-cloud"),
            ),
            timeout_seconds=_env_int("JOB_RADAR_EXTRACTION_TIMEOUT_SECONDS", 240),
        ),
        understanding=LLMTaskSettings(
            provider=os.environ.get("JOB_RADAR_UNDERSTANDING_PROVIDER", "ollama"),
            model=os.environ.get(
                "JOB_RADAR_UNDERSTANDING_MODEL",
                os.environ.get("JOB_RADAR_UNDERSTANDING_OLLAMA_MODEL", "gpt-oss:20b-cloud"),
            ),
            timeout_seconds=_env_int("JOB_RADAR_UNDERSTANDING_TIMEOUT_SECONDS", 180),
        ),
        match=LLMTaskSettings(
            provider=os.environ.get("JOB_RADAR_MATCH_PROVIDER", "ollama"),
            model=os.environ.get(
                "JOB_RADAR_MATCH_MODEL",
                os.environ.get("JOB_RADAR_MATCH_OLLAMA_MODEL", "gpt-oss:20b-cloud"),
            ),
            timeout_seconds=_env_int("JOB_RADAR_MATCH_TIMEOUT_SECONDS", 180),
        ),
    )


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and return an empty mapping for blank files."""

    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def resolve_config_path(name: str, config_dir: Path = CONFIG_DIR) -> tuple[Path, bool]:
    """Resolve a private config path, falling back to the example file."""

    private_path = config_dir / f"{name}.yaml"
    if private_path.exists():
        return private_path, False
    return config_dir / f"{name}.example.yaml", True


def load_profile(config_dir: Path = CONFIG_DIR) -> tuple[UserProfile, bool, Path]:
    """Load the user profile config, returning whether the example was used."""

    path, used_example = resolve_config_path("profile", config_dir)
    return UserProfile.model_validate(load_yaml(path)), used_example, path


def load_matching_rules(config_dir: Path = CONFIG_DIR) -> tuple[MatchingRules, bool, Path]:
    """Load matching rules, returning whether the example was used."""

    path, used_example = resolve_config_path("matching_rules", config_dir)
    return MatchingRules.model_validate(load_yaml(path)), used_example, path


