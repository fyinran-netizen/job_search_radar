from job_radar.agent.controllers import DecisionContext, LLMController
from job_radar.agent.controllers.llm_controller.observation.builder import build_observation
from job_radar.agent.controllers.llm_controller.outcome_summary import ActionOutcomeSummarizer
from job_radar.agent.controllers.llm_controller.outcome_summary.strategies.analyze_page import summarize as summarize_analyze_page
from job_radar.agent.controllers.llm_controller.outcome_summary.strategies.acquire_page import summarize as summarize_acquire_page
from job_radar.agent.models import AgentLimits, AgentState, SearchOutcome
from job_radar.tools.page_acquisition.models import PageDocument
from job_radar.tools.job_understanding.models import JobRequirementFacts, JobUnderstandingRecord
from job_radar.tools.job_extraction.models import BasicGateResult
from job_radar.tools.web_search.models import CandidateSource
from job_radar.tools.search_plan.models import SearchPlan
from tests.doubles.mock_ai_provider import MockAIProvider


def test_action_summary_provider_receives_action_specific_projection() -> None:
    before = AgentState()
    after = AgentState(
        candidate_sources=[CandidateSource(url="https://example.test/job", title="Data Analyst", source_name="Example")],
        search_round_results=[[CandidateSource(url="https://example.test/job", title="Data Analyst", source_name="Example")]],
        last_search_outcome=SearchOutcome.PROGRESS,
    )
    provider = MockAIProvider({"summary": "A new plausible job source expanded the discovery coverage."})

    summary = ActionOutcomeSummarizer(provider).summarize("web_search", before, after)

    assert summary.startswith("A new plausible")
    assert "Search statistics:" in provider.prompts[-1]
    assert "visible_text" not in provider.prompts[-1]


def test_build_search_plan_summary_is_deterministic_and_does_not_call_llm() -> None:
    before = AgentState(search_plan=SearchPlan(queries=["data analyst Sydney"]))
    after = AgentState(search_plan=SearchPlan(
        queries=["data analyst Sydney", "graduate analyst Melbourne"],
        target_roles=["Data Analyst", "Business Analyst"],
        locations=["Sydney", "Melbourne"],
    ))
    provider = MockAIProvider({"summary": "This response must not be used."})

    summary = ActionOutcomeSummarizer(provider).summarize("build_search_plan", before, after)

    assert "2 executable queries" in summary
    assert "target roles: Data Analyst, Business Analyst" in summary
    assert "locations: Sydney, Melbourne" in summary
    assert "new executable search direction" in summary
    assert provider.prompts == []


def test_build_search_plan_summary_marks_unchanged_queries() -> None:
    plan = SearchPlan(
        queries=["data analyst Sydney"],
        target_roles=["Data Analyst"],
        locations=["Sydney"],
    )

    summary = ActionOutcomeSummarizer().summarize(
        "build_search_plan",
        AgentState(search_plan=plan),
        AgentState(search_plan=plan),
    )

    assert "without changing the existing queries" in summary
    assert "1 executable quer" in summary


def test_web_search_summary_sends_deterministic_stats_without_urls() -> None:
    seen = CandidateSource(url="https://example.test/seen", title="Seen role", source_name="Example")
    new = CandidateSource(url="https://example.test/new", title="New role", source_name="Example")
    before = AgentState(candidate_sources=[seen])
    after = AgentState(
        candidate_sources=[seen, new],
        search_round_results=[[CandidateSource(url="https://example.test/seen/", title="Seen role", source_name="Example"), new]],
        selected_sources=[new],
    )
    provider = MockAIProvider({"summary": "The round added one novel source while retaining one previously seen result."})

    summary = ActionOutcomeSummarizer(provider).summarize("web_search", before, after)
    prompt = provider.prompts[-1]

    assert "added one novel source" in summary
    assert '"returned_sources": 2' in prompt
    assert '"new_sources": 1' in prompt
    assert '"previously_seen_sources": 1' in prompt
    assert '"selected_sources": 1' in prompt
    assert seen.url not in prompt
    assert new.url not in prompt


def test_semantic_summary_falls_back_without_unsupported_inference() -> None:
    from job_radar.tools.page_analysis.models import AIPageInput

    before = AgentState()
    after = AgentState(job_detail_pages=[AIPageInput(
        url="https://example.test/detail",
        title="Data Analyst",
        source_name="Example",
        visible_text="Job description",
    )])
    provider = MockAIProvider({"unexpected": "invalid structured output"})

    summary = summarize_analyze_page(before, after, provider, 60)

    assert "1 new job-detail page(s)" in summary
    assert "Routing evidence was classified" in summary
    assert "high-quality" not in summary
    assert "strong candidate fit" not in summary


