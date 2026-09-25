import pytest

from job_radar.agent.actions import (
    ActionPreconditionError,
    AgentAction,
    execute_action,
)
from job_radar.agent.policies.availability import action_availability
from job_radar.agent.policies.availability import available_actions
from job_radar.agent.models import AgentLimits, AgentState, SearchOutcome
from job_radar.tools.base import BaseTool
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.page_acquisition.models import PageDocument
from job_radar.tools.job_extraction.models import AIPageInput, RawJobRecord
from job_radar.tools.job_extraction.normalization import normalize_records
from job_radar.tools.job_understanding.models import JobUnderstandingRecord
from job_radar.tools.job_extraction.models import BasicGateResult
from job_radar.tools.web_search.models import CandidateSource, SearchPlan
from job_radar.profile.models import UserProfile


class RecordingSearchTool(BaseTool):
    name = "web_search"

    def run(self, payload):
        return [
            CandidateSource(
                url="https://example.test/job/1",
                title="Job 1",
                source_name="Example",
                relevance_score=90,
            )
        ]


class RecordingPageTool(BaseTool):
    name = "acquire_page"

    def __init__(self):
        self.urls = []

    def run(self, payload):
        self.urls.append(payload.url)
        return PageDocument(url=payload.url, source_name=payload.source_name, html="<html />")


def test_action_model_has_only_v1_actions_and_batch_collection():
    action = AgentAction(action="acquire_page", rationale="Collect selected sources")

    assert action.action == "acquire_page"
    assert "source_url" not in action.model_dump()
    with pytest.raises(ValueError, match="stop requires stop_reason"):
        AgentAction(action="stop", rationale="Done")


def test_action_availability_requires_stage_inputs():
    state = AgentState()
    limits = AgentLimits()

    assert action_availability("web_search", state, limits).reasons == ["search_plan is missing"]
    assert action_availability("acquire_page", state, limits).available is False
    assert action_availability("analyze_page", state, limits).available is False
    assert action_availability("job_extraction", state, limits).available is False
    assert action_availability("job_understanding", state, limits).available is False
    assert action_availability("match_analysis", state, limits).available is False
    assert "stop" in available_actions(state, limits)


def test_mixed_backlog_exposes_all_currently_valid_stage_actions() -> None:
    profile = UserProfile(target_roles=["Example Job"])
    job = normalize_records(
        [RawJobRecord(company_name="Example", title="Example Job", location="Sydney")]
    )[0]
    understanding = JobUnderstandingRecord(
        deduplication_key=job.deduplication_key,
        basic_gate=BasicGateResult(),
        source="ai",
    )
    state = AgentState(
        search_plan=SearchPlan(queries=["example jobs"]),
        acquisition_queue=[
            CandidateSource(url="https://example.test/queued", title="Queued", source_name="Example")
        ],
        acquired_pages=[PageDocument(url="https://example.test/acquired", source_name="Example")],
        job_detail_pages=[
            AIPageInput(url="https://example.test/detail", title="Example Job", visible_text="description")
        ],
        prepared_jobs=[job],
        understanding_records=[understanding],
    )

    assert available_actions(state, AgentLimits(), profile=profile) == [
        "web_search",
        "acquire_page",
        "analyze_page",
        "job_extraction",
        "job_understanding",
        "match_analysis",
    ]


def test_availability_has_no_scheduler_context() -> None:
    state = AgentState(
        search_plan=SearchPlan(queries=["example jobs"]),
        acquisition_queue=[
            CandidateSource(url="https://example.test/queued", title="Queued", source_name="Example")
        ],
    )
    limits = AgentLimits()

    assert available_actions(state, limits) == available_actions(state, limits)


def test_web_search_stays_in_round_and_selects_sources():
    state = AgentState(search_plan=SearchPlan(keywords=["graduate jobs"]))
    result = execute_action(
        AgentAction(action="web_search", rationale="Start search"),
        state,
        ToolExecutor([RecordingSearchTool()]),
        AgentLimits(),
    )

    assert result.round_index == 0
    assert len(result.candidate_sources) == 1
    assert len(result.selected_sources) == 1
    assert result.last_search_outcome is SearchOutcome.PROGRESS
    assert result.action_call_counts == {}


def test_web_search_admits_raw_source_even_when_it_is_only_discovery_history():
    source = CandidateSource(
        url="https://example.test/job/1?utm_source=history",
        title="Job 1",
        source_name="Example",
        relevance_score=90,
    )
    state = AgentState(
        search_plan=SearchPlan(keywords=["graduate jobs"]),
        candidate_sources=[source],
    )

    result = execute_action(
        AgentAction(action="web_search", rationale="Admit raw search results"),
        state,
        ToolExecutor([RecordingSearchTool()]),
        AgentLimits(),
    )

    assert [item.url for item in result.acquisition_queue] == ["https://example.test/job/1"]


