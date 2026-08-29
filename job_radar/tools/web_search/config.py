"""Configuration helpers owned by the web-search capability."""

from pathlib import Path

from job_radar.config import load_yaml, resolve_config_path
from job_radar.infra.paths import CONFIG_DIR
from job_radar.tools.web_search.models import CandidateSource


def load_candidate_sources(config_dir: Path = CONFIG_DIR) -> tuple[list[CandidateSource], bool, Path]:
    """Load enabled manually configured sources as CandidateSource objects."""

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
                location=item.get("location"),
                is_official=bool(item.get("official", False)),
                relevance_score=int(item.get("relevance_score", 100)),
                reason=f"Manually configured source: {item.get('type', 'unknown')}",
            )
        )
    return sources, used_example, path
