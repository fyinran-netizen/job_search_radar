"""Opt-in multi-step behavior tests for the real LLM workflow controller."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import time
from typing import Any

import pytest

from job_radar.agent import LLMController
from job_radar.agent.action_names import AgentActionName
from job_radar.agent.controllers import DecisionContext
from job_radar.agent.controllers.llm_controller.observation.builder import (
    build_observation,
)
from job_radar.agent.controllers.llm_controller.prompt import (
    build_controller_prompt,
)
from job_radar.agent.models import (
    AgentLimits,
    AgentState,
    SearchOutcome,
)
from job_radar.agent.policies.namespace import available_actions
from job_radar.config import load_project_env, load_runtime_settings
from job_radar.infra.llm.ollama import OllamaProvider
from job_radar.profile.models import UserProfile
from job_radar.tools.job_extraction.models import (
    AIPageInput,
    JobRecord,
)
from job_radar.tools.job_understanding.models import (
    JobRequirementFacts,
    JobUnderstandingRecord,
    RequirementFact,
)
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

DEBUG_RECORDS: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Shared fixtures / model objects
# ---------------------------------------------------------------------------


def profile() -> UserProfile:
    return UserProfile(
        target_roles=["AI Agent Engineer"],
    )


def source(
    suffix: str = "job-1",
    title: str = "AI Agent Engineer",
) -> CandidateSource:
    return CandidateSource(
        url=f"https://example.test/{suffix}",
        title=title,
        source_name="Example",
    )


def acquired_page(
    suffix: str = "job-1",
    title: str = "AI Agent Engineer",
) -> PageDocument:
    return PageDocument(
        url=f"https://example.test/{suffix}",
        title=title,
        source_name="Example",
    )


def detail_page(
    suffix: str = "job-1",
    title: str = "AI Agent Engineer",
) -> AIPageInput:
    return AIPageInput(
        url=f"https://example.test/{suffix}",
        title=title,
        source_name="Example",
        visible_text=(
            "Graduate AI Agent Engineer role. "
            "Python, LLM, RAG and agent workflow experience preferred."
        ),
    )


def prepared_job(
    suffix: str = "job-1",
    title: str = "AI Agent Engineer",
) -> JobRecord:
    return JobRecord(
        deduplication_key=f"example:{suffix}",
        title=title,
        company_name="Example",
        source_url=f"https://example.test/{suffix}",
        source_name="Example",
        description="Build AI agent workflows using Python, LLMs and RAG.",
    )


def understanding_record(
    suffix: str = "job-1",
    title: str = "AI Agent Engineer",
) -> JobUnderstandingRecord:
    job = prepared_job(
        suffix=suffix,
        title=title,
    )

    return JobUnderstandingRecord(
        deduplication_key=job.deduplication_key,
        basic_gate=job.basic_gate,
        understanding=JobRequirementFacts(
            canonical_role=title,
            seniority="graduate",
            requirements=[
                RequirementFact(
                    category="technical_skill",
                    text="Python",
                )
            ],
            confidence="high",
        ),
        source="ai",
    )


# ---------------------------------------------------------------------------
# Production context construction
# ---------------------------------------------------------------------------


def make_context(
    state: AgentState,
    *,
    last_action: AgentActionName | None,
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


# ---------------------------------------------------------------------------
# Real controller
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def behavior_report():
    load_project_env()
    settings = load_runtime_settings()

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    DEBUG_RECORDS.clear()

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
            "Test type: `multi-step controller behavior`\n\n"
            "Context version: "
            "`production available_actions + last_action_summary context`\n\n"
            f"Cooldown: `{COOLDOWN_SECONDS}s`\n\n"
        )

        report.write(
            "| Scenario | Step | Available Actions | "
            "Last Action | Last Action Summary | "
            "Expected | Actual | Result | Rationale |\n"
        )

        report.write(
            "|---|---:|---|---|---|---|---|---|---|\n"
        )

    yield

    if not DEBUG_RECORDS:
        return

    with REPORT_PATH.open(
        "a",
        encoding="utf-8",
    ) as report:
        report.write(
            "\n### Failed step details\n\n"
        )

        for record in DEBUG_RECORDS:
            report.write(
                f"#### {record['scenario']} / step {record['step']}\n\n"
                f"Model: `{record['model']}`\n\n"
            )

            observation = record.get("observation")
            if observation is not None:
                report.write(
                    "Controller observation:\n\n"
                    "```json\n"
                    f"{observation.model_dump_json(indent=2)}\n"
                    "```\n\n"
                )

            prompt = record.get("prompt")
            if prompt is not None:
                report.write(
                    "Controller prompt:\n\n"
                    "```text\n"
                    f"{prompt}\n"
                    "```\n\n"
                )

            exception = record.get("exception")
            if exception is not None:
                report.write(
                    "Exception / validation error:\n\n"
                    "```text\n"
                    f"{repr(exception)}\n"
                    "```\n\n"
                )

            decision = record.get("decision")
            if decision is not None:
                report.write(
                    "Parsed decision:\n\n"
                    "```json\n"
                    f"{decision.model_dump_json(indent=2)}\n"
                    "```\n\n"
                )


def _markdown_cell(
    value: object,
) -> str:
    return (
        str(value)
        .replace("|", "\\|")
        .replace("\n", " ")
    )


def _append_report_row(
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


def _record_debug(
    *,
    scenario: str,
    step: int,
    model: str,
    observation: object,
    prompt: str,
    exception: BaseException | None = None,
    decision: object | None = None,
) -> None:
    DEBUG_RECORDS.append(
        {
            "scenario": scenario,
            "step": step,
            "model": model,
            "observation": observation,
            "prompt": prompt,
            "exception": exception,
            "decision": decision,
        }
    )


def _cooldown() -> None:
    if COOLDOWN_SECONDS > 0:
        time.sleep(COOLDOWN_SECONDS)


def _decide_step(
    controller: LLMController,
    *,
    scenario: str,
    step: int,
    state: AgentState,
    last_action: AgentActionName,
    expected_actions: set[AgentActionName],
    user_profile: UserProfile | None = None,
) -> AgentActionName:
    settings = load_runtime_settings()

    context = make_context(
        state,
        last_action=last_action,
        user_profile=user_profile,
    )

    observation = build_observation(
        context
    )

    prompt = build_controller_prompt(
        observation,
        context.available_actions,
    )

    # The test must never invent an expected action outside the
    # production action namespace.
    assert expected_actions.issubset(
        set(context.available_actions)
    ), (
        f"{scenario} step {step}: expected actions "
        f"{sorted(expected_actions)} are not all production-available; "
        f"available={context.available_actions}"
    )

    try:
        decision = controller.decide(
            context
        )
    except Exception as exc:
        _append_report_row(
            scenario=scenario,
            step=step,
            context=context,
            expected_actions=expected_actions,
            actual_action="<exception>",
            result="FAIL",
            rationale="",
        )

        _record_debug(
            scenario=scenario,
            step=step,
            model=settings.controller.model,
            observation=observation,
            prompt=prompt,
            exception=exc,
        )

        _cooldown()
        raise

    result = (
        "PASS"
        if decision.action in expected_actions
        else "FAIL"
    )

    _append_report_row(
        scenario=scenario,
        step=step,
        context=context,
        expected_actions=expected_actions,
        actual_action=decision.action,
        result=result,
        rationale=decision.rationale,
    )

    if result == "FAIL":
        _record_debug(
            scenario=scenario,
            step=step,
            model=settings.controller.model,
            observation=observation,
            prompt=prompt,
            decision=decision,
        )

    _cooldown()

    assert decision.action in expected_actions

    return decision.action


# ---------------------------------------------------------------------------
# Scenario 1
#
# Productive search:
# web_search -> acquire_page -> analyze_page
#
# Step 1 deliberately creates a real decision between:
# - consuming an already selected source
# - abandoning it and replanning
# ---------------------------------------------------------------------------


def test_productive_search_progresses_downstream(
    controller: LLMController,
) -> None:
    user_profile = profile()
    selected = source("job-1")

    state = AgentState(
        search_plan=SearchPlan(
            queries=["AI agent graduate jobs"],
            target_roles=["AI Agent Engineer"],
        ),
        executed_queries=[
            "AI agent graduate jobs"
        ],
        candidate_sources=[
            selected
        ],
        selected_sources=[
            selected
        ],
        last_search_outcome=SearchOutcome.PROGRESS,
        last_action_summary=(
            "The latest search completed its current query and found "
            "a relevant new source that was selected for page acquisition."
        ),
    )

    action = _decide_step(
        controller,
        scenario="productive search progresses downstream",
        step=1,
        state=state,
        last_action="web_search",
        expected_actions={"acquire_page"},
        user_profile=user_profile,
    )

    assert action == "acquire_page"

    page = acquired_page("job-1")

    state = state.model_copy(
        update={
            "acquired_pages": [page],
            "last_action_summary": (
                "Page acquisition successfully acquired the selected source "
                "and the page now requires routing analysis."
            ),
        }
    )

    _decide_step(
        controller,
        scenario="productive search progresses downstream",
        step=2,
        state=state,
        last_action="acquire_page",
        expected_actions={"analyze_page"},
        user_profile=user_profile,
    )


# ---------------------------------------------------------------------------
# Scenario 2
#
# Search recovery:
# web_search -> build_search_plan -> web_search
#
# This validates a backward loop instead of fixed forward-only progression.
# ---------------------------------------------------------------------------


def test_search_no_progress_replans_and_returns_to_search(
    controller: LLMController,
) -> None:
    user_profile = profile()

    old_query = "AI agent graduate jobs"

    state = AgentState(
        search_plan=SearchPlan(
            queries=[old_query],
            target_roles=["AI Agent Engineer"],
        ),
        executed_queries=[
            old_query
        ],
        last_search_outcome=SearchOutcome.NO_PROGRESS,
        last_action_summary=(
            "The previous web-search query produced no useful candidate "
            "sources. The current query is exhausted, but the target role "
            "remains unmet and alternative search directions have not yet "
            "been planned."
        ),
    )

    action = _decide_step(
        controller,
        scenario="search recovery loop",
        step=1,
        state=state,
        last_action="web_search",
        expected_actions={"build_search_plan"},
        user_profile=user_profile,
    )

    assert action == "build_search_plan"

    new_query = (
        "graduate AI Agent Engineer Python LLM RAG jobs"
    )

    state = state.model_copy(
        update={
            "search_plan": SearchPlan(
                queries=[new_query],
                target_roles=[
                    "AI Agent Engineer"
                ],
            ),
            "last_action_summary": (
                "A revised search plan produced a new executable query "
                "for the unmet target role."
            ),
        }
    )

    _decide_step(
        controller,
        scenario="search recovery loop",
        step=2,
        state=state,
        last_action="build_search_plan",
        expected_actions={"web_search"},
        user_profile=user_profile,
    )


# ---------------------------------------------------------------------------
# Scenario 3
#
# Same-stage backlog:
# analyze_page -> analyze_page -> job_extraction
#
# Both analyze_page and job_extraction are initially production-available.
# The controller should finish remaining page-analysis work before advancing,
# because after leaving the analysis stage the transition policy does not
# return directly to it.
# ---------------------------------------------------------------------------


def test_page_analysis_finishes_backlog_before_advancing(
    controller: LLMController,
) -> None:
    user_profile = profile()

    page_one = acquired_page(
        "job-1",
        "AI Agent Engineer",
    )

    page_two = acquired_page(
        "job-2",
        "LLM Application Engineer",
    )

    detail_one = detail_page(
        "job-1",
        "AI Agent Engineer",
    )

    state = AgentState(
        acquired_pages=[
            page_one,
            page_two,
        ],
        analyzed_page_urls=[
            page_one.url
        ],
        job_detail_pages=[
            detail_one
        ],
        last_action_summary=(
            "Page analysis produced one job-detail page, but another "
            "acquired page remains unanalyzed."
        ),
    )

    action = _decide_step(
        controller,
        scenario="page analysis backlog",
        step=1,
        state=state,
        last_action="analyze_page",
        expected_actions={"analyze_page"},
        user_profile=user_profile,
    )

    assert action == "analyze_page"

    detail_two = detail_page(
        "job-2",
        "LLM Application Engineer",
    )

    state = state.model_copy(
        update={
            "analyzed_page_urls": [
                page_one.url,
                page_two.url,
            ],
            "job_detail_pages": [
                detail_one,
                detail_two,
            ],
            "last_action_summary": (
                "All acquired pages have now been analyzed and two "
                "job-detail pages are ready for structured extraction."
            ),
        }
    )

    _decide_step(
        controller,
        scenario="page analysis backlog",
        step=2,
        state=state,
        last_action="analyze_page",
        expected_actions={"job_extraction"},
        user_profile=user_profile,
    )


# ---------------------------------------------------------------------------
# Scenario 4
#
# Late-stage branch:
# match_analysis -> match_analysis -> build_search_plan
#
# While unmatched understanding records remain, matching should continue.
# Once matching is complete and the current search plan is exhausted,
# the workflow can return to search planning for additional opportunities.
# ---------------------------------------------------------------------------


def test_matching_finishes_pending_work_then_replans(
    controller: LLMController,
) -> None:
    user_profile = profile()

    query = "AI Agent Engineer graduate jobs"

    record_one = understanding_record(
        "job-1",
        "AI Agent Engineer",
    )

    record_two = understanding_record(
        "job-2",
        "LLM Application Engineer",
    )

    retained_source = source(
        "job-1",
        "AI Agent Engineer",
    )

    state = AgentState(
        search_plan=SearchPlan(
            queries=[query],
            target_roles=[
                "AI Agent Engineer"
            ],
        ),
        executed_queries=[
            query
        ],
        candidate_sources=[
            retained_source
        ],
        understanding_records=[
            record_one,
            record_two,
        ],
        matched_job_keys=[
            record_one.deduplication_key
        ],
        match_assessments=[
            {
                "deduplication_key": (
                    record_one.deduplication_key
                ),
                "match_score": 72,
                "role_fit": "medium",
                "must_have_fit": "yes",
                "recommendation": "consider",
                "match_reasons": [
                    "Relevant Python and agent workflow experience."
                ],
                "missing_requirements": [],
                "risk_flags": [],
                "confidence": "high",
            }
        ],
        last_search_outcome=SearchOutcome.PROGRESS,
        last_action_summary=(
            "One job has been matched, while another understood job "
            "still has no match assessment."
        ),
    )

    action = _decide_step(
        controller,
        scenario="matching completion and replan",
        step=1,
        state=state,
        last_action="match_analysis",
        expected_actions={"match_analysis"},
        user_profile=user_profile,
    )

    assert action == "match_analysis"

    state = state.model_copy(
        update={
            "matched_job_keys": [
                record_one.deduplication_key,
                record_two.deduplication_key,
            ],
            "match_assessments": [
                *state.match_assessments,
                {
                    "deduplication_key": (
                        record_two.deduplication_key
                    ),
                    "match_score": 48,
                    "role_fit": "low",
                    "must_have_fit": "no",
                    "recommendation": "skip",
                    "match_reasons": [],
                    "missing_requirements": [
                        "Required production deployment experience."
                    ],
                    "risk_flags": [],
                    "confidence": "high",
                },
            ],
            "last_action_summary": (
                "All currently understood jobs have now been matched. "
                "The available opportunities are not strong enough to "
                "end discovery, and the current search query is exhausted."
            ),
        }
    )

    _decide_step(
        controller,
        scenario="matching completion and replan",
        step=2,
        state=state,
        last_action="match_analysis",
        expected_actions={"build_search_plan"},
        user_profile=user_profile,
    )