from job_radar.agent.actions import AgentAction, available_actions, execute_action
from job_radar.agent.models import AgentLimits, AgentState
from tests.doubles.mock_ai_provider import MockAIProvider
from job_radar.profile.models import UserProfile
from job_radar.tools.job_extraction.tool import JobExtractionTool
from job_radar.tools.job_understanding.tool import JobUnderstandingTool
from job_radar.tools.match_analysis.tool import MatchAnalysisTool
from job_radar.tools.page_analysis.tool import PageAnalysisTool
from job_radar.tools.registry import create_mock_tool_executor
from job_radar.tools.web_search.models import SearchPlan
from job_radar.tools.search_plan import SearchPlanBuilder

from tests.fixtures.loaders import load_json


def _mock_provider(response: object) -> MockAIProvider:
    provider = MockAIProvider(response)
    provider.model = "mock-fixture"
    return provider


def test_mock_agent_action_sequence_updates_state_and_stops() -> None:
    profile = UserProfile.model_validate(load_json("profile/mock_profile.json"))
    source_expectations = load_json("sources/mock_search_expectations.json")
    page_expectations = load_json("pages/mock_page_expectations.json")
    job_expectations = load_json("jobs/mock_expected.json")
    initial_expectations = load_json("agent_states/initial.json")

    page_provider = _mock_provider(load_json("pages/mock_classification_response.json"))
    extraction_provider = _mock_provider(load_json("jobs/mock_extraction_response.json"))
    understanding_provider = _mock_provider(load_json("jobs/mock_understanding_response.json"))
    match_provider = _mock_provider(load_json("jobs/mock_match_response.json"))

    executor = create_mock_tool_executor()
    executor.tools.update(
        {
            "analyze_page": PageAnalysisTool(page_provider),
            "job_extraction": JobExtractionTool(extraction_provider),
            "job_understanding": JobUnderstandingTool(understanding_provider),
            "match_analysis": MatchAnalysisTool(match_provider),
        }
    )

    profile_plan = SearchPlanBuilder().build(profile)
    state = AgentState(
        round_index=initial_expectations["round_index"],
        stop_reason=initial_expectations["stop_reason"],
        search_plan=SearchPlan.model_validate(profile_plan),
    )
    limits = AgentLimits(max_rounds=1)
    decisions: list[dict[str, object]] = []
    selected_actions = [
        ("web_search", "Search the configured mock sources."),
        ("acquire_page", "Collect the selected mock pages."),
        ("analyze_page", "Process collected pages for extraction."),
        ("job_extraction", "Extract structured jobs from accepted pages."),
        ("job_understanding", "Understand requirements for prepared jobs."),
        ("match_analysis", "Assess the prepared jobs against the profile."),
        ("stop", "Stop after the configured one-round budget is exhausted."),
    ]

    for action_name, rationale in selected_actions:
        available = available_actions(state, limits, profile=profile)
        assert action_name in available
        decisions.append(
            {
                "selected_action": action_name,
                "rationale": rationale,
                "available_actions": available,
            }
        )
        state = execute_action(
            AgentAction(
                action=action_name,
                rationale=rationale,
                stop_reason=("max_rounds reached" if action_name == "stop" else None),
            ),
            state,
            executor,
            limits,
            profile=profile,
        )

    assert [item["selected_action"] for item in decisions] == [
        item[0] for item in selected_actions
    ]
    assert all(item["rationale"] for item in decisions)
    assert [event.tool_name for event in executor.events] == [
        "web_search",
        "acquire_page",
        "acquire_page",
        "acquire_page",
        "analyze_page",
        "job_extraction",
        "job_understanding",
        "match_analysis",
    ]

    assert state.round_index == 1
    assert len(state.candidate_sources) == source_expectations["candidate_count"]
    assert [source.url for source in state.candidate_sources] == source_expectations["candidate_urls"]
    assert len(state.selected_sources) == source_expectations["selected_count"]
    assert [source.url for source in state.selected_sources] == source_expectations["selected_urls"]
    assert len(state.acquired_pages) == page_expectations["collected_count"]
    assert [page.url for page in state.acquired_pages] == page_expectations["page_urls"]
    assert len(state.job_detail_pages) == 2
    assert len(state.prepared_jobs) == job_expectations["prepared_count"]
    assert [job.title for job in state.prepared_jobs] == job_expectations["expected_titles"]
    assert len(state.understanding_records) == 2
    assert len(state.match_assessments) == 2
    assert state.stop_reason == "max_rounds reached"
    assert "stop" not in available_actions(state, limits, profile=profile)
