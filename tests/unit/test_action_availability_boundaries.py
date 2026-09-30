import pytest

from job_radar.agent.actions import ActionPreconditionError, AgentAction, execute_action
from job_radar.agent.models import AgentError, AgentLimits, AgentState, SearchOutcome
from job_radar.agent.policies.availability import action_availability, available_actions
from job_radar.profile.models import UserProfile
from job_radar.tools.explore_followups.models import PendingFollowup
from job_radar.tools.job_extraction.models import AIPageInput, BasicGateResult, RawJobRecord
from job_radar.tools.job_extraction.normalization import normalize_records
from job_radar.tools.job_understanding.models import JobUnderstandingRecord
from job_radar.tools.page_acquisition.models import PageDocument
from job_radar.tools.search_plan.models import SearchPlan
from job_radar.tools.web_search.models import CandidateSource
from job_radar.tools.executor import ToolExecutor


PROFILE = UserProfile(target_roles=["Example Job"])


def source(url: str = "https://example.test/source") -> CandidateSource:
    return CandidateSource(url=url, title="Example", source_name="Example")


def page(url: str = "https://example.test/page") -> PageDocument:
    return PageDocument(url=url, source_name="Example")


def detail(url: str = "https://example.test/detail") -> AIPageInput:
    return AIPageInput(url=url, title="Example Job", visible_text="Job description")


def job():
    return normalize_records(
        [RawJobRecord(company_name="Example", title="Example Job", location="Sydney")]
    )[0]


def understanding() -> JobUnderstandingRecord:
    record = job()
    return JobUnderstandingRecord(
        deduplication_key=record.deduplication_key,
        basic_gate=BasicGateResult(),
        source="ai",
    )


def followup(*, links: list[dict[str, str]], kind: str = "navigation_required") -> PendingFollowup:
    return PendingFollowup(
        url="https://example.test/parent",
        title="Example parent",
        source_name="Example",
        pending_kind=kind,
        suggested_next_action="fetch_detail_links",
        links=links,
    )


@pytest.mark.parametrize(
    ("action", "state", "profile", "reason"),
    [
        ("build_search_plan", AgentState(), None, "profile is required by build_search_plan"),
        (
            "job_extraction",
            AgentState(job_detail_pages=[detail()]),
            None,
            "profile is required by job_extraction",
        ),
        (
            "match_analysis",
            AgentState(understanding_records=[understanding()]),
            None,
            "profile is required by match_analysis",
        ),
    ],
)
def test_profile_is_required_at_each_profile_gated_boundary(
    action, state, profile, reason
) -> None:
    result = action_availability(action, state, AgentLimits(), profile=profile)

    assert result.available is False
    assert reason in result.reasons


def test_search_plan_requires_an_unexecuted_query_and_build_requires_no_active_plan() -> None:
    query = "example jobs"
    active = AgentState(search_plan=SearchPlan(queries=[query]))
    exhausted = active.model_copy(update={"executed_queries": [query]})

    assert action_availability("web_search", active, AgentLimits()).available is True
    assert action_availability("web_search", exhausted, AgentLimits()).available is False
    assert action_availability("build_search_plan", active, AgentLimits(), profile=PROFILE).available is False

    no_plan = AgentState()
    assert action_availability("build_search_plan", no_plan, AgentLimits(), profile=PROFILE).available is True
    assert action_availability("web_search", no_plan, AgentLimits()).available is False


def test_search_plan_with_one_remaining_query_stays_available_after_other_queries_are_executed() -> None:
    state = AgentState(
        search_plan=SearchPlan(queries=["done", "remaining"]),
        executed_queries=["done"],
    )

    result = action_availability("web_search", state, AgentLimits())

    assert result.available is True
    assert result.reasons == []


def test_completion_markers_only_remove_consumed_items_from_pending_work() -> None:
    state = AgentState(
        acquired_pages=[page("https://example.test/one"), page("https://example.test/two")],
        analyzed_page_urls=["https://example.test/one"],
    )

    assert action_availability("analyze_page", state, AgentLimits()).available is True

    completed = state.model_copy(
        update={"analyzed_page_urls": ["https://example.test/one", "https://example.test/two"]}
    )
    result = action_availability("analyze_page", completed, AgentLimits())

    assert result.available is False
    assert "all acquired_pages are already processed" in result.reasons


