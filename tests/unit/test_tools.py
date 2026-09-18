import json

import pytest
from pydantic import TypeAdapter, ValidationError

from tests.doubles.mock_ai_provider import MockAIProvider
from job_radar.infra.llm.ollama import OllamaProvider
from job_radar.infra.llm.structured_output import StructuredOutputError, parse_json_output, validate_model
from job_radar.tools.job_extraction.extraction import (
    AIJobExtractionClient,
    AIPageInput,
    build_ai_page_input,
    extract_important_links,
)
from job_radar.tools.job_extraction.models import ImportantLink
from job_radar.tools.page_analysis.semantic_classification import PageSemanticClassifier
from job_radar.tools.job_understanding.analyzer import JobUnderstandingAnalyzer
from job_radar.tools.match_analysis.analyzer import SemanticMatchAnalyzer
from job_radar.tools.search_plan import SearchPlanBuilder, SearchPlanLimits
from job_radar.tools.search_plan import BuildSearchPlanTool, SearchPlanToolInput
from job_radar.tools.web_search.source_selection import normalize_url, select_sources
from job_radar.config import load_matching_rules, load_profile
from job_radar.tools.job_extraction.models import BasicGateResult, RawJobRecord
from job_radar.tools.web_search.models import CandidateSource, SearchPlan
from job_radar.tools.web_search.providers.tavily import TavilyWebSearchTool
from job_radar.tools.web_search.config import load_candidate_sources
from job_radar.profile.models import UserProfile
from job_radar.tools.page_acquisition.models import PageDocument
from job_radar.tools.page_analysis.cleaning import clean_page_text
from job_radar.tools.page_analysis.triage import triage_pages
from job_radar.tools.job_extraction.quality import triage_extracted_page
from job_radar.tools.job_extraction.backend_gate.gate import evaluate_basic_gate
from job_radar.tools.match_analysis.deterministic import evaluate_deterministic_match
from job_radar.tools.job_extraction.normalization import normalize_records
from job_radar.profile.completeness import ProfileCompletenessChecker
from job_radar.infra.paths import CONFIG_DIR


def make_prepared_job(**overrides):
    data = {
        "company_name": "Example Bank",
        "company_type": "Bank",
        "title": "Information Technology Graduate",
        "location": "Sydney",
        "description": "Build internal digital banking systems and data services.",
        "requirements": "Python SQL backend development 2026 graduates",
        "graduation_years": ["2026"],
        "source_name": "Example Bank Careers",
        "source_url": "https://careers.example/job/1",
        "is_official": True,
    }
    data.update(overrides)
    return normalize_records([RawJobRecord(**data)])[0]


def test_profile_checker_reports_incomplete_profile() -> None:
    result = ProfileCompletenessChecker().check(UserProfile())

    assert not result.is_complete
    assert "target_roles" in result.missing_fields
    assert result.questions


def test_profile_checker_requires_preferred_locations_but_allows_optional_preferences() -> None:
    profile = UserProfile(
        graduation_date="2026",
        target_roles=["Data Analyst"],
        skills=["Python"],
        preferred_locations=["Shanghai"],
    )

    result = ProfileCompletenessChecker().check(profile)

    assert result.is_complete
    assert result.missing_fields == []


def test_profile_checker_requires_graduation_year() -> None:
    profile = UserProfile(
        graduation_date="next winter",
        target_roles=["Data Analyst"],
        skills=["Python"],
        preferred_locations=["Shanghai"],
    )

    result = ProfileCompletenessChecker().check(profile)

    assert not result.is_complete
    assert result.missing_fields == ["graduation_date"]


def test_search_plan_builder_generates_role_led_queries() -> None:
    profile = UserProfile(
        graduation_date="2026-06",
        target_roles=["Data Analyst"],
        skills=["Python"],
        preferred_locations=["Shanghai"],
        excluded_locations=["Beijing"],
        preferred_company_types=["Bank"],
    )

    plan = SearchPlanBuilder().build(profile)

    assert plan.cohort_year == 2026
    assert plan.graduation_start == "2025-09"
    assert plan.graduation_end == "2026-06"
    assert "2026届" in plan.cohort_terms
    assert plan.queries
    assert all("Data Analyst" in query for query in plan.queries)
    assert all(token in plan.queries[0] for token in ("Shanghai", "Bank"))
    assert all("Beijing" not in query for query in plan.queries)


def test_search_plan_builder_maps_september_to_next_cohort() -> None:
    profile = UserProfile(
        graduation_date="2026-09",
        target_roles=["Software Engineer"],
        skills=["Python"],
        preferred_locations=["Shanghai"],
        preferred_company_types=["Bank"],
    )

    plan = SearchPlanBuilder().build(profile)

    assert plan.cohort_year == 2027
    assert plan.graduation_start == "2026-09"
    assert plan.graduation_end == "2027-06"
    assert "2027届" in plan.cohort_terms
    assert "Software Engineer" in plan.queries[0]