def test_limited_action_call_budget_is_checked_and_counted_once():
    url = "https://example.test/job"
    state = AgentState(
        acquired_pages=[PageDocument(url=url, source_name="Example")],
    )
    limits = AgentLimits(action_call_limits={"analyze_page": 1})

    result = execute_action(
        AgentAction(action="analyze_page", rationale="Analyze page"),
        state,
        ToolExecutor(
            [
                _RecordingAnalysisTool(),
            ]
        ),
        limits,
    )

    assert result.action_call_counts == {"analyze_page": 1}
    availability = action_availability("analyze_page", result, limits)
    assert not availability.available
    assert availability.reasons == ["action call limit reached (1/1)", "all acquired_pages are already processed"]


class _RecordingAnalysisTool(BaseTool):
    name = "analyze_page"

    def run(self, payload):
        return {
            "accepted_pages": [],
            "pending_followups": [],
            "rejected_pages": [],
            "traces": [],
            "report": {},
        }


def test_acquire_page_is_batch_level_and_skips_already_handled_sources():
    first = CandidateSource(url="https://example.test/1", title="1", source_name="Example")
    second = CandidateSource(url="https://example.test/2", title="2", source_name="Example")
    page_tool = RecordingPageTool()
    state = AgentState(
        selected_sources=[first, second],
        acquired_pages=[PageDocument(url=first.url, source_name=first.source_name)],
    )

    result = execute_action(
        AgentAction(action="acquire_page", rationale="Collect remaining sources"),
        state,
        ToolExecutor([page_tool]),
        AgentLimits(),
    )

    assert page_tool.urls == [second.url]
    assert [page.url for page in result.acquired_pages] == [first.url, second.url]


def test_stage_actions_are_unavailable_after_their_batch_is_marked_complete():
    """Output presence is not completion; explicit stage markers are."""
    url = "https://example.test/job"
    job = normalize_records(
        [RawJobRecord(company_name="Example", title="Job", location="Sydney")]
    )[0]
    understanding = JobUnderstandingRecord(
        deduplication_key=job.deduplication_key,
        basic_gate=BasicGateResult(),
        source="ai",
    )
    state = AgentState(
        acquired_pages=[PageDocument(url=url, source_name="Example")],
        job_detail_pages=[
            AIPageInput(url=url, title="Job", visible_text="description")
        ],
        analyzed_page_urls=[url],
        extracted_page_urls=[url],
        prepared_jobs=[job],
        understood_job_keys=[job.deduplication_key],
        understanding_records=[understanding],
        matched_job_keys=[job.deduplication_key],
    )
    limits = AgentLimits()
    profile = UserProfile(target_roles=["Job"])

    assert not action_availability("analyze_page", state, limits).available
    assert not action_availability("job_extraction", state, limits).available
    assert not action_availability("job_understanding", state, limits, profile=profile).available
    assert not action_availability("match_analysis", state, limits, profile=profile).available


def test_max_rounds_and_max_results_are_hard_limits():
    plan_state = AgentState(search_plan=SearchPlan(keywords=["jobs"]), round_index=1)
    limits = AgentLimits(max_rounds=1)
    assert not action_availability("web_search", plan_state, limits).available

    job = normalize_records([RawJobRecord(company_name="Example", title="Job", location="Sydney")])[0]
    result_state = AgentState(
        search_plan=SearchPlan(keywords=["jobs"]),
        prepared_jobs=[job],
    )
    limits = AgentLimits(max_results=1)
    assert action_availability("web_search", result_state, limits).available


def test_search_and_acquisition_guards_do_not_read_prepared_jobs():
    source = CandidateSource(url="https://example.test/job", title="Job", source_name="Example")
    state = AgentState(
        search_plan=SearchPlan(keywords=["jobs"]),
        selected_sources=[source],
        prepared_jobs=[normalize_records([RawJobRecord(company_name="Example", title="Job", location="Sydney")])[0]],
    )

    limits = AgentLimits(max_results=1)
    assert action_availability("web_search", state, limits).available
    assert action_availability("acquire_page", state, limits).available


def test_job_extraction_requires_profile_at_availability_boundary():
    state = AgentState(
        job_detail_pages=[
            AIPageInput(url="https://example.test/job", title="Job", visible_text="description")
        ]
    )

    availability = action_availability("job_extraction", state, AgentLimits())

    assert not availability.available
    assert availability.reasons == ["profile is required by job_extraction"]


def test_stop_updates_stop_reason_and_requires_terminal_evidence():
    state = AgentState(round_index=3)
    result = execute_action(
        AgentAction(action="stop", rationale="Search budget exhausted", stop_reason="max_rounds reached"),
        state,
        ToolExecutor([]),
        AgentLimits(max_rounds=3),
    )
    assert result.stop_reason == "max_rounds reached"

    with pytest.raises(ActionPreconditionError, match="no deterministic stop condition"):
        execute_action(
            AgentAction(action="stop", rationale="Stop", stop_reason="manual"),
            AgentState(search_plan=SearchPlan(keywords=["jobs"])),
            ToolExecutor([]),
            AgentLimits(),
        )