def test_action_strategy_is_scoped_to_the_completed_action() -> None:
    source = CandidateSource(url="https://example.test/job", title="Job", source_name="Example")
    before = AgentState(selected_sources=[source])
    after = AgentState(
        selected_sources=[source],
        acquired_pages=[PageDocument(url=source.url, title="Job", source_name="Example")],
    )

    summary = summarize_acquire_page(before, after, None, 60)

    assert "acquired all" in summary


def test_analyze_page_summary_combines_counts_and_url_free_semantics() -> None:
    from job_radar.tools.page_analysis.models import AIPageInput

    before = AgentState()
    after = AgentState(job_detail_pages=[AIPageInput(
        url="https://example.test/detail",
        title="Data Analyst",
        source_name="Example",
        visible_text="ignored by projection",
        is_official=True,
    )])
    provider = MockAIProvider({"summary": "The routing produced extraction-ready job-detail evidence."})

    summary = summarize_analyze_page(before, after, provider, 60)

    assert "1 new job-detail page(s)" in summary
    assert "extraction-ready" in summary
    assert "https://example.test/detail" not in provider.prompts[-1]
    assert "Data Analyst" in provider.prompts[-1]
    assert "ignored by projection" not in provider.prompts[-1]


def test_job_understanding_summary_is_mixed_and_omits_record_identifiers_and_gate() -> None:
    record_one = JobUnderstandingRecord(
        deduplication_key="private-key-1",
        basic_gate=BasicGateResult(gate_reasons=["not sent to understanding"]),
        understanding=JobRequirementFacts(
            canonical_role="Data Analyst",
            role_family="Analytics",
            seniority="entry_level",
            responsibilities=["build reports"],
            requirements=[],
            work_context=["cross-functional"],
            risk_flags=[],
            confidence="high",
        ),
        source="ai",
    )
    record_two = record_one.model_copy(update={"deduplication_key": "private-key-2"})
    before = AgentState()
    after = AgentState(understanding_records=[record_one, record_two])
    provider = MockAIProvider({"summary": "The records show a repeated entry-level analytics pattern with high-confidence requirements."})

    summary = ActionOutcomeSummarizer(provider).summarize("job_understanding", before, after)

    assert "high concentration" in summary
    assert "private-key-1" not in provider.prompts[-1]
    assert "basic_gate" not in provider.prompts[-1]
    assert "canonical_role" in provider.prompts[-1]
    assert "role-concentration assessment as context: high" in provider.prompts[-1]


def test_match_analysis_summary_uses_deterministic_distributions_and_semantic_projection() -> None:
    before = AgentState()
    after = AgentState(match_assessments=[
        {
            "deduplication_key": "private-match-1",
            "match_score": 86,
            "role_fit": "high",
            "must_have_fit": "yes",
            "recommendation": "apply",
            "match_reasons": ["strong role alignment"],
            "missing_requirements": [],
            "risk_flags": [],
            "confidence": "high",
        },
        {
            "deduplication_key": "private-match-2",
            "match_score": 42,
            "role_fit": "low",
            "must_have_fit": "no",
            "recommendation": "skip",
            "match_reasons": [],
            "missing_requirements": ["required certification"],
            "risk_flags": ["unclear scope"],
            "confidence": "medium",
        },
    ])
    provider = MockAIProvider({"summary": "The batch separates a strong aligned opportunity from a weaker certification-gapped role."})

    summary = ActionOutcomeSummarizer(provider).summarize("match_analysis", before, after)

    assert "strong aligned opportunity" in summary
    assert "private-match-1" not in provider.prompts[-1]
    assert "recommendation_distribution" in provider.prompts[-1]
    assert "match_reasons" in provider.prompts[-1]
    assert "required certification" in provider.prompts[-1]


def test_match_analysis_fallback_unwraps_nested_assessment() -> None:
    from job_radar.agent.controllers.llm_controller.outcome_summary.strategies.match_analysis import (
        _fallback_summary,
    )

    summary = _fallback_summary([
        {
            "deduplication_key": "private-match-1",
            "assessment": {
                "recommendation": "apply",
                "role_fit": "high",
                "must_have_fit": "yes",
                "confidence": "high",
            },
        }
    ])

    assert "recommendation is apply" in summary
    assert "role fit is high" in summary
    assert "must-have fit is yes" in summary
    assert "confidence is high" in summary


def test_controller_observation_carries_last_action_summary() -> None:
    state = AgentState(last_action_summary="The page yielded a plausible job detail for extraction.")
    context = DecisionContext(
        state=state,
        limits=AgentLimits(),
        available_actions=["stop"],
        last_action="analyze_page",
    )
    provider = MockAIProvider({
        "action": "stop",
        "rationale": "No further action is needed.",
        "stop_reason": "test stop",
    })

    observation = build_observation(context)
    LLMController(provider).decide(context)

    assert observation.common.last_action == "analyze_page"
    assert observation.common.last_action_summary == state.last_action_summary
    assert state.last_action_summary in provider.prompts[-1]
