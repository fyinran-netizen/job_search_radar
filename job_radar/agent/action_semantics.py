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
        purpose="Define the next bounded search scope for discovering relevant opportunities.",
        consumes=["candidate profile", "search history", "prior discovery context", "remaining search budget"],
        produces=["bounded search plan aligned with the candidate's goals"],
        progress_signal="The next search scope is specific, executable, and adds a useful direction to discovery.",
    ),
    "web_search": ActionSemantics(
        purpose="Explore the planned search scope and identify sources that may contain relevant jobs.",
        consumes=["executable search plan", "known candidate sources", "remaining search budget"],
        produces=["new candidate sources", "sources selected for inspection", "search evidence and history"],
        progress_signal="Search produces previously unseen, plausibly relevant sources or meaningful evidence that the scope is exhausted.",
    ),
    "acquire_page": ActionSemantics(
        purpose="Make selected source content available for workflow-level inspection.",
        consumes=["selected sources awaiting inspection", "canonical source URLs"],
        produces=["retrieved page content tied to its source", "bounded acquisition failure evidence"],
        progress_signal="A selected source becomes inspectable, or its inability to provide content is clearly established.",
    ),
    "analyze_page": ActionSemantics(
        purpose="Determine how each acquired page contributes to job discovery and what should happen next.",
        consumes=["acquired page content awaiting classification"],
        produces=["job-detail pages for extraction", "follow-up sources", "rejected pages", "classification evidence"],
        progress_signal="Pages are assigned a justified workflow disposition that either advances extraction or closes an unhelpful branch.",
    ),
    "job_extraction": ActionSemantics(
        purpose="Turn job-detail evidence into trustworthy, candidate-relevant job records for evaluation.",
        consumes=["job-detail pages awaiting extraction", "candidate profile and eligibility context"],
        produces=["validated and deduplicated prepared jobs", "follow-up needs", "extraction or validation evidence"],
        progress_signal="A page yields a trustworthy job record that is eligible for evaluation, or is conclusively ruled out with a reason.",
    ),
    "explore_followups": ActionSemantics(
        purpose="Follow explicit navigation links from unresolved pages to discover more executable sources.",
        consumes=["navigation-required pending follow-ups", "explicit HTTP(S) hrefs", "handled URL state"],
        produces=["new candidate sources", "selected sources for acquisition", "follow-up exploration metadata"],
        progress_signal="At least one previously unhandled href becomes a new source, or all explicit hrefs are exhausted.",
    ),
    "job_understanding": ActionSemantics(
        purpose="Make the substantive requirements and signals of each prepared job explicit for matching.",
        consumes=["prepared jobs awaiting interpretation"],
        produces=["structured job-understanding records", "requirement and signal evidence"],
        progress_signal="A job's material requirements are sufficiently explicit to support a reasoned fit assessment.",
    ),
    "match_analysis": ActionSemantics(
        purpose="Evaluate whether an understood opportunity merits the candidate's attention and why.",
        consumes=["structured job understanding", "corresponding job record", "candidate profile"],
        produces=["fit assessment with supporting strengths, gaps, and risks"],
        progress_signal="The opportunity receives an evidence-based assessment that can guide prioritization or rejection.",
    ),
    "stop": ActionSemantics(
        purpose="Conclude the workflow when its bounded objective is met or no worthwhile next action remains.",
        consumes=["current workflow evidence", "decision rationale"],
        produces=["explicit terminal rationale for the workflow outcome"],
        progress_signal="The workflow reaches a justified terminal decision with a clear reason for stopping.",
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
