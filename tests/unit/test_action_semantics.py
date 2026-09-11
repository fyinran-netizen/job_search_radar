from job_radar.agent.action_names import AGENT_ACTION_NAMES
from job_radar.agent.action_semantics import (
    ACTION_SEMANTICS,
    get_available_action_semantics,
)
from job_radar.agent.controllers import DecisionContext, LLMController
from job_radar.agent.controllers.llm_controller.observation.builder import build_observation
from job_radar.agent.controllers.llm_controller.prompt import build_controller_prompt
from job_radar.agent.models import AgentLimits, AgentState
from tests.doubles.mock_ai_provider import MockAIProvider


def test_action_semantics_cover_canonical_vocabulary() -> None:
    assert tuple(ACTION_SEMANTICS) == AGENT_ACTION_NAMES
    assert set(next(iter(ACTION_SEMANTICS.values())).model_dump()) == {
        "purpose",
        "consumes",
        "produces",
        "progress_signal",
    }


def test_available_action_semantics_are_scoped_and_ordered() -> None:
    available = ["match_analysis", "stop"]

    semantics = get_available_action_semantics(available)

    assert list(semantics) == available
    assert set(semantics) == set(available)
    assert "job_understanding" not in semantics


def test_controller_prompt_includes_last_and_available_action_semantics() -> None:
    context = DecisionContext(
        state=AgentState(),
        limits=AgentLimits(),
        available_actions=["stop"],
        last_action="web_search",
    )
    observation = build_observation(context)
    provider = MockAIProvider({
        "action": "stop",
        "rationale": "No further work is available.",
        "stop_reason": "No further work is available.",
    })

    LLMController(provider).decide(context)

    prompt = provider.prompts[-1]
    assert '"web_search"' in prompt
    assert '"stop"' in prompt
    assert "Action semantics:" in build_controller_prompt(observation, context.available_actions)
