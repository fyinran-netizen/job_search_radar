from job_radar.agent.controllers.base import DecisionContext
from job_radar.agent.controllers.llm_controller.observation.builder import build_observation
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.agent.actions import AgentAction, execute_action
from job_radar.agent.policies.availability import action_availability
from job_radar.agent.policies.transition import transition_allowed_actions
from job_radar.tools.explore_followups.models import ExploreFollowupsInput
from job_radar.tools.explore_followups.tool import ExploreFollowupsTool
from job_radar.tools.page_analysis.models import PendingFollowup
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.web_search.models import CandidateSource


def followup(*, kind: str = "navigation_required", stage: str = "pre_extraction", links=None, priority: int = 80) -> PendingFollowup:
    return PendingFollowup(
        url="https://example.test/careers",
        title="Example careers",
        source_name="Example",
        company_name="Example Co",
        company_type="Technology",
        is_official=True,
        pending_kind=kind,
        suggested_next_action="fetch_detail_links",
        priority=priority,
        links=links or [],
        stage=stage,
    )


def test_explicit_href_produces_provenance_preserving_source() -> None:
    result = ExploreFollowupsTool().run(
        ExploreFollowupsInput(
            pending_followups=[
                followup(links=[{"url": "https://example.test/jobs/1", "text": "Data Analyst"}])
            ]
        )
    )

    assert [source.url for source in result.sources] == ["https://example.test/jobs/1"]
    source = result.sources[0]
    assert source.title == "Data Analyst"
    assert source.company_name == "Example Co"
    assert source.is_official is True
    assert "https://example.test/careers" in source.reason


def test_duplicate_handled_and_invalid_hrefs_are_skipped() -> None:
    pending = followup(
        links=[
            {"href": "https://example.test/jobs/1?utm_source=test", "text": "one"},
            {"url": "https://example.test/jobs/1", "text": "duplicate"},
            {"url": "javascript:void(0)", "text": "invalid"},
            {"url": "https://example.test/jobs/2", "text": "two"},
        ]
    )
    result = ExploreFollowupsTool().run(
        ExploreFollowupsInput(
            pending_followups=[pending],
            excluded_urls={"https://example.test/jobs/1"},
        )
    )

    assert [source.url for source in result.sources] == ["https://example.test/jobs/2"]
    assert result.explored_links == ["https://example.test/jobs/2"]
    assert result.resolutions[0].skipped_count == 3


def test_unsupported_and_linkless_followups_remain_unresolved() -> None:
    result = ExploreFollowupsTool().run(
        ExploreFollowupsInput(
            pending_followups=[
                followup(kind="review_required", links=[{"url": "https://example.test/review"}]),
                followup(links=[]),
            ]
        )
    )

    assert result.sources == []
    assert [item.status for item in result.resolutions] == ["unsupported", "no_usable_links"]


def test_pre_and_post_extraction_navigation_followups_are_supported() -> None:
    result = ExploreFollowupsTool().run(
        ExploreFollowupsInput(
            pending_followups=[
                followup(stage="pre_extraction", links=[{"url": "https://example.test/pre"}]),
                followup(stage="post_extraction", links=[{"url": "https://example.test/post"}]),
            ]
        )
    )

    assert [source.url for source in result.sources] == [
        "https://example.test/pre",
        "https://example.test/post",
    ]
    assert [item.stage for item in result.resolutions] == ["pre_extraction", "post_extraction"]


def test_same_followup_links_are_not_repeated() -> None:
    pending = followup(links=[{"url": "https://example.test/jobs/1"}])
    first = ExploreFollowupsTool().run(ExploreFollowupsInput(pending_followups=[pending]))
    second = ExploreFollowupsTool().run(
        ExploreFollowupsInput(
            pending_followups=[pending],
            explored_links=set(first.explored_links),
        )
    )

    assert len(first.sources) == 1
    assert second.sources == []
    assert second.resolutions[0].status == "already_explored"


def test_action_updates_selected_sources_and_explored_state() -> None:
    pending = followup(links=[{"url": "https://example.test/jobs/1"}])
    state = AgentState(pending_followups=[pending])
    result = execute_action(
        AgentAction(action="explore_followups", rationale="Follow explicit job links"),
        state,
        ToolExecutor([ExploreFollowupsTool()]),
        AgentLimits(),
    )

    assert [source.url for source in result.selected_sources] == ["https://example.test/jobs/1"]
    assert result.explored_followup_links == ["https://example.test/jobs/1"]
    assert result.followup_resolutions[0]["status"] == "explored"
    assert action_availability("explore_followups", result, AgentLimits()).available is False


def test_availability_requires_new_href_and_transitions_are_scoped() -> None:
    no_links = AgentState(pending_followups=[followup(links=[])])
    with_link = AgentState(pending_followups=[followup(links=[{"url": "https://example.test/jobs/1"}])])
    assert action_availability("explore_followups", no_links, AgentLimits()).available is False
    assert action_availability("explore_followups", with_link, AgentLimits()).available is True
    assert "explore_followups" in transition_allowed_actions("analyze_page")
    assert "explore_followups" in transition_allowed_actions("job_extraction")
    assert transition_allowed_actions("explore_followups") == ["acquire_page", "stop"]


def test_checkpoint_state_round_trips_explored_links() -> None:
    state = AgentState(explored_followup_links=["https://example.test/jobs/1"])
    restored = AgentState.model_validate(state.model_dump(mode="json"))
    assert restored == state


def test_controller_observation_exposes_compact_followup_counts() -> None:
    state = AgentState(
        pending_followups=[
            followup(stage="pre_extraction", links=[{"url": "https://example.test/pre"}], priority=90),
            followup(stage="post_extraction", links=[]),
            followup(kind="review_required", links=[{"url": "https://example.test/review"}]),
        ]
    )
    observation = build_observation(
        DecisionContext(
            state=state,
            limits=AgentLimits(),
            available_actions=["explore_followups"],
        )
    )

    assert observation.followups is not None
    assert observation.followups.navigation_pending_count == 2
    assert observation.followups.executable_followup_count == 1
    assert observation.followups.high_priority_executable_count == 1
    assert observation.followups.pre_extraction_count == 1
    assert observation.followups.post_extraction_count == 1
