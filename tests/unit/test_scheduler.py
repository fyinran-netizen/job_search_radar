from job_radar.agent.controllers.context import (
    ActionBacklog,
    AnalyzePageOutcome,
    CommonContext,
    LastActionOutcome,
    SchedulerBudget,
    SchedulingContext,
    SpecificContext,
    build_scheduling_context,
)
from job_radar.agent.controllers.outcome import build_outcome
from job_radar.agent.controllers.scheduler import schedule
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.agent.policies.availability import available_actions
from job_radar.profile.models import UserProfile
from job_radar.tools.page_acquisition.models import PageDocument
from job_radar.tools.job_extraction.models import JobRecord
from job_radar.tools.search_plan.models import SearchPlan


PROFILE = UserProfile(target_roles=["Data Analyst"])


def context(state: AgentState, profile: UserProfile | None = PROFILE, limits: AgentLimits | None = None):
    limits = limits or AgentLimits()
    available = available_actions(state, limits, profile=profile)
    return build_scheduling_context(state, limits, available)


def test_scheduler_drains_pipeline_before_spending_search_budget():
    state = AgentState(
        search_plan=SearchPlan(queries=["jobs"]),
        acquisition_queue=[],
        acquired_pages=[PageDocument(url="https://example.test/job", source_name="Example")],
    )
    assert schedule(context(state)).action == "analyze_page"


def test_scheduler_searches_active_plan_after_no_backlog():
    assert schedule(context(AgentState(search_plan=SearchPlan(queries=["jobs"])))).action == "web_search"


def test_scheduler_builds_plan_when_no_active_plan_exists():
    assert schedule(context(AgentState())).action == "build_search_plan"


def test_scheduler_uses_stop_only_when_available():
    state = AgentState(round_index=1)
    assert schedule(context(state, limits=AgentLimits(max_rounds=1))).action == "stop"


def test_outcome_is_structured_and_deterministic():
    before = AgentState()
    after = before.model_copy(update={"search_round_count": 1})
    outcome = build_outcome("web_search", before, after)
    assert outcome.action == "web_search"
    assert outcome.status == "no_progress"
    assert outcome.state_changed is True
    assert outcome.payload.kind == "web_search"


def test_context_has_three_layers_and_scopes_specific_backlogs():
    state = AgentState(search_plan=SearchPlan(queries=["jobs"]))
    built = context(state)

    assert built.common.progress.match_result_count == 0
    assert built.specific.available_actions == ["web_search"]
    assert set(built.specific.backlogs) == set()
    assert built.specific.search_plan_active is True
    assert built.last_outcome is None


def test_every_action_has_a_discriminated_payload():
    actions = (
        "build_search_plan", "web_search", "acquire_page", "analyze_page",
        "job_extraction", "explore_followups", "job_understanding",
        "match_analysis", "stop",
    )
    for action in actions:
        before = AgentState()
        after = AgentState(stop_reason="done") if action == "stop" else AgentState()
        outcome = build_outcome(action, before, after)
        assert outcome.payload.kind == action
        assert outcome.status == ("stopped" if action == "stop" else "no_progress")


def test_batch_failure_with_state_progress_is_partial():
    from job_radar.agent.models import AgentError

    before = AgentState(acquisition_queue=[])
    after = AgentState(
        acquired_pages=[PageDocument(url="https://example.test/job", source_name="Example")],
        errors=[AgentError(stage="acquire_page", reason="one source failed")],
    )
    outcome = build_outcome("acquire_page", before, after)

    assert outcome.status == "partial"
    assert outcome.state_changed is True
    assert outcome.errors_added == 1
    assert outcome.payload.kind == "acquire_page"


def manual_context(
    *actions: str,
    last_outcome=None,
    soft_scope_reached=False,
    search_plan_active=None,
    search_queries_remaining=None,
    match_result_count=0,
    backlog_overrides=None,
    round_match_result_count=0,
    round_steps_remaining=999,
    round_result_target=3,
    refill_budget_remaining=2,
):
    return SchedulingContext(
        common=CommonContext(
            budget=SchedulerBudget(
                search_rounds_remaining=2,
                results_remaining=10,
                soft_result_target=8,
                soft_scope_reached=soft_scope_reached,
                round_result_target=round_result_target,
                round_match_result_count=round_match_result_count,
                round_steps_remaining=round_steps_remaining,
                refill_budget_remaining=refill_budget_remaining,
            ),
            progress={"match_result_count": match_result_count},
        ),
        specific=SpecificContext(
            available_actions=list(actions),
            backlogs={
                action: ActionBacklog(
                    pending=(backlog_overrides or {}).get(action, {}).get("pending", 1),
                    executable=(backlog_overrides or {}).get(action, {}).get("executable", 1),
                    batch_size=(backlog_overrides or {}).get(action, {}).get("batch_size", 3),
                )
                for action in actions
                if action != "stop"
            },
            search_plan_active=search_plan_active,
            search_queries_remaining=search_queries_remaining,
        ),
        last_outcome=last_outcome,
    )


