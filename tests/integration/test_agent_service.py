from job_radar.agent.controllers import RuleBasedController
from job_radar.agent.models import AgentLimits, AgentState
from job_radar.profile.models import UserProfile
from job_radar.services.agent_service import AgentService
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.web_search.providers.mock import MockWebSearchTool
from job_radar.tools.web_search.models import SearchPlan
import pytest


def test_agent_service_runs_injected_rule_controller_and_records_trace() -> None:
    service = AgentService(
        controller=RuleBasedController(),
        executor=ToolExecutor([MockWebSearchTool()]),
        limits=AgentLimits(max_rounds=1),
    )

    result = service.run(
        UserProfile(target_roles=["Data Analyst"]),
        initial_state=AgentState(
            search_plan=SearchPlan(keywords=["graduate jobs"]),
        ),
    )

    assert result.state.stop_reason == "deterministic stop condition reached"
    assert [entry.selected_action for entry in result.decision_trace] == [
        "web_search",
        "stop",
    ]
    assert result.decision_trace[0].available_actions == ["web_search"]
    assert result.decision_trace[0].state_summary["round_index"] == 0
    assert result.decision_trace[1].state_summary["round_index"] == 1


def test_agent_service_rejects_an_action_that_does_not_change_state(monkeypatch) -> None:
    class StuckController:
        def decide(self, context):
            return type("Action", (), {
                "action": "web_search",
                "rationale": "repeat",
            })()

    import job_radar.services.agent_service as agent_service_module

    monkeypatch.setattr(
        agent_service_module,
        "execute_action",
        lambda action, state, executor, limits, profile=None: state,
    )
    service = AgentService(
        controller=StuckController(),  # type: ignore[arg-type]
        executor=ToolExecutor([]),
        limits=AgentLimits(max_rounds=1),
    )

    with pytest.raises(RuntimeError, match="did not change State"):
        service.run(
            UserProfile(target_roles=["Data Analyst"]),
            initial_state=AgentState(search_plan=SearchPlan(keywords=["jobs"])),
        )
