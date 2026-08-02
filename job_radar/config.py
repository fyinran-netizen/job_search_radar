"""Configuration loading helpers."""

from pathlib import Path
from typing import Any

import yaml

from job_radar.models.profile import MatchingRules, UserProfile
from job_radar.models.search import CandidateSource
from job_radar.utils.paths import CONFIG_DIR


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


def load_candidate_sources(config_dir: Path = CONFIG_DIR) -> tuple[list[CandidateSource], bool, Path]:
    """Load enabled manually configured sources as candidate sources."""

    path, used_example = resolve_config_path("sources", config_dir)
    data = load_yaml(path)
    sources = []
    for item in data.get("sources", []):
        if not item.get("enabled", False):
            continue
        sources.append(
            CandidateSource(
                url=item["url"],
                title=item.get("name", item["url"]),
                source_name=item.get("name", item["url"]),
                company_name=item.get("company_name"),
                company_type=item.get("company_type"),
                is_official=bool(item.get("official", False)),
                relevance_score=int(item.get("relevance_score", 100)),
                reason=f"Manually configured source: {item.get('type', 'unknown')}",
            )
        )
    return sources, used_example, path