def test_different_backlogs_can_make_different_actions_available_together() -> None:
    record = job()
    state = AgentState(
        search_plan=SearchPlan(queries=["example jobs"]),
        acquisition_queue=[source("https://example.test/queued")],
        acquired_pages=[page()],
        job_detail_pages=[detail()],
        prepared_jobs=[record],
        understanding_records=[understanding()],
    )

    actions = available_actions(state, AgentLimits(), profile=PROFILE)

    assert actions == [
        "web_search",
        "acquire_page",
        "analyze_page",
        "job_extraction",
        "job_understanding",
        "match_analysis",
    ]


def test_action_call_limit_blocks_an_otherwise_valid_action() -> None:
    state = AgentState(
        search_plan=SearchPlan(queries=["example jobs"]),
        action_call_counts={"web_search": 1},
    )
    limits = AgentLimits(action_call_limits={"web_search": 1})

    result = action_availability("web_search", state, limits)

    assert result.available is False
    assert result.reasons == ["action call limit reached (1/1)"]


def test_round_and_result_limits_are_boundary_exclusive_for_their_actions() -> None:
    plan = SearchPlan(queries=["example jobs"])
    assert action_availability(
        "web_search", AgentState(search_plan=plan, round_index=1), AgentLimits(max_rounds=1)
    ).available is False

    assert action_availability(
        "build_search_plan", AgentState(search_round_count=1), AgentLimits(max_search_rounds=1), profile=PROFILE
    ).available is True

    result_state = AgentState(job_detail_pages=[detail()], prepared_jobs=[job()])
    assert action_availability(
        "job_extraction", result_state, AgentLimits(max_results=1), profile=PROFILE
    ).available is False


def test_stopped_state_has_no_available_actions_even_with_valid_backlogs() -> None:
    state = AgentState(
        stop_reason="finished",
        search_plan=SearchPlan(queries=["example jobs"]),
        acquisition_queue=[source()],
        acquired_pages=[page()],
        job_detail_pages=[detail()],
        prepared_jobs=[job()],
        understanding_records=[understanding()],
    )

    assert available_actions(state, AgentLimits(), profile=PROFILE) == []


@pytest.mark.parametrize(
    "state",
    [
        AgentState(round_index=1),
        AgentState(prepared_jobs=[job()]),
        AgentState(last_search_outcome=SearchOutcome.ERROR),
        AgentState(last_search_outcome=SearchOutcome.STOPPED_NO_PROGRESS),
        AgentState(errors=[AgentError(stage="web_search", reason="failed")]),
    ],
)
def test_stop_is_available_only_when_deterministic_evidence_exists(state: AgentState) -> None:
    limits = AgentLimits(max_rounds=1, max_results=1)
    result = action_availability("stop", state, limits)

    assert result.available is True


def test_stop_is_not_available_without_deterministic_evidence() -> None:
    result = action_availability("stop", AgentState(search_plan=SearchPlan(queries=["jobs"])), AgentLimits())

    assert result.available is False
    assert result.reasons == ["no deterministic stop condition is present"]


def test_non_executable_followups_do_not_make_explore_followups_available() -> None:
    states = [
        AgentState(pending_followups=[followup(links=[])]),
        AgentState(
            pending_followups=[followup(links=[{"href": "https://example.test/job"}])],
            explored_followup_links=["https://example.test/job"],
        ),
        AgentState(
            pending_followups=[followup(links=[{"href": "https://example.test/job"}], kind="review_required")]
        ),
    ]

    assert all(
        not action_availability("explore_followups", state, AgentLimits()).available
        for state in states
    )


@pytest.mark.parametrize(
    ("action", "state", "profile", "stop_reason"),
    [
        ("web_search", AgentState(), None, None),
        ("acquire_page", AgentState(), None, None),
        ("analyze_page", AgentState(), None, None),
        ("job_extraction", AgentState(job_detail_pages=[detail()]), None, None),
        ("job_understanding", AgentState(), None, None),
        ("match_analysis", AgentState(), PROFILE, None),
        ("explore_followups", AgentState(pending_followups=[followup(links=[])]), None, None),
        ("stop", AgentState(search_plan=SearchPlan(queries=["jobs"])), None, "manual stop"),
    ],
)
def test_execute_action_rechecks_unavailable_actions(
    action, state, profile, stop_reason
) -> None:
    request = AgentAction(
        action=action,
        rationale="Attempt unavailable action",
        stop_reason=stop_reason,
    )

    with pytest.raises(ActionPreconditionError):
        execute_action(request, state, ToolExecutor([]), AgentLimits(), profile=profile)
