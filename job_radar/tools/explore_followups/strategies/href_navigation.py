"""Explore explicit href/link targets from navigation follow-ups."""

from collections.abc import Iterable
from typing import Any

from job_radar.tools.explore_followups.common import normalized_http_url, normalized_url_set
from job_radar.tools.explore_followups.models import FollowupResolution
from job_radar.tools.page_analysis.models import PendingFollowup
from job_radar.tools.web_search.models import CandidateSource


def select_href_targets(
    pending_followups: Iterable[PendingFollowup],
    *,
    excluded_urls: set[str] | list[str] | None = None,
    explored_links: set[str] | list[str] | None = None,
) -> tuple[list[CandidateSource], list[str], list[FollowupResolution]]:
    """Select new HTTP(S) hrefs in stable follow-up/link order."""

    excluded = normalized_url_set(excluded_urls or set())
    explored = normalized_url_set(explored_links or set())
    selected: list[CandidateSource] = []
    newly_explored: list[str] = []
    seen = set(excluded) | explored
    resolutions: list[FollowupResolution] = []

    for followup in pending_followups:
        if followup.pending_kind != "navigation_required":
            resolutions.append(
                FollowupResolution(
                    followup_url=followup.url,
                    stage=followup.stage,
                    pending_kind=followup.pending_kind,
                    status="unsupported",
                    reason="pending kind is not supported by href navigation",
                )
            )
            continue

        usable: list[tuple[str, dict[str, str]]] = []
        invalid_count = 0
        for link in followup.links:
            raw_url = link.get("href") or link.get("url")
            normalized = normalized_http_url(raw_url)
            if normalized is None:
                invalid_count += 1
                continue
            usable.append((normalized, link))

        if not usable:
            resolutions.append(
                FollowupResolution(
                    followup_url=followup.url,
                    stage=followup.stage,
                    pending_kind=followup.pending_kind,
                    status="no_usable_links",
                    reason="no valid HTTP(S) hrefs were provided",
                    evidence={"invalid_link_count": invalid_count},
                )
            )
            continue

        discovered = 0
        skipped = invalid_count
        for normalized, link in usable:
            if normalized in seen:
                skipped += 1
                continue
            seen.add(normalized)
            newly_explored.append(normalized)
            selected.append(_candidate_source(followup, normalized, link))
            discovered += 1

        status = "explored" if discovered else "already_explored"
        resolutions.append(
            FollowupResolution(
                followup_url=followup.url,
                stage=followup.stage,
                pending_kind=followup.pending_kind,
                status=status,
                discovered_count=discovered,
                skipped_count=skipped,
                reason=(
                    "new href targets selected"
                    if discovered
                    else "all valid href targets were already handled"
                ),
                evidence={"usable_link_count": len(usable)},
            )
        )

    return selected, newly_explored, resolutions


def has_executable_href(
    pending_followups: Iterable[PendingFollowup],
    *,
    excluded_urls: set[str] | list[str] | None = None,
    explored_links: set[str] | list[str] | None = None,
) -> bool:
    """Return whether at least one navigation href can produce a new source."""

    sources, _, _ = select_href_targets(
        pending_followups,
        excluded_urls=excluded_urls,
        explored_links=explored_links,
    )
    return bool(sources)


def _candidate_source(
    followup: PendingFollowup,
    url: str,
    link: dict[str, str],
) -> CandidateSource:
    text = link.get("text", "").strip()
    title = text or followup.title or url
    provenance = f"href from follow-up {followup.url}"
    if followup.pending_kind:
        provenance += f" ({followup.pending_kind})"
    return CandidateSource(
        url=url,
        title=title,
        source_name=followup.source_name,
        company_name=followup.company_name,
        company_type=followup.company_type,
        is_official=followup.is_official,
        relevance_score=followup.priority,
        reason=provenance,
    )
