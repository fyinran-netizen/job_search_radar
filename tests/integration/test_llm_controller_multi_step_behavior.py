"""Opt-in multi-step behavior tests for the real LLM workflow controller."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import time

import pytest

from job_radar.agent import LLMController
from job_radar.agent.action_names import AgentActionName
from job_radar.agent.controllers import DecisionContext
from job_radar.agent.models import AgentLimits, AgentState, SearchOutcome
from job_radar.agent.policies.namespace import available_actions
from job_radar.config import load_project_env, load_runtime_settings
from job_radar.infra.llm.ollama import OllamaProvider
from job_radar.profile.models import UserProfile
from job_radar.tools.job_extraction.models import AIPageInput
from job_radar.tools.page_acquisition.models import PageDocument
from job_radar.tools.search_plan.models import SearchPlan
from job_radar.tools.web_search.models import CandidateSource


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LLM_CONTROLLER_MULTI_STEP_BEHAVIOR") != "1",
    reason=(
        "Real LLM multi-step behavior test; "
        "set RUN_LLM_CONTROLLER_MULTI_STEP_BEHAVIOR=1 to run."
    ),
)

REPORT_PATH = (
    Path(__file__).resolve().parents[1]
    / "output"
    / "llm_controller_multi_step_behavior_report.md"
)

COOLDOWN_SECONDS = float(
    os.environ.get(
        "LLM_CONTROLLER_TEST_COOLDOWN_SECONDS",
        "5",
    )
)


def profile() -> UserProfile:
    return UserProfile(
        target_roles=["AI Agent Engineer"],
    )


def source() -> CandidateSource:
    return CandidateSource(
        url="https://example.test/job",
        title="AI Agent Engineer",
        source_name="Example",
    )


def acquired_page() -> PageDocument:
    return PageDocument(
        url="https://example.test/job",
        title="AI Agent Engineer",
        source_name="Example",
    )


def detail_page() -> AIPageInput:
    return AIPageInput(
        url="https://example.test/job",
        title="AI Agent Engineer",
        source_name="Example",
        visible_text=(
            "Graduate AI Agent Engineer role. "
            "Python, LLM, RAG and agent workflow experience preferred."
        ),
    )


def make_context(
    state: AgentState,
    *,
    last_action: AgentActionName | None = None,
    user_profile: UserProfile | None = None,
) -> DecisionContext:
    limits = AgentLimits()

    actions = available_actions(
        state,
        limits,
        profile=user_profile,
        last_action=last_action,
    )

    return DecisionContext(
        state=state,
        limits=limits,
        profile=user_profile,
        available_actions=actions,
        last_action=last_action,
    )


@pytest.fixture(scope="module")
def controller() -> LLMController:
    load_project_env()
    settings = load_runtime_settings()

    return LLMController(
        provider=OllamaProvider(
            model=settings.controller.model,
            base_url=settings.ollama_base_url,
        ),
        timeout_seconds=settings.controller.timeout_seconds,
    )


@pytest.fixture(scope="module", autouse=True)
def behavior_report() -> None:
    load_project_env()
    settings = load_runtime_settings()

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    run_label = datetime.now().astimezone().strftime(
        "%Y-%m-%d %H:%M"
    )

    with REPORT_PATH.open(
        "a",
        encoding="utf-8",
    ) as report:
        report.write(
            f"\n## Run {run_label}\n\n"
            f"Model: `{settings.controller.model}`\n\n"
            "Context version: "
            "`after last_action_summary / controller context refactor`\n\n"
            "| Scenario | Step | Available Actions | "
            "Last Action | Last Action Summary | "
            "Expected | Actual | Result | Rationale |\n"
            "|---|---:|---|---|---|---|---|---|---|\n"
        )


def _cooldown() -> None:
    if COOLDOWN_SECONDS > 0:
        time.sleep(COOLDOWN_SECONDS)


def _markdown_cell(value: object) -> str:
    return (
        str(value)
        .replace("|", "\\|")
        .replace("\n", " ")
    )


def _append_report(
    *,
    scenario: str,
    step: int,
    context: DecisionContext,
    expected_actions: set[AgentActionName],
    actual_action: str,
    result: str,
    rationale: str,
) -> None:
    row = (
        scenario,
        step,
        ", ".join(context.available_actions),
        context.last_action or "",
        context.state.last_action_summary or "",
        ", ".join(sorted(expected_actions)),
        actual_action,
        result,
        rationale,
    )

    with REPORT_PATH.open(
        "a",
        encoding="utf-8",
    ) as report:
        report.write(
            "| "
            + " | ".join(
                _markdown_cell(value)
                for value in row
            )
            + " |\n"
        )


def _decide(
    controller: LLMController,
    *,
    scenario: str,
    step: int,
    context: DecisionContext,
    expected_actions: set[AgentActionName],
) -> AgentActionName:
    decision = controller.decide(context)

    result = (
        "PASS"
        if decision.action in expected_actions
        else "FAIL"
    )

    _append_report(
        scenario=scenario,
        step=step,
        context=context,
        expected_actions=expected_actions,
        actual_action=decision.action,
        result=result,
        rationale=decision.rationale,
    )

    assert decision.action in expected_actions

    _cooldown()

    return decision.action


def test_search_replan_loop(
    controller: LLMController,
) -> None:
    """
    web_search produced no useful progress
    -> replan
    -> new plan becomes searchable again
    """

    user_profile = profile()

    state = AgentState(
        search_plan=SearchPlan(
            queries=["AI agent graduate jobs"],
            target_roles=["AI Agent Engineer"],
        ),
        executed_queries=["AI agent graduate jobs"],
        last_search_outcome=SearchOutcome.NO_PROGRESS,
        last_action_summary=(
            "The previous web-search round produced no meaningful "
            "new candidate-source evidence and the current direction "
            "appears saturated."
        ),
    )

    context = make_context(
        state,
        last_action="web_search",
        user_profile=user_profile,
    )

    action = _decide(
        controller,
        scenario="search replan loop",
        step=1,
        context=context,
        expected_actions={"build_search_plan"},
    )

    assert action == "build_search_plan"

    state = state.model_copy(
        update={
            "search_plan": SearchPlan(
                queries=[
                    "AI Agent Engineer graduate Python LLM jobs"
                ],
                target_roles=["AI Agent Engineer"],
            ),
            "last_action_summary": (
                "A new executable search direction was produced "
                "with a revised query."
            ),
        }
    )

    context = make_context(
        state,
        last_action="build_search_plan",
        user_profile=user_profile,
    )

    _decide(
        controller,
        scenario="search replan loop",
        step=2,
        context=context,
        expected_actions={"web_search"},
    )


def test_page_processing_branch_changes_with_state(
    controller: LLMController,
) -> None:
    """
    Same general page-processing area, but state changes should move
    the controller from analysis to extraction.
    """

    user_profile = profile()

    state = AgentState(
        acquired_pages=[acquired_page()],
        last_action_summary=(
            "Page acquisition successfully acquired one page "
            "that still requires routing analysis."
        ),
    )

    context = make_context(
        state,
        last_action="acquire_page",
        user_profile=user_profile,
    )

    _decide(
        controller,
        scenario="page processing progression",
        step=1,
        context=context,
        expected_actions={"analyze_page"},
    )

    state = state.model_copy(
        update={
            "job_detail_pages":[detail_page()],
            "analyzed_page_urls":[
                "https://example.test/job"
            ],
            "last_action_summary": (
                "Page analysis routed one job-detail page "
                "for extraction with no remaining page-analysis work."
            ),
        }
    )

    context = make_context(
        state,
        last_action="analyze_page",
        user_profile=user_profile,
    )

    _decide(
        controller,
        scenario="page processing progression",
        step=2,
        context=context,
        expected_actions={"job_extraction"},
    )


def test_search_result_progresses_to_acquisition(
    controller: LLMController,
) -> None:
    """
    Productive search result should move the controller downstream
    instead of triggering unnecessary replanning or stopping.
    """

    state = AgentState(
        candidate_sources=[source()],
        selected_sources=[source()],
        last_search_outcome=SearchOutcome.PROGRESS,
        last_action_summary=(
            "The latest search round found a relevant new source "
            "and selected it for page inspection."
        ),
    )

    context = make_context(
        state,
        last_action="web_search",
        user_profile=profile(),
    )

    _decide(
        controller,
        scenario="productive search progression",
        step=1,
        context=context,
        expected_actions={"acquire_page"},
    )