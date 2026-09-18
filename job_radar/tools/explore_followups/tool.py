"""Agent-facing deterministic follow-up exploration tool."""

from typing import Any

from pydantic import BaseModel

from job_radar.tools.base import BaseTool
from job_radar.tools.explore_followups.models import (
    ExploreFollowupsInput,
    ExploreFollowupsOutput,
)
from job_radar.tools.explore_followups.strategies.href_navigation import select_href_targets


class ExploreFollowupsTool(BaseTool):
    """Turn supported explicit follow-up links into candidate sources."""

    name = "explore_followups"

    def run(self, payload: BaseModel | dict[str, Any]) -> ExploreFollowupsOutput:
        data = payload if isinstance(payload, ExploreFollowupsInput) else ExploreFollowupsInput.model_validate(payload)
        sources, explored_links, resolutions = select_href_targets(
            data.pending_followups,
            excluded_urls=data.excluded_urls,
            explored_links=data.explored_links,
        )
        return ExploreFollowupsOutput(
            sources=sources,
            explored_links=explored_links,
            resolutions=resolutions,
        )
