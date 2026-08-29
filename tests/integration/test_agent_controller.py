import pytest

from job_radar.agent.actions import AgentAction
from job_radar.agent.controllers import DecisionContext, LLMController, RuleBasedController
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.profile.models import UserProfile
from job_radar.tools.job_extraction.models import AIPageInput
from job_radar.tools.page_collection.models import PageContent
from job_radar.tools.web_search.models import CandidateSource, SearchPlan


def decide(
    state: AgentState,
    *,
    limits: AgentLimits | None = None,
    profile: UserProfile | None = None,
) -> AgentAction:
    context = DecisionContext(
        state=state,
        limits=limits or AgentLimits(),
        profile=profile,
    )
    return RuleBasedController().decide(context)


def test_rule_based_controller_starts_search_when_plan_and_budget_are_available() -> None:
    decision = decide(AgentState(search_plan=SearchPlan(keywords=["graduate jobs"])))

    assert decision.action == "web_search"
    assert "search plan" in decision.rationale


def test_rule_based_controller_collects_unprocessed_selected_sources() -> None:
    source = CandidateSource(url="https://example.test/job", title="Job", source_name="Example")

    decision = decide(
        AgentState(
            selected_sources=[source],
            collected_pages=[PageContent(url="https://example.test/other", source_name="Example")],
        )
    )

    assert decision.action == "collect_page"
    assert "unprocessed" in decision.rationale


def test_rule_based_controller_processes_collected_pages() -> None:
    decision = decide(
        AgentState(
            search_plan=SearchPlan(keywords=["graduate jobs"]),
            collected_pages=[PageContent(url="https://example.test/job", source_name="Example")],
        )
    )

    assert decision.action == "page_processing"
    assert "processing" in decision.rationale


def test_rule_based_controller_extracts_from_processed_pages() -> None:
    decision = decide(
        AgentState(
            search_plan=SearchPlan(keywords=["graduate jobs"]),
            processed_pages=[
                AIPageInput(
                    url="https://example.test/job",
                    title="Example Job",
                    visible_text="Job description",
                )
            ],
        )
    )

    assert decision.action == "job_extraction"
    assert "extraction" in decision.rationale


def test_rule_based_controller_stops_when_search_budget_is_exhausted() -> None:
    decision = decide(
        AgentState(
            search_plan=SearchPlan(keywords=["graduate jobs"]),
            round_index=1,
        ),
        limits=AgentLimits(max_rounds=1),
    )

    assert decision.action == "stop"
    assert decision.stop_reason
    assert "stop condition" in decision.rationale


def test_llm_controller_is_reserved_without_model_or_prompt() -> None:
    context = DecisionContext(state=AgentState())

    with pytest.raises(NotImplementedError, match="no model, prompt, or API"):
        LLMController().decide(context)
