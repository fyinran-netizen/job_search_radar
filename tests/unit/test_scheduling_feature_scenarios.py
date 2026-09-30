"""Manual/scenario checks for the pre-scoring scheduling feature layer."""

from job_radar.agent.controllers.context import build_scheduling_context
from job_radar.agent.controllers.features import SchedulingFeatures, build_scheduling_features
from job_radar.agent.controllers.scheduler import schedule_with_scores
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.tools.job_extraction.models import BasicGateResult
from job_radar.tools.job_understanding.models import JobUnderstandingRecord
from job_radar.tools.page_analysis.models import AIPageInput, PendingFollowup


def _followup(index: int, priority: int = 90) -> PendingFollowup:
    return PendingFollowup(
        url=f"https://scenario.test/followup/{index}",
        title=f"Followup {index}",
        source_name="scenario",
        pending_kind="navigation_required",
        suggested_next_action="fetch_detail_links",
        priority=priority,
        links=[{"href": f"https://scenario.test/detail/{index}"}],
    )


def _features(state: AgentState, limits: AgentLimits) -> SchedulingFeatures:
    context = build_scheduling_context(state, limits, [])
    return build_scheduling_features(state, limits, context)


def _understanding(index: int) -> JobUnderstandingRecord:
    return JobUnderstandingRecord(
        deduplication_key=f"job-{index}",
        basic_gate=BasicGateResult(),
        source="ai",
    )


def test_scheduling_feature_scenarios_are_auditable():
    state_a = AgentState(
            job_detail_pages=[
                AIPageInput(
                    url="https://scenario.test/job-detail",
                    title="Synthetic job",
                    visible_text="Synthetic job detail",
                )
            ],
            pending_followups=[_followup(1), _followup(2, priority=95)],
    )
    limits_a = AgentLimits(soft_result_target=10, extraction_batch_size=1, followup_batch_size=2)
    context_a = build_scheduling_context(state_a, limits_a, ["job_extraction", "explore_followups"])
    scenario_a = build_scheduling_features(state_a, limits_a, context_a)

    state_b = AgentState(
            understanding_records=[_understanding(1), _understanding(2), _understanding(3)],
            pending_followups=[_followup(index, priority=40) for index in range(1, 5)],
    )
    limits_b = AgentLimits(soft_result_target=1, match_batch_size=3, followup_batch_size=4)
    context_b = build_scheduling_context(state_b, limits_b, ["match_analysis", "explore_followups"])
    scenario_b = build_scheduling_features(state_b, limits_b, context_b)

    action_a, scores_a = schedule_with_scores(context_a, scenario_a)
    action_b, scores_b = schedule_with_scores(context_b, scenario_b)
    print("Scenario A SchedulingFeatures:\n" + scenario_a.model_dump_json(indent=2))
    print("Scenario A ActionScores:\n" + "\n".join(score.model_dump_json(indent=2) for score in scores_a))
    print("Scenario B SchedulingFeatures:\n" + scenario_b.model_dump_json(indent=2))
    print("Scenario B ActionScores:\n" + "\n".join(score.model_dump_json(indent=2) for score in scores_b))

    assert scenario_a.backlogs["job_extraction"].executable == 1
    assert scenario_a.backlogs["explore_followups"].executable == 2
    assert scenario_a.goal.result_deficit == 10
    assert scenario_a.frontier.mean_priority == 92.5
    assert scenario_a.frontier.high_priority_executable_count == 2
    assert action_a.action == "explore_followups"
    assert {score.action for score in scores_a} == {"job_extraction", "explore_followups"}

    assert scenario_b.backlogs["match_analysis"].executable == 3
    assert scenario_b.backlogs["explore_followups"].executable == 4
    assert scenario_b.goal.result_deficit == 1
    assert scenario_b.frontier.pending_count == 4
    assert action_b.action == "match_analysis"
    assert {score.action for score in scores_b} == {"match_analysis", "explore_followups"}
