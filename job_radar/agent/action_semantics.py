"""Meaning of the canonical actions exposed to the workflow controller.

This module describes the artifacts and state changes of actions that already
exist in the agent graph.  It is explanatory input for controllers, not an
additional availability or transition policy.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pydantic import BaseModel

from job_radar.agent.action_names import AGENT_ACTION_NAMES, AgentActionName


class ActionSemantics(BaseModel):
    """The controller-facing semantics of one canonical action."""

    purpose: str
    consumes: list[str]
    produces: list[str]
    progress_signal: str


ACTION_SEMANTICS: Final[dict[AgentActionName, ActionSemantics]] = {
    "build_search_plan": ActionSemantics(
        purpose="Build or refresh bounded search queries from the candidate profile and search history.",
        consumes=["user profile", "query history", "previous search results", "current round and query limits"],
        produces=["search_plan with bounded queries"],
        progress_signal="A usable search plan is created or refreshed with at least one query.",
    ),
    "web_search": ActionSemantics(
        purpose="Execute the remaining queries in the current search plan and select candidate sources.",
        consumes=["search_plan with unexecuted queries", "existing candidate sources", "search limits"],
        produces=["candidate_sources", "selected_sources", "search round results", "query history", "search outcome"],
        progress_signal="Queries are recorded as executed and new candidate or selected sources are found.",
    ),
    "acquire_page": ActionSemantics(
        purpose="Fetch the selected source pages through the bounded page-acquisition tool.",
        consumes=["selected sources not yet handled", "source URLs"],
        produces=["acquired_pages", "page-acquisition errors for failed sources"],
        progress_signal="Each executable source is resolved to an acquired page or a recorded acquisition error.",
    ),
    "analyze_page": ActionSemantics(
        purpose="Clean and classify acquired pages, routing job-detail pages toward extraction.",
        consumes=["acquired pages not yet analyzed"],
        produces=["job_detail_pages", "pending follow-ups", "rejected pages", "page-analysis traces", "errors"],
        progress_signal="Input pages are marked analyzed and classified into accepted, follow-up, or rejected outcomes.",
    ),
    "job_extraction": ActionSemantics(
        purpose="Extract, validate, normalize, deduplicate, and gate job records from analyzed job-detail pages.",
        consumes=["job-detail pages not yet extracted", "candidate profile"],
        produces=["prepared_jobs", "pending follow-ups", "extraction and validation errors"],
        progress_signal="Input pages are marked extracted and valid, gate-passing records are added as prepared jobs.",
    ),
    "job_understanding": ActionSemantics(
        purpose="Turn prepared job records into structured requirement-understanding records.",
        consumes=["prepared jobs not yet understood"],
        produces=["understanding_records", "understood job keys", "understanding errors"],
        progress_signal="Each input job is marked understood and successful analyses produce understanding records.",
    ),
    "match_analysis": ActionSemantics(
        purpose="Assess understood jobs against the candidate profile for fit and risks.",
        consumes=["understanding records not yet matched", "corresponding prepared jobs", "candidate profile"],
        produces=["match_assessments", "matched job keys", "matching errors"],
        progress_signal="Each input understanding is marked matched and successful assessments are added.",
    ),
    "stop": ActionSemantics(
        purpose="End the bounded workflow and record why no further action should run.",
        consumes=["current controller observation", "stop rationale"],
        produces=["terminal stop_reason"],
        progress_signal="The agent state becomes terminal with a non-empty stop reason.",
    ),
}


if tuple(ACTION_SEMANTICS) != AGENT_ACTION_NAMES:
    raise RuntimeError("Action semantics vocabulary must match AGENT_ACTION_NAMES")


def get_action_semantics(action: AgentActionName) -> ActionSemantics:
    """Return the semantics for one canonical action."""

    return ACTION_SEMANTICS[action]


def get_available_action_semantics(
    actions: Sequence[AgentActionName],
) -> dict[AgentActionName, ActionSemantics]:
    """Return semantics only for the supplied, namespace-scoped actions."""

    return {action: get_action_semantics(action) for action in actions}


__all__ = [
    "ACTION_SEMANTICS",
    "ActionSemantics",
    "get_action_semantics",
    "get_available_action_semantics",
]