@pytest.mark.parametrize(
    ("graduation_date", "cohort_year"),
    [("2026-01", 2026), ("2026-08", 2026), ("2026-09", 2027), ("2026-12", 2027)],
)
def test_cohort_month_boundaries(graduation_date: str, cohort_year: int) -> None:
    from job_radar.profile.cohort import infer_graduation_cohort

    cohort = infer_graduation_cohort(graduation_date)

    assert cohort is not None
    assert cohort.cohort_year == cohort_year
    assert cohort.label == f"{cohort_year}届"
    assert cohort.graduation_window == (f"{cohort_year - 1}-09", f"{cohort_year}-06")


def test_user_profile_cleans_form_values_and_deduplicates() -> None:
    profile = UserProfile.from_form_data(
        {
            "graduation_date": " 2026-12 ",
            "target_roles": [" Data  Analyst ", "data analyst", ""],
            "skills": " Python ; SQL\npython ",
            "preferred_locations": [" Shanghai ", "shanghai", None],
            "excluded_locations": " Beijing ; ; ",
        }
    )

    assert profile.graduation_date == "2026-12"
    assert profile.target_roles == ["Data Analyst"]
    assert profile.skills == ["Python", "SQL"]
    assert profile.preferred_locations == ["Shanghai"]
    assert profile.excluded_locations == ["Beijing"]


def test_user_profile_rejects_conflicting_locations() -> None:
    with pytest.raises(ValidationError, match="cannot overlap"):
        UserProfile(
            graduation_date="2026-06",
            target_roles=["Data Analyst"],
            skills=["Python"],
            preferred_locations=[" Shanghai "],
            excluded_locations=["shanghai"],
        )


def test_search_plan_tool_generates_distinct_role_led_round_queries() -> None:
    profile = UserProfile(
        graduation_date="2026-06", target_roles=["Data Analyst"],
        preferred_locations=["Sydney"], preferred_company_types=["Bank"],
    )
    tool = BuildSearchPlanTool()
    first = tool.run(SearchPlanToolInput(profile=profile, round_index=0))
    second = tool.run(SearchPlanToolInput(profile=profile, round_index=1, previous_queries=first.queries))
    assert first.queries and second.queries
    assert set(first.queries).isdisjoint(second.queries)
    assert all("Data Analyst" in query and "Sydney" in query and "Bank" in query for query in first.queries)


def test_search_plan_builder_emits_one_query_per_role_up_to_limit() -> None:
    profile = UserProfile(
        graduation_date="2026-06",
        target_roles=["Data Analyst", "Software Engineer", "Product Analyst"],
    )

    plan = SearchPlanBuilder().build(profile, limits=SearchPlanLimits(max_queries=2))

    assert len(plan.queries) == 2
    assert all(any(role in query for role in profile.target_roles) for query in plan.queries)


def test_source_selection_keeps_low_score_aggregate_and_preserves_metadata() -> None:
    source = CandidateSource(
        url="https://example.org/careers?utm_source=test",
        title="All opportunities",
        source_name="Example",
        relevance_score=1,
        is_official=False,
    )

    selected = select_sources([source], min_relevance_score=99)

    assert selected == [source.model_copy(update={"url": "https://example.org/careers"})]


@pytest.mark.parametrize(
    ("query_count", "max_sources", "expected_quotas"),
    [(1, 10, [10]), (2, 10, [5, 5]), (3, 10, [4, 3, 3]), (4, 3, [1, 1, 1, 0])],
)
def test_tavily_allocates_dynamic_query_quotas(query_count, max_sources, expected_quotas) -> None:
    tool = TavilyWebSearchTool(max_sources=max_sources)

    assert tool._query_quotas(query_count) == expected_quotas


def test_tavily_executes_all_queries_within_budget_and_deduplicates(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "mock-key")
    calls = []

    def fake_search(_api_key, query, max_results):
        calls.append((query, max_results))
        return [
            {"url": f"https://example.org/{query}", "title": query, "score": 0.5},
            {"url": "https://example.org/shared?utm_source=test", "title": "Shared", "score": 0.4},
        ]

    tool = TavilyWebSearchTool(max_sources=6)
    monkeypatch.setattr(tool, "_search", fake_search)
    plan = SearchPlan(queries=["one", "two", "three"])

    sources = tool.run(plan)

    assert [query for query, _quota in calls] == plan.queries
    assert [quota for _query, quota in calls] == [2, 2, 2]
    assert len(sources) <= 6
    assert len({normalize_url(source.url) for source in sources}) == len(sources)


def test_source_selection_normalizes_and_deduplicates_urls_across_rounds() -> None:
    source = CandidateSource(
        url="https://Careers.Example/job/1/?utm_source=test#top", title="Role",
        source_name="Example", is_official=True, relevance_score=90,
    )
    assert normalize_url(source.url) == "https://careers.example/job/1"
    assert select_sources([source], previous_urls={"https://careers.example/job/1"}) == []


