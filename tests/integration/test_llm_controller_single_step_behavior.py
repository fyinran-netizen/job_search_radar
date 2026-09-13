"""Opt-in single-step behavior tests for the real LLM-backed workflow controller."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
from typing import Any

import pytest

from job_radar.agent import LLMController
from job_radar.agent.action_names import AgentActionName
from job_radar.agent.controllers import DecisionContext
from job_radar.agent.controllers.llm_controller.observation.builder import build_observation
from job_radar.agent.controllers.llm_controller.prompt import build_controller_prompt
from job_radar.agent.models import (
    AgentError,
    AgentLimits,
    AgentState,
    SearchOutcome,
)
from job_radar.config import load_project_env, load_runtime_settings
from job_radar.infra.llm.ollama import OllamaProvider
from job_radar.profile.models import UserProfile
from job_radar.tools.job_extraction.models import AIPageInput, JobRecord
from job_radar.tools.job_understanding.models import (
    JobRequirementFacts,
    JobUnderstandingRecord,
    RequirementFact,
)
from job_radar.tools.page_acquisition.models import PageDocument
from job_radar.tools.web_search.models import CandidateSource
from job_radar.tools.search_plan.models import SearchPlan


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LLM_CONTROLLER_BEHAVIOR") != "1",
    reason="Real LLM behavior test; set RUN_LLM_CONTROLLER_BEHAVIOR=1 to run.",
)

REPORT_PATH = (
    Path(__file__).resolve().parents[1]
    / "output"
    / "llm_controller_behavior_report.md"
)

DEBUG_RECORDS: list[dict[str, Any]] = []


def make_context(
    state: AgentState,
    available_actions: list[AgentActionName],
    *,
    profile: UserProfile | None = None,
    last_action: AgentActionName | None = None,
) -> DecisionContext:
    return DecisionContext(
        state=state,
        limits=AgentLimits(),
        profile=profile,
        available_actions=available_actions,
        last_action=last_action,
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
        source_name="Example",
    )


def detail_page() -> AIPageInput:
    return AIPageInput(
        url="https://example.test/job",
        title="AI Agent Engineer",
        visible_text=(
            "Graduate AI Agent Engineer role. "
            "Python, LLM, RAG and agent workflow experience preferred."
        ),
    )


def prepared_job() -> JobRecord:
    return JobRecord(
        deduplication_key="example:ai-agent-engineer",
        title="AI Agent Engineer",
        company_name="Example",
        source_url="https://example.test/job",
        source_name="Example",
        description="Build AI agent workflows.",
    )


def understanding_record() -> JobUnderstandingRecord:
    return JobUnderstandingRecord(
        deduplication_key="example:ai-agent-engineer",
        basic_gate=prepared_job().basic_gate,
        understanding=JobRequirementFacts(
            canonical_role="AI Agent Engineer",
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


def ready_search_context() -> DecisionContext:
    return make_context(
        AgentState(
            search_plan=SearchPlan(
                queries=["AI agent graduate jobs"],
                target_roles=["AI Agent Engineer"],
            ),
            last_action_summary=(
                "A search plan with one executable query is ready "
                "for the next discovery step."
            ),
        ),
        ["web_search", "build_search_plan", "stop"],
        last_action="build_search_plan",
    )


def replan_context() -> DecisionContext:
    return make_context(
        AgentState(
            search_plan=SearchPlan(
                queries=["AI agent graduate jobs"],
                target_roles=["AI Agent Engineer"],
            ),
            executed_queries=["AI agent graduate jobs"],
            last_search_outcome=SearchOutcome.NO_PROGRESS,
            last_action_summary=(
                "The previous web-search query produced no useful candidate sources. "
                "The current query is exhausted, but the target role remains unmet "
                "and alternative search directions have not yet been planned."
            ),
        ),
        ["build_search_plan", "web_search", "stop"],
        profile=profile(),
        last_action="web_search",
    )


def acquisition_context() -> DecisionContext:
    return make_context(
        AgentState(
            candidate_sources=[source()],
            selected_sources=[source()],
            last_search_outcome=SearchOutcome.PROGRESS,
            last_action_summary=(
                "The latest search found and selected a relevant new source "
                "that is ready for page acquisition."
            ),
        ),
        ["acquire_page", "web_search", "stop"],
        last_action="web_search",
    )


def analysis_context() -> DecisionContext:
    return make_context(
        AgentState(
            acquired_pages=[acquired_page()],
            last_action_summary=(
                "Page acquisition successfully acquired one page "
                "that still requires routing analysis."
            ),
        ),
        ["analyze_page", "job_extraction", "stop"],
        last_action="acquire_page",
    )


def extraction_context() -> DecisionContext:
    return make_context(
        AgentState(
            job_detail_pages=[detail_page()],
            last_action_summary=(
                "Page analysis identified one job-detail page "
                "that is ready for structured extraction."
            ),
        ),
        ["job_extraction", "analyze_page", "stop"],
        profile=profile(),
        last_action="analyze_page",
    )


def understanding_context() -> DecisionContext:
    return make_context(
        AgentState(
            prepared_jobs=[prepared_job()],
            last_action_summary=(
                "Job extraction produced one prepared job record "
                "that requires requirement understanding."
            ),
        ),
        ["job_understanding", "job_extraction", "stop"],
        profile=profile(),
        last_action="job_extraction",
    )


def matching_context() -> DecisionContext:
    return make_context(
        AgentState(
            understanding_records=[understanding_record()],
            last_action_summary=(
                "Job understanding produced a high-confidence structured "
                "requirement record ready for candidate matching."
            ),
        ),
        ["match_analysis", "job_understanding", "stop"],
        profile=profile(),
        last_action="job_understanding",
    )


def error_with_work_context() -> DecisionContext:
    return make_context(
        AgentState(
            candidate_sources=[source()],
            selected_sources=[source()],
            errors=[
                AgentError(
                    stage="web_search",
                    reason="one source failed",
                )
            ],
            last_search_outcome=SearchOutcome.PROGRESS,
            last_action_summary=(
                "The search had one source failure, but a relevant source "
                "was successfully selected and remains ready for acquisition."
            ),
        ),
        ["acquire_page", "web_search", "stop"],
        last_action="web_search",
    )


def stop_context() -> DecisionContext:
    return make_context(
        AgentState(
            last_action_summary=(
                "No actionable workflow work remains."
            ),
        ),
        ["stop"],
    )


CASES: list[
    tuple[str, object, AgentActionName]
] = [
    (
        "search has remaining query",
        ready_search_context,
        "web_search",
    ),
    (
        "no search progress and replanning is available",
        replan_context,
        "build_search_plan",
    ),
    (
        "selected source needs acquisition",
        acquisition_context,
        "acquire_page",
    ),
    (
        "acquired page needs analysis",
        analysis_context,
        "analyze_page",
    ),
    (
        "job detail page needs extraction",
        extraction_context,
        "job_extraction",
    ),
    (
        "prepared jobs need understanding",
        understanding_context,
        "job_understanding",
    ),
    (
        "understanding records need matching",
        matching_context,
        "match_analysis",
    ),
    (
        "errors do not stop remaining work",
        error_with_work_context,
        "acquire_page",
    ),
    (
        "only stop is available",
        stop_context,
        "stop",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def behavior_report():
    load_project_env()
    model = load_runtime_settings().controller.model

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    run_label = datetime.now().astimezone().strftime(
        "%Y-%m-%d %H:%M"
    )

    DEBUG_RECORDS.clear()

    with REPORT_PATH.open(
        "a",
        encoding="utf-8",
    ) as report:
        report.write(
            f"\n## Run {run_label}\n\n"
            f"Model: `{model}`\n\n"
            "Context version: "
            "`after last_action_summary / controller context refactor`\n\n"
        )

        report.write(
            "| Case | Model | Available Actions | Expected | Actual | "
            "Result | Rationale | Last Action Summary |\n"
        )

        report.write(
            "|---|---|---|---|---|---|---|---|\n"
        )

    yield

    if not DEBUG_RECORDS:
        return

    with REPORT_PATH.open(
        "a",
        encoding="utf-8",
    ) as report:
        report.write("\n### Failed case details\n\n")

        for record in DEBUG_RECORDS:
            report.write(
                f"#### {record['case_name']}\n\n"
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

            parsed_decision = record.get(
                "parsed_decision"
            )
            if parsed_decision is not None:
                report.write(
                    "Parsed decision:\n\n"
                    "```json\n"
                    f"{parsed_decision.model_dump_json(indent=2)}\n"
                    "```\n\n"
                )


def _markdown_cell(value: object) -> str:
    return (
        str(value)
        .replace("|", "\\|")
        .replace("\n", " ")
    )


def _append_report_row(
    *,
    case_name: str,
    model: str,
    context: DecisionContext,
    expected_action: AgentActionName,
    actual_action: str,
    result: str,
    rationale: str,
) -> None:
    row_values = (
        case_name,
        model,
        ", ".join(context.available_actions),
        expected_action,
        actual_action,
        result,
        rationale,
        context.state.last_action_summary or "",
    )

    with REPORT_PATH.open(
        "a",
        encoding="utf-8",
    ) as report:
        report.write(
            "| "
            + " | ".join(
                _markdown_cell(value)
                for value in row_values
            )
            + " |\n"
        )


def _record_debug(
    *,
    case_name: str,
    model: str,
    observation: object | None = None,
    prompt: str | None = None,
    exception: BaseException | None = None,
    parsed_decision: object | None = None,
) -> None:
    DEBUG_RECORDS.append(
        {
            "case_name": case_name,
            "model": model,
            "observation": observation,
            "prompt": prompt,
            "exception": exception,
            "parsed_decision": parsed_decision,
        }
    )


@pytest.mark.parametrize(
    (
        "case_name",
        "context_factory",
        "expected_action",
    ),
    CASES,
)
def test_llm_controller_single_step_behavior(
    case_name: str,
    context_factory,
    expected_action: AgentActionName,
) -> None:
    load_project_env()
    settings = load_runtime_settings()

    context = context_factory()

    observation = build_observation(
        context
    )

    prompt = build_controller_prompt(
        observation,
        context.available_actions,
    )

    controller = LLMController(
        provider=OllamaProvider(
            model=settings.controller.model,
            base_url=settings.ollama_base_url,
        ),
        timeout_seconds=settings.controller.timeout_seconds,
    )

    try:
        decision = controller.decide(
            context
        )
    except Exception as exc:
        _append_report_row(
            case_name=case_name,
            model=settings.controller.model,
            context=context,
            expected_action=expected_action,
            actual_action="<exception>",
            result="FAIL",
            rationale="",
        )

        _record_debug(
            case_name=case_name,
            model=settings.controller.model,
            observation=observation,
            prompt=prompt,
            exception=exc,
        )

        raise

    result = (
        "PASS"
        if decision.action == expected_action
        else "FAIL"
    )

    _append_report_row(
        case_name=case_name,
        model=settings.controller.model,
        context=context,
        expected_action=expected_action,
        actual_action=decision.action,
        result=result,
        rationale=decision.rationale,
    )

    if result == "FAIL":
        _record_debug(
            case_name=case_name,
            model=settings.controller.model,
            observation=observation,
            prompt=prompt,
            parsed_decision=decision,
        )

    assert decision.action == expected_action