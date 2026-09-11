"""Opt-in behavior tests for the real LLM-backed workflow controller."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

import pytest

from job_radar.agent import LLMController
from job_radar.agent.action_names import AgentActionName
from job_radar.agent.controllers import DecisionContext
from job_radar.agent.controllers.llm_controller.observation.builder import build_observation
from job_radar.agent.controllers.llm_controller.prompt import build_controller_prompt
from job_radar.agent.models import AgentError, AgentLimits, AgentState, SearchOutcome
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
from job_radar.tools.web_search.models import CandidateSource, SearchPlan


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LLM_CONTROLLER_BEHAVIOR") != "1",
    reason="Real LLM behavior test; set RUN_LLM_CONTROLLER_BEHAVIOR=1 to run.",
)

REPORT_PATH = Path(__file__).resolve().parents[1] / "output" / "llm_controller_behavior_report.md"


def make_context(state: AgentState, available_actions: list[AgentActionName], *, profile: UserProfile | None = None, last_action: AgentActionName | None = None) -> DecisionContext:
    return DecisionContext(state=state, limits=AgentLimits(), profile=profile, available_actions=available_actions, last_action=last_action)


def profile() -> UserProfile:
    return UserProfile(target_roles=["AI Agent Engineer"])


def source() -> CandidateSource:
    return CandidateSource(url="https://example.test/job", title="AI Agent Engineer", source_name="Example")


def acquired_page() -> PageDocument:
    return PageDocument(url="https://example.test/job", source_name="Example")


def detail_page() -> AIPageInput:
    return AIPageInput(url="https://example.test/job", title="AI Agent Engineer", visible_text="Graduate AI Agent Engineer role. Python, LLM, RAG and agent workflow experience preferred.")


def prepared_job() -> JobRecord:
    return JobRecord(deduplication_key="example:ai-agent-engineer", title="AI Agent Engineer", company_name="Example", source_url="https://example.test/job", source_name="Example", description="Build AI agent workflows.")


def understanding_record() -> JobUnderstandingRecord:
    return JobUnderstandingRecord(
        deduplication_key="example:ai-agent-engineer",
        basic_gate=prepared_job().basic_gate,
        understanding=JobRequirementFacts(canonical_role="AI Agent Engineer", seniority="graduate", requirements=[RequirementFact(category="technical_skill", text="Python")], confidence="high"),
        source="ai",
    )


def ready_search_context() -> DecisionContext:
    return make_context(AgentState(search_plan=SearchPlan(keywords=["AI agent graduate jobs"])), ["web_search", "stop"], last_action="build_search_plan")


def replan_context() -> DecisionContext:
    return make_context(AgentState(search_plan=SearchPlan(keywords=["AI agent graduate jobs"]), executed_queries=["AI agent graduate jobs"], last_search_outcome=SearchOutcome.NO_PROGRESS), ["build_search_plan", "stop"], profile=profile(), last_action="web_search")


def acquisition_context() -> DecisionContext:
    return make_context(AgentState(selected_sources=[source()]), ["acquire_page", "stop"], last_action="web_search")


def analysis_context() -> DecisionContext:
    return make_context(AgentState(acquired_pages=[acquired_page()]), ["analyze_page", "stop"], last_action="acquire_page")


def extraction_context() -> DecisionContext:
    return make_context(AgentState(job_detail_pages=[detail_page()]), ["job_extraction", "stop"], profile=profile(), last_action="analyze_page")


def understanding_context() -> DecisionContext:
    return make_context(AgentState(prepared_jobs=[prepared_job()]), ["job_understanding", "stop"], profile=profile(), last_action="job_extraction")


def matching_context() -> DecisionContext:
    return make_context(AgentState(understanding_records=[understanding_record()]), ["match_analysis", "stop"], profile=profile(), last_action="job_understanding")


def page_choice_context() -> DecisionContext:
    return make_context(AgentState(acquired_pages=[acquired_page()], job_detail_pages=[detail_page()]), ["analyze_page", "job_extraction", "stop"], profile=profile(), last_action="acquire_page")


def extraction_choice_context() -> DecisionContext:
    state = AgentState(acquired_pages=[acquired_page()], job_detail_pages=[detail_page()], analyzed_page_urls=["https://example.test/job"])
    return make_context(state, ["analyze_page", "job_extraction", "stop"], profile=profile(), last_action="analyze_page")


def job_choice_context() -> DecisionContext:
    return make_context(AgentState(prepared_jobs=[prepared_job()], understanding_records=[understanding_record()]), ["job_understanding", "match_analysis", "stop"], profile=profile(), last_action="job_extraction")


def error_with_work_context() -> DecisionContext:
    return make_context(AgentState(selected_sources=[source()], errors=[AgentError(stage="web_search", reason="one source failed")]), ["acquire_page", "stop"], last_action="web_search")


def stop_context() -> DecisionContext:
    return make_context(AgentState(), ["stop"])


CASES: list[tuple[str, object, AgentActionName]] = [
    ("search has remaining query", ready_search_context, "web_search"),
    ("no search progress and replanning is available", replan_context, "build_search_plan"),
    ("selected source needs acquisition", acquisition_context, "acquire_page"),
    ("acquired page needs analysis", analysis_context, "analyze_page"),
    ("job detail page needs extraction", extraction_context, "job_extraction"),
    ("prepared jobs need understanding", understanding_context, "job_understanding"),
    ("understanding records need matching", matching_context, "match_analysis"),
    ("page analysis wins when both page stages have work", page_choice_context, "analyze_page"),
    ("extraction wins when analysis is complete", extraction_choice_context, "job_extraction"),
    ("understanding wins when both job stages have work", job_choice_context, "job_understanding"),
    ("errors do not stop remaining work", error_with_work_context, "acquire_page"),
    ("only stop is available", stop_context, "stop"),
]


@pytest.fixture(scope="module", autouse=True)
def behavior_report() -> None:
    load_project_env()
    model = load_runtime_settings().controller.model
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    run_label = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    with REPORT_PATH.open("a", encoding="utf-8") as report:
        report.write(f"\n## Run {run_label}\n\nModel: `{model}`\n\n")
        report.write("| Case | Model | Available Actions | Expected | Actual | Result | Rationale |\n|---|---|---|---|---|---|---|\n")


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _append_report(*, case_name: str, model: str, context: DecisionContext, expected_action: AgentActionName, actual_action: str, result: str, rationale: str, observation: object | None = None, prompt: str | None = None, exception: BaseException | None = None, parsed_decision: object | None = None) -> None:
    row_values = (case_name, model, ", ".join(context.available_actions), expected_action, actual_action, result, rationale)
    with REPORT_PATH.open("a", encoding="utf-8") as report:
        report.write("| " + " | ".join(_markdown_cell(value) for value in row_values) + " |\n")
        if result == "PASS":
            return
        report.write(f"\n### Debug: {case_name}\n\nModel: `{model}`\n\n")
        if observation is not None:
            report.write("Full ControllerObservation:\n\n```json\n" + observation.model_dump_json(indent=2) + "\n```\n\n")
        if prompt is not None:
            report.write("Full prompt:\n\n```text\n" + prompt + "\n```\n\n")
        if exception is not None:
            report.write("Exception / validation error:\n\n```text\n" + repr(exception) + "\n```\n\n")
        if parsed_decision is not None:
            report.write("Parsed decision:\n\n```json\n" + parsed_decision.model_dump_json(indent=2) + "\n```\n\n")


@pytest.mark.parametrize(("case_name", "context_factory", "expected_action"), CASES)
def test_llm_controller_behavior(case_name: str, context_factory, expected_action: AgentActionName) -> None:
    load_project_env()
    settings = load_runtime_settings()
    context = context_factory()
    observation = build_observation(context)
    prompt = build_controller_prompt(observation, context.available_actions)
    controller = LLMController(provider=OllamaProvider(model=settings.controller.model, base_url=settings.ollama_base_url), timeout_seconds=settings.controller.timeout_seconds)

    try:
        decision = controller.decide(context)
    except Exception as exc:
        _append_report(case_name=case_name, model=settings.controller.model, context=context, expected_action=expected_action, actual_action="<exception>", result="FAIL", rationale="", observation=observation, prompt=prompt, exception=exc)
        raise

    result = "PASS" if decision.action == expected_action else "FAIL"
    _append_report(case_name=case_name, model=settings.controller.model, context=context, expected_action=expected_action, actual_action=decision.action, result=result, rationale=decision.rationale, parsed_decision=decision)
    assert decision.action == expected_action
