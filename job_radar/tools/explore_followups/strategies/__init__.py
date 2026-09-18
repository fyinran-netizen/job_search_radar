"""Supported deterministic follow-up exploration strategies."""

from job_radar.tools.explore_followups.strategies.href_navigation import (
    has_executable_href,
    select_href_targets,
)

__all__ = ["has_executable_href", "select_href_targets"]
