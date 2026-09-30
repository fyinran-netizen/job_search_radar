from job_radar.agent.controllers.context import (
    AcquirePageOutcome,
    AnalyzePageOutcome,
    ExecutionMetrics,
    LastActionOutcome,
    build_scheduling_context,
)
from job_radar.agent.controllers.features import build_scheduling_features
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.tools.page_analysis.models import PendingFollowup
from job_radar.tools.web_search.models import CandidateSource


def _followup(**updates):
    data = {
        "url": "https://example.test/listing",
        "title": "Listing",
        "source_name": "test",
        "pending_kind": "navigation_required",
        "suggested_next_action": "fetch_detail_links",
    }
    data.update(updates)
    return PendingFollowup(**data)


def _features(state, limits=None, outcome=None):
    limits = limits or AgentLimits()
    context = build_scheduling_context(state, limits, [], last_outcome=outcome)
    return build_scheduling_features(state, limits, context, outcome)


def test_empty_state_has_zeroed_feature_groups():
    features = _features(AgentState())

    assert features.goal.total_match_assessments == 0
    assert features.goal.result_deficit == 8
    assert features.frontier.pending_count == 0
    assert all(backlog.pending == 0 for backlog in features.backlogs.values())
    assert features.results.recommendation_counts == {}
    assert features.recent_execution is None


def test_frontier_aggregates_priorities_semantics_and_executable_items():
    state = AgentState(
        pending_followups=[
            _followup(priority=90, evidence={"page_type": "job_listing", "confidence": "high"}, links=[{"href": "https://example.test/job"}]),
            _followup(priority=30, pending_kind="review_required", evidence={"page_type": "uncertain", "confidence": "low"}, links=[]),
            _followup(priority=80, stage="post_extraction", suggested_next_action="manual_review", links=[{"url": "https://example.test/review"}]),
        ]
    )
    features = _features(state)

    assert features.frontier.pending_count == 3
    assert features.frontier.executable_count == 2
    assert features.frontier.high_priority_executable_count == 2
    assert features.frontier.counts_by_pending_kind == {"navigation_required": 2, "review_required": 1}
    assert features.frontier.counts_by_stage["post_extraction"] == 1
    assert features.frontier.semantic_type_counts == {"job_listing": 1, "uncertain": 1}
    assert features.frontier.semantic_confidence_counts == {"high": 1, "low": 1}
    assert features.frontier.mean_priority == 200 / 3
    assert features.frontier.usable_link_count == 2


def test_backlogs_use_canonical_work_manager_and_batch_fill_ratios():
    state = AgentState(
        acquisition_queue=[CandidateSource(url="https://example.test/1", title="1", source_name="t")],
        pending_followups=[_followup(links=[{"href": "https://example.test/job"}])],
    )
    features = _features(state, AgentLimits(acquire_batch_size=4, followup_batch_size=2))

    assert features.backlogs["acquire_page"].pending == 1
    assert features.backlogs["acquire_page"].executable == 1
    assert features.backlogs["acquire_page"].batch_fill_ratio == 0.25
    assert features.backlogs["explore_followups"].batch_fill_ratio == 0.5


def test_outcome_payload_is_aggregated_with_execution_metrics():
    outcome = LastActionOutcome(
        action="acquire_page",
        status="partial",
        state_changed=True,
        execution=ExecutionMetrics(elapsed_ms=125.5, llm_calls=0, total_tokens=12),
        payload=AcquirePageOutcome(attempted=3, acquired=2, failed=1, queue_remaining=4),
    )
    features = _features(AgentState(), outcome=outcome)

    assert features.pipeline.acquisition_attempted == 3
    assert features.pipeline.acquisition_acquired == 2
    assert features.pipeline.acquisition_failed == 1
    assert features.pipeline.acquisition_success_ratio == 2 / 3
    assert features.recent_execution.elapsed_ms == 125.5
    assert features.recent_execution.total_tokens == 12


def test_analysis_outcome_exposes_observed_yields():
    outcome = LastActionOutcome(
        action="analyze_page",
        status="progress",
        state_changed=True,
        payload=AnalyzePageOutcome(
            pages_analyzed=4,
            job_detail_pages_added=2,
            followups_added=1,
            rejected_pages_added=1,
        ),
    )
    features = _features(AgentState(), outcome=outcome)

    assert features.pipeline.pages_analyzed == 4
    assert features.pipeline.job_detail_pages_produced == 2
    assert features.pipeline.analysis_followups_produced == 1
    assert features.pipeline.rejected_pages == 1
    assert features.pipeline.job_detail_yield == 0.5
    assert features.pipeline.rejection_ratio == 0.25


def test_result_distribution_and_deterministic_detail_counts():
    state = AgentState(
        match_assessments=[
            {"assessment": {"recommendation": "apply", "match_score": 90, "risk_flags": [], "missing_requirements": []}},
            {"assessment": {"recommendation": "consider", "match_score": 70, "risk_flags": ["x"], "missing_requirements": ["y"]}},
            {"assessment": {"recommendation": "skip", "match_score": 10, "risk_flags": [], "missing_requirements": []}},
        ]
    )
    features = _features(state, AgentLimits(soft_result_target=5))

    assert features.goal.useful_match_count == 2
    assert features.goal.result_deficit == 2
    assert features.results.recommendation_counts == {"apply": 1, "consider": 1, "skip": 1}
    assert features.results.apply_count == 1
    assert features.results.consider_count == 1
    assert features.results.average_match_score == 170 / 3
    assert features.results.risk_flagged_count == 1
    assert features.results.missing_requirement_count == 1


def test_search_provider_relevance_metadata_is_not_a_quality_feature():
    low = CandidateSource(url="https://example.test/a", title="A", source_name="t", relevance_score=1)
    high = CandidateSource(url="https://example.test/b", title="B", source_name="t", relevance_score=100)

    low_features = _features(AgentState(acquisition_queue=[low]))
    high_features = _features(AgentState(acquisition_queue=[high]))

    assert low_features.frontier == high_features.frontier
    assert low_features.results == high_features.results
    assert low_features.pipeline == high_features.pipeline
    assert low_features.backlogs["acquire_page"] == high_features.backlogs["acquire_page"]