def test_scheduler_prefers_downstream_continuation_without_using_fixed_work_order():
    outcome = LastActionOutcome(
        action="analyze_page",
        status="progress",
        state_changed=True,
        payload=AnalyzePageOutcome(
            pages_analyzed=2,
            job_detail_pages_added=1,
            followups_added=1,
            rejected_pages_added=0,
        ),
    )
    decision = schedule(manual_context("explore_followups", "job_extraction", last_outcome=outcome))
    assert decision.action == "job_extraction"
    assert "downstream" in decision.rationale


def test_continuation_is_not_an_absolute_priority_over_higher_value_work():
    outcome = LastActionOutcome(
        action="analyze_page",
        status="progress",
        state_changed=True,
        payload=AnalyzePageOutcome(
            pages_analyzed=1,
            job_detail_pages_added=0,
            followups_added=1,
            rejected_pages_added=0,
        ),
    )
    decision = schedule(manual_context("job_extraction", "explore_followups", last_outcome=outcome))
    assert decision.action == "job_extraction"
    assert "actually produced" not in decision.rationale


def test_extraction_followups_only_continues_to_explore_followups():
    from job_radar.agent.controllers.context import JobExtractionOutcome

    outcome = LastActionOutcome(
        action="job_extraction",
        status="progress",
        state_changed=True,
        payload=JobExtractionOutcome(
            pages_extracted=1,
            prepared_jobs_added=0,
            pending_followups_added=1,
        ),
    )
    decision = schedule(manual_context("job_understanding", "explore_followups", last_outcome=outcome))
    assert decision.action == "job_understanding"


def test_partial_extraction_batch_can_hold_when_results_already_exist():
    decision = schedule(manual_context(
        "job_extraction", "analyze_page",
        match_result_count=1,
        backlog_overrides={
            "job_extraction": {"executable": 1},
            "analyze_page": {"executable": 3},
        },
    ))
    assert decision.action == "analyze_page"
    assert "holding partial downstream" in decision.rationale


def test_partial_downstream_batch_is_not_held_before_first_result():
    decision = schedule(manual_context(
        "job_extraction", "analyze_page",
        match_result_count=0,
        backlog_overrides={
            "job_extraction": {"executable": 1},
            "analyze_page": {"executable": 3},
        },
    ))
    assert decision.action == "job_extraction"


def test_partial_understanding_can_hold_for_a_full_upstream_batch():
    decision = schedule(manual_context(
        "job_understanding", "job_extraction",
        match_result_count=1,
        backlog_overrides={
            "job_understanding": {"executable": 1},
            "job_extraction": {"executable": 3},
        },
    ))
    assert decision.action == "job_extraction"


def test_full_downstream_batch_is_not_held():
    decision = schedule(manual_context(
        "job_understanding", "job_extraction",
        match_result_count=1,
        backlog_overrides={
            "job_understanding": {"executable": 3},
            "job_extraction": {"executable": 3},
        },
    ))
    assert decision.action == "job_understanding"


def test_downstream_is_not_held_when_upstream_is_exhausted():
    decision = schedule(manual_context(
        "job_understanding",
        match_result_count=1,
        backlog_overrides={"job_understanding": {"executable": 1}},
    ))
    assert decision.action == "job_understanding"


def test_scheduler_partial_outcome_continues_to_valid_downstream_work():
    outcome = LastActionOutcome(
        action="analyze_page",
        status="partial",
        state_changed=True,
        errors_added=1,
        payload=AnalyzePageOutcome(
            pages_analyzed=2,
            job_detail_pages_added=1,
            followups_added=0,
            rejected_pages_added=0,
        ),
    )
    assert schedule(manual_context("job_extraction", last_outcome=outcome)).action == "job_extraction"


def test_scheduler_no_progress_avoids_repeating_same_action_when_alternative_exists():
    outcome = LastActionOutcome(
        action="analyze_page",
        status="no_progress",
        state_changed=True,
        payload=AnalyzePageOutcome(
            pages_analyzed=1,
            job_detail_pages_added=0,
            followups_added=0,
            rejected_pages_added=0,
        ),
    )
    assert schedule(manual_context("analyze_page", "acquire_page", last_outcome=outcome)).action == "acquire_page"


