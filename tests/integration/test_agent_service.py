from job_radar.agent.models import AgentLimits, AgentState
from job_radar.profile.models import UserProfile
from job_radar.services.agent_service import AgentService
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.web_search.providers.mock import MockWebSearchTool
from job_radar.tools.web_search.models import SearchPlan
import pytest
import sqlite3
import gc

from job_radar.services.persistence import JobPersistenceService
from tests.integration.test_repository import make_job


def test_agent_service_runs_deterministic_scheduler_and_records_trace() -> None:
    service = AgentService(
        executor=ToolExecutor([MockWebSearchTool()]),
        limits=AgentLimits(max_rounds=1),
    )

    result = service.run(
        UserProfile(target_roles=["Data Analyst"]),
        initial_state=AgentState(
            search_plan=SearchPlan(keywords=["graduate jobs"]),
        ),
    )

    assert result.state.stop_reason == "max_rounds"
    assert result.state.round_index == 1
    assert result.state.round_end_reason == "no_progress"
    assert [entry.selected_action for entry in result.decision_trace] == [
        "web_search",
        "acquire_page",
        "stop",
    ]
    assert result.decision_trace[0].available_actions == ["web_search"]
    assert result.decision_trace[0].state_summary["round_index"] == 0
    assert result.decision_trace[1].state_summary["round_index"] == 0


def test_agent_service_rejects_an_action_that_does_not_change_state(monkeypatch) -> None:
    import job_radar.services.agent_service as agent_service_module

    monkeypatch.setattr(
        agent_service_module,
        "execute_action",
        lambda action, state, executor, limits, profile=None: state,
    )
    service = AgentService(
        executor=ToolExecutor([]),
        limits=AgentLimits(max_rounds=1),
    )

    with pytest.raises(RuntimeError, match="did not change State"):
        service.run(
            UserProfile(target_roles=["Data Analyst"]),
            initial_state=AgentState(search_plan=SearchPlan(keywords=["jobs"])),
        )


def test_agent_service_pauses_after_action_and_resumes_without_repeating_search(temp_db_path) -> None:
    executor = ToolExecutor([MockWebSearchTool()])
    service = AgentService(
        executor=executor,
        limits=AgentLimits(max_rounds=1),
        checkpoint_path=temp_db_path.with_name("agent-checkpoints.db"),
    )

    paused = service.run(
        UserProfile(target_roles=["Data Analyst"]),
        initial_state=AgentState(search_plan=SearchPlan(keywords=["jobs"])),
        run_id="pause-and-resume",
        pause_after_action=True,
    )

    assert paused.interrupted is True
    assert paused.state.round_index == 0
    assert [event.tool_name for event in executor.events] == ["web_search"]
    assert service.state_history("pause-and-resume")

    resumed = service.resume("pause-and-resume")

    assert resumed.state.stop_reason == "max_rounds"
    assert resumed.state.round_index == 1
    assert resumed.state.round_end_reason == "no_progress"
    assert [entry.selected_action for entry in resumed.decision_trace] == [
        "web_search", "acquire_page", "stop",
    ]
    assert [event.tool_name for event in executor.events].count("web_search") == 1


def test_graph_persists_final_jobs_and_keeps_checkpoint_db_separate(temp_db_path) -> None:
    jobs_path = temp_db_path
    checkpoint_path = temp_db_path.with_name("agent-checkpoints.db")

    service = AgentService(
        executor=ToolExecutor([]),
        limits=AgentLimits(max_rounds=1),
        checkpoint_path=checkpoint_path,
        persistence_service=JobPersistenceService(jobs_path),
    )
    state = AgentState(
        round_index=1,
        prepared_jobs=[make_job()],
        understood_job_keys=[make_job().deduplication_key],
        match_assessments=[{
            "deduplication_key": make_job().deduplication_key,
            "assessment": {"match_score": 91, "match_reasons": ["Python"]},
        }],
    )

    paused = service.run(UserProfile(target_roles=["Data Analyst"]), initial_state=state,
                         run_id="persist-on-resume", pause_after_action=True)
    assert paused.interrupted is True
    assert JobPersistenceService(jobs_path).repository.count_jobs() == 0

    resumed = service.resume("persist-on-resume")
    assert not hasattr(resumed.state.prepared_jobs[0], "match_score")  # match output is a separate artifact
    assert JobPersistenceService(jobs_path).repository.count_jobs() == 1

    # A second graph execution with the same final state is an update, not a duplicate.
    service.run(UserProfile(target_roles=["Data Analyst"]), initial_state=state, run_id="persist-again")
    assert JobPersistenceService(jobs_path).repository.count_jobs() == 1

    del service
    gc.collect()
    connection = sqlite3.connect(checkpoint_path)
    try:
        checkpoint_tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        connection.close()
    connection = sqlite3.connect(jobs_path)
    try:
        job_tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        connection.close()
    assert "jobs" not in checkpoint_tables
    assert "jobs" in job_tables
    assert "checkpoints" in checkpoint_tables