def test_ollama_provider_parses_message_content_json(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"message":{"content":"[{\\"company_name\\":\\"Example\\"}]"}}'

    def fake_urlopen(request, timeout=180):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("job_radar.infra.llm.ollama.urlopen", fake_urlopen)

    data = OllamaProvider(model="qwen3.5:cloud").generate_json("extract", timeout_seconds=12)

    assert data == [{"company_name": "Example"}]
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["body"]["model"] == "qwen3.5:cloud"
    assert captured["body"]["format"] == "json"
    assert captured["body"]["stream"] is False
    assert captured["body"]["think"] is False
    assert captured["timeout"] == 12

    OllamaProvider(model="gpt-oss:20b-cloud").generate_json("extract")

    assert captured["body"]["think"] == "low"


def test_ollama_provider_sends_system_and_user_messages(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"message":{"content":"{\\"ok\\":true}"}}'

    def fake_urlopen(request, timeout=180):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("job_radar.infra.llm.ollama.urlopen", fake_urlopen)

    data = OllamaProvider().generate_json("user prompt", system_prompt="system prompt")

    assert data == {"ok": True}
    assert captured["body"]["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]


def test_deterministic_match_bypasses_ai_for_graduation_year_mismatch() -> None:
    job = make_prepared_job(graduation_years=["2027"], graduation_requirement="2027 graduates only")
    profile = UserProfile(
        graduation_date="2026-06",
        target_roles=["Software Engineer"],
        skills=["Python"],
    )

    result = evaluate_deterministic_match(job, profile)
    analyzer = SemanticMatchAnalyzer(MockAIProvider({"should_not": "be called"}))
    assessment = analyzer.analyze(job, profile)

    assert not result.should_call_ai
    assert result.hard_reject
    assert assessment.analysis_source == "deterministic"
    assert assessment.recommendation == "skip"
    assert assessment.match_score == 0
    assert "graduation_year_mismatch" in assessment.risk_flags


def test_deterministic_match_treats_september_as_next_cohort() -> None:
    job = make_prepared_job(graduation_years=["2027"])
    profile = UserProfile(
        graduation_date="2026-09",
        target_roles=["Software Engineer"],
        skills=["Python"],
    )

    result = evaluate_deterministic_match(job, profile)

    assert result.should_call_ai
    assert not result.hard_reject
    assert "graduation_year_mismatch" not in result.risk_flags


def test_basic_gate_uses_clear_pre_understanding_names() -> None:
    job = make_prepared_job(graduation_years=["2027"], graduation_requirement="2027 graduates only")
    profile = UserProfile(
        graduation_date="2026-06",
        target_roles=["Policy Analyst"],
        skills=["policy writing"],
    )

    result = evaluate_basic_gate(job, profile)

    assert result.decision == "skip"
    assert not result.should_continue
    assert result.gate_reasons == ["Graduation year eligibility does not match."]
    assert "graduation_year_mismatch" in result.risk_flags


def test_basic_gate_keeps_ambiguous_graduation_year_mismatch_for_understanding() -> None:
    job = make_prepared_job(
        title="Software Dev Engineer Intern 2026 Shanghai",
        requirements="Build services with Java and distributed systems.",
        graduation_years=["2026"],
        graduation_requirement=None,
    )
    profile = UserProfile(
        graduation_date="2027-06",
        target_roles=["Software Engineer"],
        skills=["Python"],
    )

    result = evaluate_basic_gate(job, profile)

    assert result.should_continue
    assert not result.hard_reject
    assert any(flag.startswith("ambiguous_graduation_year_mismatch") for flag in result.risk_flags)


def test_basic_gate_rejects_explicit_graduation_window_mismatch() -> None:
    job = make_prepared_job(
        graduation_years=[],
        graduation_start="2025-09",
        graduation_end="2026-08",
        graduation_requirement="Candidates must graduate between 2025-09 and 2026-08.",
    )
    profile = UserProfile(
        graduation_date="2027-06",
        target_roles=["Software Engineer"],
        skills=["Python"],
    )

    result = evaluate_basic_gate(job, profile)

    assert result.decision == "skip"
    assert result.hard_reject
    assert "graduation_window_mismatch" in result.risk_flags


def test_basic_gate_continues_with_missing_location_and_education() -> None:
    job = make_prepared_job(locations=[], education_levels=[])
    profile = UserProfile(graduation_date="2026-06", education="bachelor")

    result = evaluate_basic_gate(job, profile)

    assert result.should_continue
    assert not result.hard_reject
    assert "location_unknown" in result.risk_flags
    assert "education_requirement_unknown" in result.risk_flags


def test_basic_gate_rejects_explicit_education_mismatch() -> None:
    job = make_prepared_job(education_levels=["master"])
    profile = UserProfile(graduation_date="2026-06", education="bachelor")

    result = evaluate_basic_gate(job, profile)

    assert result.hard_reject
    assert "education_level_mismatch" in result.risk_flags


def test_basic_gate_rejects_fully_excluded_locations() -> None:
    job = make_prepared_job(locations=["Sydney"])
    profile = UserProfile(graduation_date="2026-06", excluded_locations=["Sydney"])

    result = evaluate_basic_gate(job, profile)

    assert result.hard_reject
    assert "excluded_location" in result.risk_flags


def test_job_understanding_analyzer_returns_discipline_neutral_facts() -> None:
    job = make_prepared_job(
        title="Policy Graduate",
        description="Prepare policy briefs and consult stakeholders on public programs.",
        requirements="Strong written communication, research judgment, and 2026 graduates.",
    )
    provider = MockAIProvider(
        {
            "canonical_role": "Policy Graduate",
            "role_family": "policy",
            "seniority": "graduate",
            "responsibilities": ["Prepare policy briefs.", "Consult stakeholders."],
            "requirements": [
                {
                    "category": "communication",
                    "text": "Strong written communication.",
                    "evidence": "Strong written communication",
                },
                {
                    "category": "other",
                    "text": "Open to 2026 graduates.",
                    "evidence": "2026 graduates",
                }
            ],
            "work_context": ["Public programs."],
            "risk_flags": [],
            "confidence": "high",
        }
    )

    record = JobUnderstandingAnalyzer(provider).understand(job)

    assert record.source == "ai"
    assert not hasattr(record, "job")
    assert not hasattr(record, "company_name")
    assert not hasattr(record, "title")
    assert record.basic_gate.decision == "continue"
    assert record.understanding is not None
    assert record.understanding.requirements[0].category == "communication"
    assert "technical_skill" not in provider.prompts[1]
    assert "candidate_profile_context" not in provider.prompts[1]
    assert "program_basic_gate" not in provider.prompts[1]


def test_job_understanding_does_not_execute_or_bypass_basic_gate() -> None:
    job = make_prepared_job().model_copy(
        update={"basic_gate": BasicGateResult(decision="skip", hard_reject=True)},
    )
    provider = MockAIProvider({})

    with pytest.raises(ValueError, match="did not pass Basic Gate"):
        JobUnderstandingAnalyzer(provider).understand(job)

    assert provider.prompts == []


def test_semantic_match_analyzer_merges_deterministic_risks() -> None:
    job = make_prepared_job(is_official=False)
    profile = UserProfile(
        graduation_date="2026-06",
        target_roles=["Software Engineer"],
        skills=["Python", "SQL"],
    )
    provider = MockAIProvider(
        {
            "match_score": 96,
            "role_fit": "high",
            "must_have_fit": "yes",
            "match_reasons": ["Role involves backend systems relevant to the candidate."],
            "missing_requirements": ["Cloud stack is not specified."],
            "risk_flags": ["vague_tech_stack"],
            "job_summary": "Information technology graduate role building internal banking systems.",
            "recommendation": "apply",
            "confidence": "high",
        }
    )

    assessment = SemanticMatchAnalyzer(provider).analyze(job, profile)

    assert assessment.analysis_source == "ai_with_deterministic_overrides"
    assert assessment.match_score == 96
    assert assessment.recommendation == "apply"
    assert assessment.confidence == "medium"
    assert assessment.risk_flags == ["deadline_unknown", "education_requirement_unknown", "location_unknown", "vague_tech_stack"]
    assert provider.prompts
    assert "You are Job Radar's semantic match analysis component." in provider.prompts[0]
    assert '"candidate_profile"' in provider.prompts[1]
    assert "fixed scoring rubric" in provider.prompts[0].lower()


def test_parse_json_output_repairs_only_trailing_container_closures() -> None:
    dell_output = (
        '{"page_id":"page-1","page_context":{},"jobs":['
        '{"title":"Data analyst","requirements":"Excel"}}'
    )
    parsed = parse_json_output(dell_output)
    assert parsed["jobs"][0]["title"] == "Data analyst"

    with pytest.raises(StructuredOutputError):
        parse_json_output('{"jobs":[{"title": invalid}]}')
    with pytest.raises(StructuredOutputError):
        parse_json_output('{"jobs":[{"title":"unterminated}]}')


def test_load_candidate_sources_reads_enabled_manual_source() -> None:
    sources, used_example, _path = load_candidate_sources(CONFIG_DIR)
    assert used_example
    assert sources
    assert sources[0].url == "https://kedacom.zhiye.com/zpdetail/511158941"
    assert sources[0].company_name == "苏州科达科技股份有限公司"


def test_page_filter_accepts_job_like_page() -> None:
    page = PageDocument(
        url="https://careers.example/job/123",
        source_name="Example Careers",
        title="Data Analyst Graduate 2026",
        text=(
            "Graduate Program responsibilities requirements qualifications location apply "
            "Python SQL data analysis role for early careers candidates. "
            "This page contains enough job description content for extraction."
        ),
        metadata={"status_code": 200, "final_url": "https://careers.example/job/123"},
    )
    result = triage_pages([page], min_text_length=80)
    assert result.readable_pages == [page]
    assert result.rejected_pages == []




def test_page_filter_rejects_obvious_non_job_page() -> None:
    page = PageDocument(
        url="https://careers.example/login",
        source_name="Example Careers",
        title="Login",
        text="Please login or sign in to continue.",
        metadata={"status_code": 200, "final_url": "https://careers.example/login"},
    )

    result = triage_pages([page], min_text_length=80)

    assert result.readable_pages == []
    assert result.rejected_pages[0].url == "https://careers.example/login"
    assert any("auth_wall" in reason for reason in result.rejected_pages[0].reasons)


def test_page_filter_does_not_reject_job_page_for_nav_login_words() -> None:
    page = PageDocument(
        url="https://www.boc.cn/aboutboc/bi4/202603/t20260311_25654053.html",
        source_name="Bank of China",
        title="Bank of China 2026 Spring Recruitment Notice",
        text=(
            "閻ц缍?濞夈劌鍞?娑擃厼娴楅柧鎯邦攽閼测€插敜閺堝妾洪崗顒€寰?026楠炲瓨妲€涳絾瀚戦懕妯哄彆閸?"
            "閹锋稖浠掗崗顒€鎲?閺嶁€虫疮閹锋稖浠?瀹搞儰缍旈崷鎵仯 娴犳槒浜寸憰浣圭湴 瀹€妞剧秴閼卞矁鐭?閺佺増宓侀崚鍡樼€?缁夋垶濡у畝?"
            "This page contains detailed campus recruitment information for 2026 graduates."
        ),
        metadata={"status_code": 200, "final_url": "https://www.boc.cn/aboutboc/bi4/202603/t20260311_25654053.html"},
    )

    result = triage_pages([page], min_text_length=80)

    assert result.readable_pages == [page]
    assert result.rejected_pages == []


def test_page_filter_keeps_redirected_detail_to_listing_page() -> None:
    page = PageDocument(
        url="https://group.bnpparibas/en/careers/job-offer/bnp-paribas-sydney-2026-graduate-programme",
        source_name="BNP Paribas Careers",
        title="Job offers for the job function Finance accounts and management control - BNP Paribas",
        text=(
            "Graduate programme qualifications location apply 2026 Sydney Bank Technology "
            "This is a long listing page with navigation and many generic career links."
        ),
        metadata={
            "status_code": 200,
            "final_url": "https://group.bnpparibas/en/careers/all-job-offers/finance-accounts-and-management-control",
        },
    )
    plan = SearchPlan(
        target_roles=["Graduate Program"],
        locations=["Sydney"],
        company_types=["Bank"],
        keywords=["BNP Paribas Sydney 2026 Graduate Programme"],
    )

    result = triage_pages([page], search_plan=plan, min_text_length=80)

    assert result.readable_pages == [page]
    assert result.rejected_pages == []


def test_page_filter_marks_short_collectable_page_pending() -> None:
    page = PageDocument(
        url="https://job.xiaohongshu.com/campus/position/17071",
        source_name="Xiaohongshu Campus Careers",
        title="Xiaohongshu",
        text="Short page",
        metadata={"status_code": 200, "final_url": "https://job.xiaohongshu.com/campus/position/17071"},
    )

    result = triage_pages([page], min_text_length=300)

    assert result.readable_pages == []
    assert result.recoverable_pages[0].url == page.url
    assert result.rejected_pages == []


def test_page_filter_rejects_redirected_error_page() -> None:
    page = PageDocument(
        url="https://job-boards.greenhouse.io/letsgetchecked/jobs/4833407101",
        source_name="LetsGetChecked Greenhouse",
        title="Jobs at LetsGetChecked",
        text="Jobs at LetsGetChecked. Search openings.",
        metadata={
            "status_code": 200,
            "final_url": "https://job-boards.greenhouse.io/letsgetchecked?error=true",
        },
    )

    result = triage_pages([page], min_text_length=30)

    assert result.readable_pages == []
    assert any("redirected_to_error_page" in reason for reason in result.rejected_pages[0].reasons)


def test_page_semantic_classifier_routes_apply_portal() -> None:
    page = AIPageInput(
        url="https://careers.example/campus/",
        source_name="Example Careers",
        source_company_name="Example",
        company_type="Technology",
        is_official=True,
        title="Example Campus Careers",
        visible_text="Explore graduate programs, search jobs, and apply online.",
    )
    provider = MockAIProvider(
        {
            "page_type": "apply_portal",
            "suggested_next_action": "open_portal_and_find_job_detail_pages",
            "reasons": ["The page is centered on search and apply actions."],
            "evidence": ["search jobs", "apply online"],
            "confidence": "high",
        }
    )

    classification = PageSemanticClassifier(provider).classify(page)

    assert classification.page_type == "apply_portal"
    assert not classification.is_job_detail_page
    assert classification.suggested_next_action == "open_portal_and_find_job_detail_pages"
    assert "allowed_page_types" in provider.prompts[0]


def test_extraction_triage_marks_role_list_without_jd_pending() -> None:
    page_input = AIPageInput(
        url="https://career.example/list",
        source_name="Example Careers",
        source_company_name="Example Robotics",
        company_type="Technology",
        is_official=False,
        title="2027 campus recruitment role list",
        visible_text="Role list",
    )
    records = [
        RawJobRecord(
            company_name="Example Robotics",
            title=f"缁犳纭跺銉р柤鐢?{index}",
            graduation_years=["2027"],
            apply_url="https://career.example/apply",
            source_url="https://career.example/list",
            source_name="Example Careers",
        )
        for index in range(12)
    ]

    pending = triage_extracted_page(page_input, records)

    assert pending is not None
    assert pending.pending_kind == "role_list_without_jd"
    assert pending.suggested_next_action == "find_detail_pages_for_role_titles"
    assert pending.evidence["extracted_job_count"] == 12
    assert len(pending.role_titles) == 12


def test_extraction_triage_marks_small_sparse_role_list_pending() -> None:
    page_input = AIPageInput(
        url="https://career.example/notice",
        source_name="Example Careers",
        source_company_name="Example Robotics",
        company_type="Technology",
        is_official=False,
        title="2027 campus recruitment notice",
        visible_text="Software roles apply through the campus portal.",
    )
    records = [
        RawJobRecord(
            company_name="Example Robotics",
            title="Motion Control Algorithm Engineer",
            graduation_years=["2027"],
            apply_url="https://career.example/campus",
            source_url="https://career.example/notice",
            source_name="Example Careers",
        ),
        RawJobRecord(
            company_name="Example Robotics",
            title="Agent Developer",
            graduation_years=["2027"],
            apply_url="https://career.example/campus",
            source_url="https://career.example/notice",
            source_name="Example Careers",
        ),
    ]

    pending = triage_extracted_page(page_input, records)

    assert pending is not None
    assert pending.pending_kind == "role_list_without_jd"
    assert pending.evidence["sparse_record_ratio"] == 1.0
    assert pending.role_titles == ["Motion Control Algorithm Engineer", "Agent Developer"]


def test_extraction_triage_allows_standard_jd_without_employer_name() -> None:
    page_input = AIPageInput(
        url="https://randstad.example/job/1",
        source_name="Randstad",
        title="Software Engineer",
        visible_text="Our client is seeking a Software Engineer.",
    )
    pending = triage_extracted_page(
        page_input,
        [
            RawJobRecord(
                title="Software Engineer",
                description="Build and maintain software services.",
                requirements="Python and distributed systems experience.",
                location="Sydney",
                source_url=page_input.url,
                source_name="Randstad",
            )
        ],
    )

    assert pending is None


def test_build_ai_page_input_preserves_provenance_but_drops_search_scoring() -> None:
    page = PageDocument(
        url="https://careers.example/job/123",
        source_name="Example Careers",
        title="Data Analyst Graduate",
        text=" line one \n\n line two \n line three ",
        metadata={
            "final_url": "https://careers.example/job/123",
            "company_name": "Example",
            "company_type": "Technology",
            "is_official": True,
            "relevance_score": 95,
            "reason": "Search result explanation.",
            "links": [
                {"href": "https://careers.example/apply", "text": "Apply"},
                {"href": "https://careers.example/about", "text": "About us"},
            ],
        },
    )

    ai_input = build_ai_page_input(page, max_text_chars=17)
    payload = ai_input.model_dump()

    assert payload == {
        "url": "https://careers.example/job/123",
        "final_url": "https://careers.example/job/123",
        "source_name": "Example Careers",
        "source_company_name": "Example",
        "company_type": "Technology",
        "source_location": None,
        "is_official": True,
        "title": "Data Analyst Graduate",
        "visible_text": "line one\nline two",
        "important_links": [
            {
                "url": "https://careers.example/apply",
                "text": "Apply",
                "kind": "apply",
                "reason": "apply_signal",
            }
        ],
    }


def test_extract_important_links_keeps_attachments_and_apply_links() -> None:
    page = PageDocument(
        url="https://www.boc.cn/aboutboc/bi4/202603/t20260311_25654053.html",
        source_name="Bank of China",
        title="Bank of China 2026 Spring Recruitment Notice",
        text="Recruitment notice",
        metadata={
            "links": [
                {
                    "href": "https://pic.bankofchina.com/bocappd/appform/202603/P020260311360231598031.pdf",
                    "text": "Attachment",
                },
                {"href": "https://careers.example/apply", "text": "Apply now"},
                {"href": "https://careers.example/about", "text": "About"},
            ]
        },
    )

    links = extract_important_links(page)

    assert [link.kind for link in links] == ["apply", "attachment"]
    assert links[1].url.endswith(".pdf")


def test_extract_important_links_uses_visible_apply_url_and_rejects_misleading_path() -> None:
    page = PageDocument(
        url="https://www.boc.cn/recruitment",
        source_name="Bank of China",
        title="Spring recruitment",
        text=(
            "閺勩儱顒滈幏娑滀粧缂冩垹鐝稉鐚寸窗\n"
            "https://campus.chinahr.com/pages/boc-2026-Spring\n"
            "Apply online"
        ),
        metadata={
            "links": [
                {
                    "href": "https://university.example/applyguide/index.html",
                    "text": "濞茶濮╂０鍕啞",
                }
            ]
        },
    )

    links = extract_important_links(page)

    assert [(link.kind, link.url) for link in links] == [
        ("apply", "https://campus.chinahr.com/pages/boc-2026-Spring")
    ]


def test_important_link_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        ImportantLink(url="https://careers.example/file.pdf", kind="download")


def test_clean_page_text_prefers_trafilatura_html() -> None:
    cleaned = clean_page_text(
        """
        <html>
          <body>
            <nav>Home Login Contact</nav>
            <main>
              <h1>Data Analyst Graduate 2026</h1>
              <p>Responsibilities include SQL dashboards and product metrics.</p>
              <p>Requirements include Python, SQL, and statistics.</p>
            </main>
          </body>
        </html>
        """,
        fallback_text="Home\nLogin\nBad fallback text",
        url="https://careers.example/job/123",
        min_extracted_chars=40,
    )

    assert cleaned.method == "trafilatura"
    assert "Responsibilities include SQL dashboards" in cleaned.text
    assert "Bad fallback text" not in cleaned.text


def test_extract_important_links_keeps_conservative_job_detail_candidates() -> None:
    page = PageDocument(
        url="https://careers.example/jobs",
        source_name="Example Careers",
        text="Several roles are listed below.",
        metadata={
            "links": [
                {"href": "/jobs/data-analyst-123", "text": "Data Analyst"},
                {"href": "/about", "text": "About us"},
                {"href": "/apply", "text": "Apply"},
            ]
        },
    )

    links = extract_important_links(page)

    assert [(link.kind, link.url) for link in links] == [
        ("apply", "https://careers.example/apply"),
        ("job_detail_candidate", "https://careers.example/jobs/data-analyst-123"),
    ]


def test_semantic_classifier_normalizes_action_to_page_type() -> None:
    provider = MockAIProvider(
        {
            "page_type": "job_listing",
            "suggested_next_action": "extract_jobs",
            "reasons": ["multiple roles"],
            "evidence": ["job detail links"],
            "confidence": "high",
        }
    )
    classification = PageSemanticClassifier(provider).classify(
        AIPageInput(
            url="https://careers.example/jobs",
            title="Jobs",
            visible_text="Data Analyst\nSoftware Engineer",
        )
    )

    assert classification.suggested_next_action == "fetch_detail_links"
    assert "job_listing" in provider.prompts[0]
    assert "Never fetch" in provider.prompts[0]


def test_ai_job_extraction_client_prompts_with_minimal_page_input() -> None:
    page = PageDocument(
        url="https://careers.example/job/123",
        source_name="Example Careers",
        title="Data Analyst Graduate",
        text="Data Analyst Graduate responsibilities requirements location apply.",
        metadata={
            "final_url": "https://careers.example/job/123",
            "company_name": "Example",
            "company_type": "Technology",
            "is_official": True,
            "relevance_score": 95,
            "reason": "Search result explanation.",
        },
    )
    provider = MockAIProvider(
        {
            "page_id": "page-1",
            "page_context": {
                "company_name": "Example",
                "recruitment_type": "Graduate Program",
                "graduation_years": [2026],
                "source_url": "https://hallucinated.example/job",
                "apply_url": "https://hallucinated.example/file.pdf",
                "is_official": False,
            },
            "jobs": [
                {
                    "title": "Data Analyst Graduate",
                    "location": "Sydney",
                },
                {
                    "title": "Software Engineer Graduate",
                    "location": "Melbourne",
                }
            ],
        }
    )

    records = AIJobExtractionClient(provider, max_text_chars=200).extract_jobs_from_page(page)

    assert records[0].title == "Data Analyst Graduate"
    assert records[1].title == "Software Engineer Graduate"
    assert all(record.company_name == "Example" for record in records)
    assert all(record.company_type == "Technology" for record in records)
    assert all(record.source_url == "https://careers.example/job/123" for record in records)
    assert all(record.source_name == "Example Careers" for record in records)
    assert all(record.is_official is True for record in records)
    assert all(record.apply_url is None for record in records)
    assert all(record.graduation_years == ["2026"] for record in records)
    assert provider.prompts
    prompt = provider.prompts[0]
    input_payload = prompt.rsplit("Input:\n", maxsplit=1)[1]
    assert "visible_text" in input_payload
    assert "relevance_score" not in input_payload
    assert "Search result explanation" not in input_payload
    assert '"company_type": "Technology"' not in input_payload
    assert '"is_official": true' not in input_payload
    assert "https://careers.example/job/123" not in input_payload
    assert "important_links" not in input_payload
    assert "only the one primary job" in prompt
    assert "related, similar, recommended" in prompt
    assert "Return every explicitly named position" not in prompt


def test_ai_job_extraction_keeps_four_job_detail_pages_to_one_primary_job_each() -> None:
    provider = MockAIProvider(
        [
            {
                "page_id": f"page-{index}",
                "page_context": {"company_name": "Example"},
                "jobs": [{"title": f"Primary Role {index}", "location": "Sydney"}],
            }
            for index in range(1, 5)
        ]
    )
    pages = [
        AIPageInput(
            url=f"https://careers.example/job/{index}",
            title=f"Primary Role {index}",
            visible_text=(
                f"Primary Role {index}\n"
                "Related jobs: Other Role A, Other Role B\n"
                "Similar jobs: Other Role C\n"
                "Recommended jobs: Other Role D"
            ),
        )
        for index in range(1, 5)
    ]

    records = AIJobExtractionClient(provider).extract_jobs_from_inputs(pages)

    assert len(records) == 4
    assert [record.title for record in records] == [
        "Primary Role 1",
        "Primary Role 2",
        "Primary Role 3",
        "Primary Role 4",
    ]


@pytest.mark.parametrize(
    ("title", "visible_text", "expected"),
    [
        (
            "Software Engineer | Example Corp",
            "Software Engineer responsibilities and requirements.",
            "Example Corp",
        ),
        (
            "Software Engineer",
            "Employer: Example Corp\nSoftware Engineer responsibilities.",
            "Example Corp",
        ),
        (
            "Software Engineer",
            "公司名称：示例科技有限公司\n岗位职责：负责平台开发。",
            "示例科技有限公司",
        ),
    ],
)
def test_ai_job_extraction_company_name_uses_explicit_main_jd_text(
    title: str, visible_text: str, expected: str | None
) -> None:
    provider = MockAIProvider(
        {
            "page_id": "page-1",
            "page_context": {"company_name": None},
            "jobs": [{"title": "Software Engineer", "location": "Sydney"}],
        }
    )
    page_input = AIPageInput(
        url="https://careers.example/job/1",
        title=title,
        visible_text=visible_text,
    )

    records = AIJobExtractionClient(provider).extract_jobs_from_input(page_input)

    assert records[0].company_name == expected


def test_ai_job_extraction_company_name_falls_back_to_source_metadata() -> None:
    provider = MockAIProvider(
        {
            "page_id": "page-1",
            "page_context": {"company_name": None},
            "jobs": [{"title": "Software Engineer", "location": "Sydney"}],
        }
    )
    page_input = AIPageInput(
        url="https://randstad.example/job/1",
        source_company_name="Example Employer",
        title="Software Engineer",
        visible_text="Our client is seeking a Software Engineer.",
    )

    records = AIJobExtractionClient(provider).extract_jobs_from_input(page_input)

    assert records[0].company_name == "Example Employer"


def test_ai_job_extraction_falls_back_to_source_location_after_semantic_response() -> None:
    provider = MockAIProvider(
        {
            "page_id": "page-1",
            "page_context": {"company_name": "Example"},
            "jobs": [{"title": "Software Engineer Graduate", "location": None}],
        }
    )
    page = PageDocument(
        url="https://careers.example/job/1",
        source_name="Example Careers",
        title="Software Engineer Graduate - Shanghai",
        text="Software Engineer Graduate responsibilities and requirements.",
        metadata={
            "company_name": "Example",
            "company_type": "Technology",
            "location": "Shanghai",
            "is_official": True,
        },
    )

    records = AIJobExtractionClient(provider).extract_jobs_from_page(page)

    assert records[0].locations == ["Shanghai"]
    input_payload = provider.prompts[0].rsplit("Input:\n", maxsplit=1)[1]
    assert '"location": "Shanghai"' not in input_payload


def test_ai_job_extraction_schema_accepts_empty_jobs_for_later_program_validation() -> None:
    provider = MockAIProvider(
        {
            "page_id": "page-1",
            "page_context": {"company_name": "Example"},
            "jobs": [],
        }
    )
    page_input = AIPageInput(
        url="https://careers.example/jobs",
        title="Example careers",
        visible_text="No named positions were extracted.",
    )

    records = AIJobExtractionClient(provider).extract_jobs_from_input(page_input)

    assert records == []


def test_ai_job_extraction_accepts_single_object_for_single_input_batch() -> None:
    provider = MockAIProvider(
        {
            "page_id": "page-1",
            "page_context": {"company_name": "Example"},
            "jobs": [{"title": "Data Analyst Graduate", "location": "Sydney"}],
        }
    )
    page_input = AIPageInput(
        url="https://careers.example/job/1",
        source_name="Example Careers",
        title="Example job",
        visible_text="Data Analyst Graduate. Location Sydney.",
    )

    records = AIJobExtractionClient(provider).extract_jobs_from_inputs([page_input])

    assert len(records) == 1
    assert records[0].company_name == "Example"
    assert records[0].title == "Data Analyst Graduate"