def test_scheduler_no_progress_defers_same_action_to_search_fallback():
    outcome = LastActionOutcome(
        action="analyze_page",
        status="no_progress",
        state_changed=True,
        payload=AnalyzePageOutcome(
            pages_analyzed=1,
            job_detail_pages_added=0,
            followups_added=0,
            rejected_pages_added=0,
        ),
    )
    decision = schedule(manual_context(
        "analyze_page", "web_search", last_outcome=outcome,
        search_plan_active=True, search_queries_remaining=1,
    ))
    assert decision.action == "web_search"


def test_scheduler_error_defers_same_action_to_soft_close():
    outcome = LastActionOutcome(
        action="analyze_page",
        status="error",
        state_changed=True,
        errors_added=1,
        payload=AnalyzePageOutcome(
            pages_analyzed=1,
            job_detail_pages_added=0,
            followups_added=0,
            rejected_pages_added=0,
        ),
    )
    decision = schedule(manual_context("analyze_page", "stop", last_outcome=outcome, soft_scope_reached=True))
    assert decision.action == "stop"


def test_scheduler_error_switches_to_other_productive_path():
    outcome = LastActionOutcome(
        action="job_understanding",
        status="error",
        state_changed=True,
        errors_added=1,
        payload={"kind": "job_understanding", "jobs_processed": 1, "records_added": 0},
    )
    decision = schedule(manual_context("job_understanding", "match_analysis", last_outcome=outcome))
    assert decision.action == "match_analysis"
    assert "switched away" in decision.rationale


def test_scheduler_soft_scope_stops_only_when_stop_is_available():
    decision = schedule(manual_context("stop", soft_scope_reached=True))
    assert decision.action == "stop"
    assert "soft result target" in decision.rationale


def test_soft_scope_with_search_plan_does_not_continue_web_search():
    state = AgentState(
        search_plan=SearchPlan(queries=["another search"]),
        match_assessments=[{} for _ in range(8)],
    )
    decision = schedule(context(state))
    assert decision.action == "stop"


def test_soft_scope_still_processes_existing_downstream_work():
    state = AgentState(
        acquired_pages=[PageDocument(url="https://example.test/job", source_name="Example")],
        match_assessments=[{} for _ in range(8)],
    )
    decision = schedule(context(state))
    assert decision.action == "analyze_page"


def test_scheduler_uses_cost_only_for_value_ties():
    decision = schedule(manual_context("acquire_page", "explore_followups"))
    assert decision.action == "explore_followups"


def test_scheduler_uses_stable_downstream_tie_break_after_cost_tie():
    decision = schedule(manual_context("analyze_page", "job_extraction"))
    assert decision.action == "job_extraction"


def test_round_result_target_does_not_override_current_frontier_in_scheduler():
    decision = schedule(manual_context(
        "analyze_page", "web_search",
        search_plan_active=True,
        search_queries_remaining=1,
        round_match_result_count=3,
        round_result_target=3,
    ))
    assert decision.action == "analyze_page"


def test_round_step_budget_does_not_override_current_frontier_in_scheduler():
    decision = schedule(manual_context(
        "analyze_page", "web_search",
        search_plan_active=True,
        search_queries_remaining=1,
        round_steps_remaining=0,
    ))
    assert decision.action == "analyze_page"


def test_refill_budget_exhaustion_releases_partial_llm_batch():
    decision = schedule(manual_context(
        "job_understanding", "job_extraction",
        match_result_count=1,
        refill_budget_remaining=0,
        backlog_overrides={
            "job_understanding": {"executable": 1},
            "job_extraction": {"executable": 3},
        },
    ))
    assert decision.action == "job_understanding"


def test_search_round_limit_keeps_existing_frontier_work_schedulable():
    state = AgentState(
        search_round_count=1,
        search_plan=SearchPlan(queries=["jobs"]),
        acquired_pages=[PageDocument(url="https://example.test/job", source_name="Example")],
    )
    assert schedule(context(state, limits=AgentLimits(max_search_rounds=1))).action == "analyze_page"


def test_search_round_limit_stops_when_no_productive_frontier_remains():
    state = AgentState(search_round_count=1, search_plan=SearchPlan(queries=["jobs"]))
    assert schedule(context(state, limits=AgentLimits(max_search_rounds=1))).action == "stop"


def test_hard_result_cap_stops_even_if_search_is_available():
    state = AgentState(
        search_plan=SearchPlan(queries=["jobs"]),
        prepared_jobs=[JobRecord.model_construct(deduplication_key="job-1")],
    )
    assert schedule(context(state, limits=AgentLimits(max_results=1))).action == "stop"
