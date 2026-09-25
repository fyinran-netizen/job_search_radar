from job_radar.agent.models import AgentError, AgentLimits, AgentState
from job_radar.agent.actions import AgentAction, execute_action
from job_radar.agent.work_manager import get_executable_count, is_followup_executable, take_action_batch
from job_radar.agent.policies.availability import action_availability
from job_radar.tools.explore_followups.models import ExploreFollowupsInput
from job_radar.tools.explore_followups.tool import ExploreFollowupsTool
from job_radar.tools.page_analysis.models import PendingFollowup
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.page_acquisition.models import PageDocument, RejectedPage
from job_radar.tools.web_search.models import CandidateSource


def followup(*, kind: str = "navigation_required", stage: str = "pre_extraction", links=None, priority: int = 80, url: str = "https://example.test/careers") -> PendingFollowup:
    return PendingFollowup(
        url=url,
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


def test_action_consumes_only_three_followups_and_second_call_handles_remaining() -> None:
    pending = [
        followup(url=f"https://example.test/careers/{index}", links=[{"url": f"https://example.test/jobs/{index}"}])
        for index in range(5)
    ]
    executor = ToolExecutor([ExploreFollowupsTool()])
    limits = AgentLimits(followup_batch_size=3)

    first = execute_action(
        AgentAction(action="explore_followups", rationale="Process followup batch"),
        AgentState(pending_followups=pending), executor, limits,
    )
    assert len(first.pending_followups) == 2
    assert [item.url for item in first.pending_followups] == [item.url for item in pending[3:]]

    second = execute_action(
        AgentAction(action="explore_followups", rationale="Process remaining followups"),
        first, executor, limits,
    )
    assert second.pending_followups == []
    assert len(second.processed_followup_urls) == 5


def test_selected_followup_is_consumed_even_when_no_new_href_is_enqueued() -> None:
    same_href = {"url": "https://example.test/jobs/shared"}
    state = AgentState(
        pending_followups=[
            followup(url="https://example.test/careers/a", links=[same_href]),
            followup(url="https://example.test/careers/b", links=[same_href]),
        ]
    )

    result = execute_action(
        AgentAction(action="explore_followups", rationale="Consume executable followups"),
        state, ToolExecutor([ExploreFollowupsTool()]), AgentLimits(followup_batch_size=2),
    )

    assert result.pending_followups == []
    assert [source.url for source in result.acquisition_queue] == ["https://example.test/jobs/shared"]


def test_same_parent_url_different_followups_are_consumed_by_item_not_parent() -> None:
    state = AgentState(
        pending_followups=[
            followup(stage="pre_extraction", links=[{"url": "https://example.test/jobs/pre"}]),
            followup(stage="post_extraction", links=[{"url": "https://example.test/jobs/post"}]),
        ]
    )

    result = execute_action(
        AgentAction(action="explore_followups", rationale="Process one followup"),
        state, ToolExecutor([ExploreFollowupsTool()]), AgentLimits(followup_batch_size=1),
    )

    assert len(result.pending_followups) == 1
    assert result.pending_followups[0].stage == "post_extraction"


def test_availability_requires_new_href() -> None:
    no_links = AgentState(pending_followups=[followup(links=[])])
    with_link = AgentState(pending_followups=[followup(links=[{"url": "https://example.test/jobs/1"}])])
    assert action_availability("explore_followups", no_links, AgentLimits()).available is False
    assert action_availability("explore_followups", with_link, AgentLimits()).available is True


def test_followup_executable_semantics_are_shared_by_count_availability_and_batch() -> None:
    def href_followup(url: str) -> PendingFollowup:
        return followup(url=f"https://example.test/parent/{url.rsplit('/', 1)[-1]}", links=[{"url": url}])

    queued = "https://example.test/queued"
    acquired = "https://example.test/acquired"
    rejected = "https://example.test/rejected"
    errored = "https://example.test/errored"
    explored = "https://example.test/explored"
    executable = "https://example.test/executable"
    state = AgentState(
        pending_followups=[href_followup(url) for url in [queued, acquired, rejected, errored, explored, executable]],
        acquisition_queue=[CandidateSource(url=queued, title="Queued", source_name="Example")],
        acquired_pages=[PageDocument(url=acquired, source_name="Example")],
        rejected_pages=[RejectedPage(url=rejected, source_name="Example", title="Rejected")],
        errors=[AgentError(stage="acquire_page", url=errored, reason="failed")],
        explored_followup_links=[explored],
    )

    assert get_executable_count(state, "explore_followups") == 1
    assert is_followup_executable(state, state.pending_followups[-1])
    assert not is_followup_executable(state, state.pending_followups[0])
    batch, remaining = take_action_batch(state, "explore_followups", 1)
    assert [item.links[0]["url"] for item in batch] == [executable]
    assert len(remaining) == 5
    assert action_availability("explore_followups", state, AgentLimits()).available is True

    exhausted = state.model_copy(update={"pending_followups": state.pending_followups[:-1]})
    assert get_executable_count(exhausted, "explore_followups") == 0
    assert action_availability("explore_followups", exhausted, AgentLimits()).available is False


def test_checkpoint_state_round_trips_explored_links() -> None:
    state = AgentState(explored_followup_links=["https://example.test/jobs/1"])
    restored = AgentState.model_validate(state.model_dump(mode="json"))
    assert restored == state

