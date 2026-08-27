import json

import pytest
from pydantic import TypeAdapter, ValidationError

from job_radar.agent.orchestrator import JobDiscoveryAgent
from job_radar.cli.clean_pages import main as clean_pages_cli_main
from job_radar.cli.classify_pages import main as classify_pages_cli_main
from job_radar.cli.collect_pages import main as collect_pages_cli_main
from job_radar.cli.analyze_matches import main as analyze_matches_cli_main
from job_radar.cli.extract_jobs import main as extract_jobs_cli_main
from job_radar.cli.group_prepared_jobs import main as group_prepared_jobs_cli_main
from job_radar.cli.understand_jobs import main as understand_jobs_cli_main
from job_radar.cli.search_strategy import main as search_strategy_cli_main
from job_radar.cli.web_search import main as web_search_cli_main
from job_radar.ai.providers.codex_cli import CodexCliDebugInfo, CodexCliProvider
from job_radar.ai.providers.mock import MockAIProvider
from job_radar.ai.providers.ollama import OllamaProvider
from job_radar.ai.structured_output import StructuredOutputError, parse_json_output, validate_model
from job_radar.ai.tasks.job_extraction import (
    AIJobExtractionClient,
    AIPageInput,
    ImportantLink,
    build_ai_page_input,
    extract_important_links,
)
from job_radar.ai.tasks.page_classification import PageSemanticClassifier
from job_radar.ai.tasks.job_understanding import JobUnderstandingAnalyzer
from job_radar.ai.tasks.match_analysis import SemanticMatchAnalyzer
from job_radar.ai.tasks.search_strategy import AISearchPlanBuilder, AutoSearchPlanBuilder, SearchPlanBuilder
from job_radar.config import load_candidate_sources, load_matching_rules, load_profile
from job_radar.extractors.llm import LLMJobExtractor, UnconfiguredLLMJobExtractor
from job_radar.extractors.rule_based import RuleBasedJobExtractor
from job_radar.models.job import RawJobRecord
from job_radar.models.search import CandidateSource, SearchPlan
from job_radar.models.profile import UserProfile
from job_radar.models.tool import PageContent
from job_radar.models.understanding import JobUnderstandingRecord
from job_radar.pipeline.page_cleaning import clean_page_text, clean_visible_text
from job_radar.pipeline.page_filter import filter_pages
from job_radar.pipeline.page_triage import triage_extracted_page
from job_radar.pipeline.basic_gate import evaluate_basic_gate
from job_radar.pipeline.deterministic_match import evaluate_deterministic_match
from job_radar.pipeline.normalization import normalize_records
from job_radar.pipeline.runner import PipelineRunner
from job_radar.profile.completeness import ProfileCompletenessChecker
from job_radar.services.ingestion_service import IngestionService
from job_radar.storage.repository import JobRepository
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.factory import create_mock_tool_executor
from job_radar.tools.functions.codex_web_search import CodexWebSearchTool
from job_radar.tools.functions.http_page import HttpPageTool
from job_radar.tools.functions.manual_sources import ManualSourceTool
from job_radar.utils.paths import CONFIG_DIR


def make_agent() -> JobDiscoveryAgent:
    return JobDiscoveryAgent(job_extractor=RuleBasedJobExtractor(), tool_executor=create_mock_tool_executor())


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


def test_profile_checker_allows_optional_preferences() -> None:
    profile = UserProfile(
        graduation_date="2026",
        target_roles=["Data Analyst"],
        skills=["Python"],
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


def test_search_plan_builder_generates_keywords() -> None:
    profile = UserProfile(
        graduation_date="2026-06",
        target_roles=["Data Analyst"],
        skills=["Python"],
        preferred_locations=["Shanghai"],
        preferred_company_types=["Bank"],
    )

    plan = SearchPlanBuilder().build(profile)

    assert plan.cohort_year == 2026
    assert plan.graduation_start == "2025-09"
    assert plan.graduation_end == "2026-06"
    assert "2026届" in plan.cohort_terms
    assert "Data Analyst 2026 graduate" in plan.keywords
    assert "2026 graduate jobs Shanghai" in plan.keywords
    assert "Bank 2026 graduate program" in plan.keywords


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
    assert "Software Engineer 2027 graduate" in plan.keywords


def test_ai_search_plan_builder_uses_skill_provider() -> None:
    profile, _, _ = load_profile(CONFIG_DIR)
    provider = MockAIProvider(
        {
            "target_roles": ["Data Analyst"],
            "locations": ["Sydney"],
            "company_types": ["Technology"],
            "keywords": ["Data Analyst graduate 2026 Sydney"],
        }
    )

    plan = AISearchPlanBuilder(provider).build(profile)

    assert plan.keywords == ["Data Analyst graduate 2026 Sydney"]
    assert provider.prompts
    assert "Search Strategy" in provider.prompts[0]


def test_auto_search_plan_builder_falls_back_when_codex_unavailable() -> None:
    class UnavailableCodexProvider:
        def is_available(self) -> bool:
            return False

        def generate_json(self, _prompt):
            raise AssertionError("Codex should not be called when unavailable")

    profile = UserProfile(
        graduation_date="2026-06",
        target_roles=["Data Analyst"],
        skills=["Python"],
        preferred_locations=["Shanghai"],
        preferred_company_types=["Bank"],
    )
    builder = AutoSearchPlanBuilder(codex_provider=UnavailableCodexProvider())  # type: ignore[arg-type]

    plan = builder.build(profile)

    assert builder.last_source == "deterministic"
    assert "not installed or not authenticated" in (builder.last_error or "")
    assert "Data Analyst 2026 graduate" in plan.keywords


def test_auto_search_plan_builder_falls_back_when_codex_output_fails() -> None:
    class FailingCodexProvider:
        def is_available(self) -> bool:
            return True

        def generate_json(self, _prompt):
            raise RuntimeError("bad codex output")

    profile = UserProfile(
        graduation_date="2026-06",
        target_roles=["Data Analyst"],
        skills=["Python"],
        preferred_locations=["Shanghai"],
        preferred_company_types=["Bank"],
    )
    builder = AutoSearchPlanBuilder(codex_provider=FailingCodexProvider())  # type: ignore[arg-type]

    plan = builder.build(profile)

    assert builder.last_source == "deterministic"
    assert builder.last_error == "bad codex output"
    assert "Data Analyst 2026 graduate" in plan.keywords


def test_search_strategy_cli_prints_deterministic_plan(capsys, tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "graduation_date": "2026-06",
                "target_roles": ["Data Analyst"],
                "skills": ["Python"],
                "preferred_locations": ["Shanghai"],
                "preferred_company_types": ["Bank"],
            }
        ),
        encoding="utf-8",
    )

    exit_code = search_strategy_cli_main(
        ["--provider", "deterministic", "--show-meta", "--profile-file", str(profile_path)]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"provider": "deterministic"' in captured.out
    assert "Data Analyst 2026 graduate" in captured.out


def test_search_strategy_cli_reports_incomplete_profile(capsys, tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        '{"graduation_date": "2026", "target_roles": [], "skills": ["Python"]}',
        encoding="utf-8",
    )

    exit_code = search_strategy_cli_main(
        [
            "--provider",
            "deterministic",
            "--profile-file",
            str(profile_path),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert '"is_complete": false' in captured.out
    assert "target_roles" in captured.out


def test_search_strategy_cli_debug_prints_codex_raw_output(capsys, monkeypatch) -> None:
    class FakeCodexProvider:
        last_debug_info = CodexCliDebugInfo(
            command=["codex", "exec"],
            prompt="prompt text",
            stdout="raw stdout",
            stderr="raw stderr",
            returncode=0,
        )

        def is_available(self) -> bool:
            return True

        def generate_json(self, _prompt):
            raise RuntimeError("bad json")

    monkeypatch.setattr(
        "job_radar.cli.search_strategy.CodexCliProvider",
        lambda: FakeCodexProvider(),
    )

    exit_code = search_strategy_cli_main(["--provider", "codex", "--debug"])

    captured = capsys.readouterr()

    assert exit_code == 3
    assert "Search strategy generation failed: bad json" in captured.err
    assert "--- DEBUG: Prompt sent to Codex ---" in captured.err
    assert "raw stdout" in captured.err
    assert "raw stderr" in captured.err


def test_codex_provider_uses_utf8_for_prompt(monkeypatch) -> None:
    captured = {}

    def fake_which(_command):
        return "codex.CMD"

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["input"] = kwargs.get("input")
        captured["encoding"] = kwargs.get("encoding")
        captured["errors"] = kwargs.get("errors")

        class Result:
            returncode = 0
            stdout = '{"target_roles":[],"locations":[],"company_types":[],"keywords":[]}'
            stderr = ""

        return Result()

    monkeypatch.setattr("job_radar.ai.providers.codex_cli.shutil.which", fake_which)
    monkeypatch.setattr("job_radar.ai.providers.codex_cli.subprocess.run", fake_run)

    provider = CodexCliProvider()
    provider.generate_json("\ufeff生成搜索策略")

    assert captured["command"] == ["codex.CMD", "exec"]
    assert captured["input"] == "\ufeff生成搜索策略"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


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

    monkeypatch.setattr("job_radar.ai.providers.ollama.urlopen", fake_urlopen)

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

    monkeypatch.setattr("job_radar.ai.providers.ollama.urlopen", fake_urlopen)

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


def test_job_understanding_analyzer_returns_discipline_neutral_facts() -> None:
    job = make_prepared_job(
        title="Policy Graduate",
        description="Prepare policy briefs and consult stakeholders on public programs.",
        requirements="Strong written communication, research judgment, and 2026 graduates.",
    )
    profile = UserProfile(
        graduation_date="2026-06",
        target_roles=["Policy Analyst"],
        skills=["writing", "research"],
    )
    provider = MockAIProvider(
        {
            "canonical_role": "Policy Graduate",
            "role_family": "policy",
            "seniority": "graduate",
            "responsibilities": ["Prepare policy briefs.", "Consult stakeholders."],
            "hard_requirements": [
                {
                    "category": "communication",
                    "importance": "hard",
                    "text": "Strong written communication.",
                    "evidence": "Strong written communication",
                }
            ],
            "preferred_requirements": [],
            "eligibility_constraints": [
                {
                    "category": "graduation_or_cohort",
                    "importance": "hard",
                    "text": "Open to 2026 graduates.",
                    "evidence": "2026 graduates",
                }
            ],
            "work_context": ["Public programs."],
            "risk_flags": [],
            "evidence": ["Prepare policy briefs", "Strong written communication"],
            "confidence": "high",
        }
    )

    record = JobUnderstandingAnalyzer(provider).understand(job, profile)

    assert record.source == "ai"
    assert record.basic_gate.decision == "continue"
    assert record.understanding is not None
    assert record.understanding.hard_requirements[0].category == "communication"
    assert "technical_skill" not in provider.prompts[1]


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
    assert assessment.match_score == 90
    assert assessment.recommendation == "apply"
    assert assessment.confidence == "medium"
    assert assessment.risk_flags == ["non_official_source", "vague_tech_stack"]
    assert provider.prompts
    assert "You are Job Radar's semantic match analysis component." in provider.prompts[0]
    assert '"candidate_profile"' in provider.prompts[1]
    assert "fixed scoring rubric" in provider.prompts[0].lower()


def test_analyze_matches_cli_writes_structured_assessments(capsys, monkeypatch, tmp_path) -> None:
    job_understandings_path = tmp_path / "job_understandings.json"
    output_path = tmp_path / "match_assessments.json"
    profile_dir = tmp_path / "config"
    profile_dir.mkdir()
    profile_dir.joinpath("profile.yaml").write_text(
        json.dumps(
            {
                "graduation_date": "2026-06",
                "target_roles": ["Software Engineer"],
                "skills": ["Python", "SQL"],
                "preferred_locations": ["Sydney"],
                "excluded_locations": [],
            }
        ),
        encoding="utf-8",
    )
    job = make_prepared_job()
    basic_gate = evaluate_basic_gate(
        job,
        UserProfile(
            graduation_date="2026-06",
            target_roles=["Software Engineer"],
            skills=["Python", "SQL"],
        ),
    )
    understanding_record = JobUnderstandingRecord(
        deduplication_key=job.deduplication_key,
        company_name=job.company_name or "",
        title=job.title or "",
        job=job,
        basic_gate=basic_gate,
        understanding=None,
        source="ai",
    )
    job_understandings_path.write_text(
        json.dumps([understanding_record.model_dump()], ensure_ascii=False),
        encoding="utf-8",
    )

    class FakeOllamaProvider:
        def __init__(self, model="qwen3.5:cloud", base_url="http://localhost:11434"):
            self.model = model
            self.base_url = base_url

        def is_available(self):
            return True

        def generate_json(self, prompt, timeout_seconds=180, system_prompt=None):
            assert system_prompt
            assert "candidate_profile" in prompt
            assert "job_understanding" in prompt
            return {
                "match_score": 82,
                "role_fit": "high",
                "must_have_fit": "yes",
                "match_reasons": ["Backend systems and SQL are relevant."],
                "missing_requirements": ["Exact framework is not specified."],
                "risk_flags": [],
                "job_summary": "Graduate technology role for internal banking systems.",
                "recommendation": "apply",
                "confidence": "high",
            }

    monkeypatch.setattr("job_radar.cli.analyze_matches.OllamaProvider", FakeOllamaProvider)

    exit_code = analyze_matches_cli_main(
        [
            "--job-understandings-file",
            str(job_understandings_path),
            "--profile-dir",
            str(profile_dir),
            "--output-file",
            str(output_path),
        ]
    )

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assessments = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["assessment_count"] == 1
    assert report["provider"] == "ollama"
    assert assessments[0]["deduplication_key"] == job.deduplication_key
    assert assessments[0]["assessment"]["match_score"] == 82
    assert assessments[0]["assessment"]["analysis_source"] == "ai"


def test_understand_jobs_cli_writes_understanding_artifacts(capsys, monkeypatch, tmp_path) -> None:
    prepared_jobs_path = tmp_path / "prepared_jobs.json"
    output_path = tmp_path / "job_understandings.json"
    profile_dir = tmp_path / "config"
    profile_dir.mkdir()
    profile_dir.joinpath("profile.yaml").write_text(
        json.dumps(
            {
                "graduation_date": "2026-06",
                "target_roles": ["Policy Analyst"],
                "skills": ["writing", "research"],
                "preferred_locations": ["Sydney"],
                "excluded_locations": [],
            }
        ),
        encoding="utf-8",
    )
    job = make_prepared_job(
        title="Policy Graduate",
        description="Prepare policy briefs and consult stakeholders.",
        requirements="Strong written communication and 2026 graduates.",
    )
    prepared_jobs_path.write_text(json.dumps([job.model_dump()], ensure_ascii=False), encoding="utf-8")

    class FakeOllamaProvider:
        def __init__(self, model="qwen3:8b", base_url="http://localhost:11434"):
            self.model = model
            self.base_url = base_url

        def is_available(self):
            return True

        def generate_json(self, prompt, timeout_seconds=180, system_prompt=None):
            assert system_prompt
            assert "program_basic_gate" in prompt
            return {
                "canonical_role": "Policy Graduate",
                "role_family": "policy",
                "seniority": "graduate",
                "responsibilities": ["Prepare policy briefs.", "Consult stakeholders."],
                "hard_requirements": [
                    {
                        "category": "communication",
                        "importance": "hard",
                        "text": "Strong written communication.",
                        "evidence": "Strong written communication",
                    }
                ],
                "preferred_requirements": [],
                "eligibility_constraints": [
                    {
                        "category": "graduation_or_cohort",
                        "importance": "hard",
                        "text": "Open to 2026 graduates.",
                        "evidence": "2026 graduates",
                    }
                ],
                "work_context": [],
                "risk_flags": [],
                "evidence": ["Prepare policy briefs", "Strong written communication"],
                "confidence": "high",
            }

    monkeypatch.setattr("job_radar.cli.understand_jobs.OllamaProvider", FakeOllamaProvider)

    exit_code = understand_jobs_cli_main(
        [
            "--prepared-jobs-file",
            str(prepared_jobs_path),
            "--profile-dir",
            str(profile_dir),
            "--output-file",
            str(output_path),
        ]
    )

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    records = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["ollama_model"] == "gpt-oss:20b-cloud"
    assert report["understanding_count"] == 1
    assert records[0]["source"] == "ai"
    assert records[0]["job"]["deduplication_key"] == job.deduplication_key
    assert records[0]["basic_gate"]["decision"] == "continue"
    assert records[0]["understanding"]["hard_requirements"][0]["category"] == "communication"


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


def test_codex_web_search_tool_validates_candidate_sources() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.prompt = ""

        def generate_json(self, prompt, timeout_seconds=240):
            self.prompt = prompt
            return [
                {
                    "url": "https://careers.example/job/123",
                    "title": "Data Analyst Graduate",
                    "source_name": "Example Careers",
                    "company_name": "Example",
                    "company_type": "Technology",
                    "is_official": True,
                    "relevance_score": 92,
                    "reason": "Concrete graduate job page.",
                }
            ]

    provider = FakeProvider()
    plan = SearchPlanBuilder().build(
        UserProfile(
            graduation_date="2026-06",
            target_roles=["Data Analyst"],
            skills=["Python"],
            preferred_locations=["Shanghai"],
            preferred_company_types=["Bank"],
        )
    )

    sources = CodexWebSearchTool(provider=provider).run(plan)  # type: ignore[arg-type]

    assert sources[0].url == "https://careers.example/job/123"
    assert sources[0].relevance_score == 92
    assert "Use web search" in provider.prompt
    assert '"cohort_year": 2026' in provider.prompt
    assert "2027届 means expected graduation between 2026-09 and 2027-06" in provider.prompt


def test_web_search_cli_prints_mock_sources(capsys, tmp_path) -> None:
    plan_path = tmp_path / "search_plan.json"
    plan_path.write_text(
        '{"target_roles":["Data Analyst"],"locations":["Shanghai"],"company_types":["Bank"],"keywords":["Data Analyst graduate Shanghai"]}',
        encoding="utf-8",
    )

    exit_code = web_search_cli_main(["--provider", "mock", "--plan-file", str(plan_path)])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "mock://future-bank/campus" in captured.out


def test_web_search_cli_debug_prints_codex_raw_output(capsys, monkeypatch, tmp_path) -> None:
    class FakeCodexProvider:
        last_debug_info = CodexCliDebugInfo(
            command=["codex", "exec"],
            prompt="web search prompt",
            stdout="raw web stdout",
            stderr="raw web stderr",
            returncode=0,
        )

        def is_available(self) -> bool:
            return True

        def generate_json(self, _prompt, timeout_seconds=240):
            raise RuntimeError("bad web json")

    plan_path = tmp_path / "search_plan.json"
    plan_path.write_text(
        '{"target_roles":["Data Analyst"],"locations":["Shanghai"],"company_types":["Bank"],"keywords":["Data Analyst graduate Shanghai"]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "job_radar.cli.web_search.CodexCliProvider",
        lambda: FakeCodexProvider(),
    )

    exit_code = web_search_cli_main(["--provider", "codex", "--plan-file", str(plan_path), "--debug"])

    captured = capsys.readouterr()

    assert exit_code == 3
    assert "web_search failed: bad web json" in captured.err
    assert "raw web stdout" in captured.err
    assert "raw web stderr" in captured.err


def test_agent_tool_executor_runs_mock_search_and_collection() -> None:
    profile, _, _ = load_profile(CONFIG_DIR)
    agent = make_agent()

    records, result = agent.discover(profile)

    assert result.profile_check.is_complete
    assert result.search_plan is not None
    assert len(result.candidate_sources) == 3
    assert len(result.selected_sources) == 2
    assert [event.tool_name for event in result.tool_events] == [
        "web_search",
        "collect_page",
        "collect_page",
    ]
    assert len(records) == 3
    assert records[0].source_name == "Future Bank Careers"


def test_agent_orchestrator_feeds_existing_pipeline(temp_db_path) -> None:
    profile, _, _ = load_profile(CONFIG_DIR)
    rules, _, _ = load_matching_rules(CONFIG_DIR)
    agent = make_agent()
    agent_result = None

    def collect_raw_records() -> list[RawJobRecord]:
        nonlocal agent_result
        records, agent_result = agent.discover(profile)
        return records

    runner = PipelineRunner(
        collect_raw_records=collect_raw_records,
        repository=JobRepository(temp_db_path),
        profile=profile,
        rules=rules,
    )

    result = runner.run()

    assert result.collected_count == 3
    assert result.valid_count == 3
    assert result.invalid_count == 0
    assert result.inserted_count == 3
    assert agent_result is not None
    assert agent_result.extracted_count == 3


def test_ingestion_service_runs_mock_agent_pipeline(temp_db_path) -> None:
    result, notices, agent_result = IngestionService(db_path=temp_db_path).run_mock_agent_pipeline()

    assert result.collected_count == 3
    assert result.inserted_count == 3
    assert result.failed_count == 0
    assert agent_result.collected_pages_count == 2
    assert any("rule-based extraction" in notice for notice in notices)


def test_load_candidate_sources_reads_enabled_manual_source() -> None:
    sources, used_example, _ = load_candidate_sources(CONFIG_DIR)

    assert used_example
    assert sources
    assert sources[0].url == "https://kedacom.zhiye.com/zpdetail/511158941"
    assert sources[0].company_name == "苏州科达科技股份有限公司"


def test_http_page_tool_reads_local_html(temp_db_path) -> None:
    html_path = temp_db_path.parent / "kedacom.html"
    html_path.write_text(
        """
        <html>
          <head><title>驱动开发工程师（2026校园招聘）</title></head>
          <body>
            <h1>驱动开发工程师（2026校园招聘）</h1>
            <div>工作地点：江苏省-苏州市</div>
            <a href="/apply">现在申请</a>
            <section>工作职责：</section>
            <p>负责嵌入式系统、驱动、媒体、传输、存储、安全等相关领域技术开发工作。</p>
            <section>任职资格：</section>
            <p>通信、电子、计算机、自动化、数学等相关专业，硕士及以上学历。</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    source = CandidateSource(
        url=html_path.as_uri(),
        title="Kedacom local test",
        source_name="Kedacom local test",
        company_name="苏州科达科技股份有限公司",
        company_type="Technology",
        is_official=True,
        relevance_score=100,
    )

    page = HttpPageTool().run(source)

    assert page.title == "驱动开发工程师（2026校园招聘）"
    assert "工作职责" in page.text
    assert page.metadata["company_name"] == "苏州科达科技股份有限公司"
    assert page.metadata["status_code"] == 200
    assert page.metadata["final_url"].startswith("file:")
    assert page.metadata["links"][0]["href"].endswith("/apply")


def test_rule_based_extractor_uses_candidate_source_location_fallback() -> None:
    page = PageContent(
        url="https://careers.example/jobs/software-engineer-shanghai",
        source_name="Example Careers",
        title="Software Engineer Graduate",
        text="Software Engineer Graduate\nBuild internal tools and data services.",
        metadata={
            "company_name": "Example Tech",
            "company_type": "Technology",
            "location": "Shanghai",
            "source_title": "Software Engineer Graduate - Shanghai",
            "source_reason": "Official graduate software engineering posting in Shanghai.",
            "is_official": True,
        },
    )

    record = RuleBasedJobExtractor().extract(page)[0]

    assert record.location == "Shanghai"


def test_page_filter_accepts_job_like_page() -> None:
    page = PageContent(
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

    result = filter_pages([page], min_text_length=80)

    assert result.readable_pages == [page]
    assert result.rejected_pages == []


def test_page_filter_rejects_obvious_non_job_page() -> None:
    page = PageContent(
        url="https://careers.example/login",
        source_name="Example Careers",
        title="Login",
        text="Please login or sign in to continue.",
        metadata={"status_code": 200, "final_url": "https://careers.example/login"},
    )

    result = filter_pages([page], min_text_length=80)

    assert result.readable_pages == []
    assert result.rejected_pages[0].url == "https://careers.example/login"
    assert any("auth_wall" in reason for reason in result.rejected_pages[0].reasons)


def test_page_filter_does_not_reject_job_page_for_nav_login_words() -> None:
    page = PageContent(
        url="https://www.boc.cn/aboutboc/bi4/202603/t20260311_25654053.html",
        source_name="Bank of China",
        title="Bank of China 2026 Spring Recruitment Notice",
        text=(
            "登录 注册 中国银行股份有限公司2026年春季招聘公告 "
            "招聘公告 校园招聘 工作地点 任职要求 岗位职责 数据分析 科技岗 "
            "This page contains detailed campus recruitment information for 2026 graduates."
        ),
        metadata={"status_code": 200, "final_url": "https://www.boc.cn/aboutboc/bi4/202603/t20260311_25654053.html"},
    )

    result = filter_pages([page], min_text_length=80)

    assert result.readable_pages == [page]
    assert result.rejected_pages == []


def test_page_filter_keeps_redirected_detail_to_listing_page() -> None:
    page = PageContent(
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

    result = filter_pages([page], search_plan=plan, min_text_length=80)

    assert result.readable_pages == [page]
    assert result.rejected_pages == []


def test_page_filter_marks_short_collectable_page_pending() -> None:
    page = PageContent(
        url="https://job.xiaohongshu.com/campus/position/17071",
        source_name="Xiaohongshu Campus Careers",
        title="Xiaohongshu",
        text="小红书",
        metadata={"status_code": 200, "final_url": "https://job.xiaohongshu.com/campus/position/17071"},
    )

    result = filter_pages([page], min_text_length=300)

    assert result.readable_pages == []
    assert result.pending_pages[0].url == page.url
    assert any("insufficient_visible_text" in reason for reason in result.pending_pages[0].reasons)
    assert result.rejected_pages == []


def test_page_filter_rejects_redirected_error_page() -> None:
    page = PageContent(
        url="https://job-boards.greenhouse.io/letsgetchecked/jobs/4833407101",
        source_name="LetsGetChecked Greenhouse",
        title="Jobs at LetsGetChecked",
        text="Jobs at LetsGetChecked. Search openings.",
        metadata={
            "status_code": 200,
            "final_url": "https://job-boards.greenhouse.io/letsgetchecked?error=true",
        },
    )

    result = filter_pages([page], min_text_length=30)

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
            title=f"算法工程师 {index}",
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


def test_collect_pages_cli_filters_local_pages(capsys, tmp_path) -> None:
    job_path = tmp_path / "job.html"
    job_path.write_text(
        """
        <html>
          <head><title>Data Analyst Graduate 2026</title></head>
          <body>
            <h1>Data Analyst Graduate 2026</h1>
            <p>Graduate Program responsibilities requirements qualifications location apply.</p>
            <p>Python SQL data analysis role for early careers candidates.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    login_path = tmp_path / "login.html"
    login_path.write_text(
        "<html><head><title>Login</title></head><body>Please login or sign in to continue.</body></html>",
        encoding="utf-8",
    )
    sources_path = tmp_path / "sources.json"
    pages_path = tmp_path / "readable_pages.json"
    sources_path.write_text(
        f"""
        [
          {{
            "url": "{job_path.as_uri()}",
            "title": "Data Analyst Graduate 2026",
            "source_name": "Example Careers",
            "company_name": "Example",
            "company_type": "Technology",
            "is_official": true,
            "relevance_score": 95
          }},
          {{
            "url": "{login_path.as_uri()}",
            "title": "Login",
            "source_name": "Example Careers",
            "company_name": "Example",
            "company_type": "Technology",
            "is_official": true,
            "relevance_score": 20
          }}
        ]
        """,
        encoding="utf-8",
    )

    exit_code = collect_pages_cli_main(
        [
            "--sources-file",
            str(sources_path),
            "--min-text-length",
            "50",
            "--snippet-chars",
            "20",
            "--output-readable-pages-file",
            str(pages_path),
        ]
    )

    captured = capsys.readouterr()
    saved_pages = json.loads(pages_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert '"readable_count": 1' in captured.out
    assert '"pending_count": 0' in captured.out
    assert '"rejected_count": 1' in captured.out
    assert "Data Analyst Graduate 2026" in captured.out
    assert "auth_wall" in captured.out
    assert len(saved_pages) == 1
    assert saved_pages[0]["url"] == job_path.as_uri()
    assert "Python SQL data analysis role for early careers candidates." in saved_pages[0]["text"]
    assert "<html>" in saved_pages[0]["html"]


def test_collect_pages_cli_overwrites_run_artifacts(capsys, tmp_path) -> None:
    job_path = tmp_path / "job.html"
    job_path.write_text(
        """
        <html>
          <head><title>Business Analyst Graduate 2026</title></head>
          <body>
            <h1>Business Analyst Graduate 2026</h1>
            <p>Graduate Program responsibilities requirements qualifications location apply.</p>
            <p>SQL dashboards and stakeholder analysis for early careers candidates.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    sources_path = tmp_path / "sources.json"
    sources_path.write_text(
        f"""
        [
          {{
            "url": "{job_path.as_uri()}",
            "title": "Business Analyst Graduate 2026",
            "source_name": "Example Careers",
            "company_name": "Example",
            "company_type": "Technology",
            "is_official": true,
            "relevance_score": 95
          }}
        ]
        """,
        encoding="utf-8",
    )
    runs_dir = tmp_path / "page_runs"

    exit_code = collect_pages_cli_main(
        [
            "--sources-file",
            str(sources_path),
            "--min-text-length",
            "50",
            "--output-run-dir",
            str(runs_dir),
        ]
    )

    captured = capsys.readouterr()
    pages_path = runs_dir / "readable_pages.json"
    pending_path = runs_dir / "pending_pages.json"
    report_path = runs_dir / "page_collection_report.json"
    saved_pages = TypeAdapter(list[PageContent]).validate_python(
        json.loads(pages_path.read_text(encoding="utf-8"))
    )
    saved_report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert [path for path in runs_dir.iterdir() if path.is_dir()] == []
    assert pages_path.exists()
    assert pending_path.exists()
    assert report_path.exists()
    assert len(saved_pages) == 1
    assert saved_pages[0].title == "Business Analyst Graduate 2026"
    assert saved_report["collected_at"]
    assert saved_report["artifacts"]["run_dir"] == str(runs_dir)
    assert saved_report["artifacts"]["readable_pages_file"] == str(pages_path)
    assert saved_report["artifacts"]["pending_pages_file"] == str(pending_path)
    assert "readable_pages_file" in captured.out


def test_classify_pages_cli_writes_clear_jd_pages_and_pending_followups(capsys, monkeypatch, tmp_path) -> None:
    pages_path = tmp_path / "cleaned_pages.json"
    output_pages_path = tmp_path / "jd_cleaned_pages.json"
    output_pending_path = tmp_path / "pending_followups.json"
    output_report_path = tmp_path / "page_classification_report.json"
    pages_path.write_text(
        json.dumps(
            [
                AIPageInput(
                    url="https://careers.example/job/1",
                    source_name="Example Careers",
                    source_company_name="Example",
                    company_type="Technology",
                    is_official=True,
                    title="Software Engineer Graduate",
                    visible_text=(
                        "Software Engineer Graduate. Responsibilities include building backend systems. "
                        "Requirements include Python and SQL. Location Sydney."
                    ),
                    final_url="https://careers.example/job/1",
                ).model_dump(),
                AIPageInput(
                    url="https://careers.example/early-careers",
                    source_name="Example Careers",
                    source_company_name="Example",
                    company_type="Technology",
                    is_official=True,
                    title="Early Careers",
                    visible_text="Explore graduate programs and search jobs.",
                    final_url="https://careers.example/early-careers",
                ).model_dump(),
            ]
        ),
        encoding="utf-8",
    )

    class FakeOllamaProvider:
        def __init__(self, model="qwen3:8b", base_url="http://localhost:11434"):
            self.model = model
            self.base_url = base_url

        def is_available(self):
            return True

        def generate_json(self, prompt, timeout_seconds=90, system_prompt=None):
            if "Software Engineer Graduate" in prompt:
                return {
                    "page_type": "job_detail",
                    "suggested_next_action": "extract_jobs",
                    "reasons": ["visible text contains responsibilities and requirements"],
                    "evidence": ["Responsibilities include building backend systems."],
                    "confidence": "high",
                }
            return {
                "page_type": "apply_portal",
                "suggested_next_action": "open_portal_and_find_job_detail_pages",
                "reasons": ["visible text is an early careers portal"],
                "evidence": ["Explore graduate programs and search jobs."],
                "confidence": "high",
            }

    monkeypatch.setattr("job_radar.cli.classify_pages.OllamaProvider", FakeOllamaProvider)

    exit_code = classify_pages_cli_main(
        [
            "--cleaned-pages-file",
            str(pages_path),
            "--output-jd-cleaned-pages-file",
            str(output_pages_path),
            "--output-pending-followups-file",
            str(output_pending_path),
            "--output-report-file",
            str(output_report_path),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    jd_pages = json.loads(output_pages_path.read_text(encoding="utf-8"))
    pending_followups = json.loads(output_pending_path.read_text(encoding="utf-8"))
    saved_report = json.loads(output_report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["jd_page_count"] == 1
    assert report["pending_followup_count"] == 1
    assert report["ollama_model"] == "qwen3:8b"
    assert saved_report["jd_page_count"] == 1
    assert jd_pages[0]["url"] == "https://careers.example/job/1"
    assert jd_pages[0]["visible_text"].startswith("Software Engineer Graduate")
    assert pending_followups[0]["url"] == "https://careers.example/early-careers"
    assert pending_followups[0]["pending_kind"] == "official_apply_portal"


def test_rule_based_extractor_structures_job_detail_page(temp_db_path) -> None:
    html_path = temp_db_path.parent / "kedacom.html"
    html_path.write_text(
        """
        <html>
          <head><title>驱动开发工程师（2026校园招聘）</title></head>
          <body>
            <h1>驱动开发工程师（2026校园招聘）</h1>
            <div>招聘类别：校园招聘</div>
            <div>工作地点：江苏省-苏州市 江苏省 苏州市 虎丘区</div>
            <div>发布时间：2026-05-15</div>
            <h2>工作职责：</h2>
            <p>负责嵌入式系统、驱动、媒体、传输、存储、安全等相关领域技术开发工作。</p>
            <h2>任职资格：</h2>
            <p>通信、电子、计算机、自动化、数学等相关专业，硕士及以上学历。</p>
            <p>熟悉linux开发环境，熟练掌握C/C++语言编程。</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    source = CandidateSource(
        url=html_path.as_uri(),
        title="Kedacom local test",
        source_name="Kedacom local test",
        company_name="苏州科达科技股份有限公司",
        company_type="Technology",
        is_official=True,
        relevance_score=100,
    )
    page = HttpPageTool().run(source)

    record = RuleBasedJobExtractor().extract(page)[0]

    assert record.company_name == "苏州科达科技股份有限公司"
    assert record.title == "驱动开发工程师（2026校园招聘）"
    assert record.location == "江苏省-苏州市 江苏省 苏州市 虎丘区"
    assert "嵌入式系统" in (record.description or "")
    assert "C/C++" in (record.requirements or "")
    assert record.recruitment_type == "Campus Recruitment"


def test_manual_source_tool_pipeline_with_local_html(temp_db_path) -> None:
    html_path = temp_db_path.parent / "kedacom.html"
    html_path.write_text(
        """
        <html>
          <head><title>驱动开发工程师（2026校园招聘）</title></head>
          <body>
            <h1>驱动开发工程师（2026校园招聘）</h1>
            <div>工作地点：江苏省-苏州市</div>
            <h2>工作职责：</h2>
            <p>负责嵌入式系统软件开发工作。</p>
            <h2>任职资格：</h2>
            <p>熟练掌握C/C++语言编程，熟悉linux开发环境。</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    source = CandidateSource(
        url=html_path.as_uri(),
        title="Kedacom local test",
        source_name="Kedacom local test",
        company_name="苏州科达科技股份有限公司",
        company_type="Technology",
        is_official=True,
        relevance_score=100,
    )
    executor = ToolExecutor([ManualSourceTool([source]), HttpPageTool()])
    profile, _, _ = load_profile(CONFIG_DIR)
    rules, _, _ = load_matching_rules(CONFIG_DIR)
    agent = JobDiscoveryAgent(
        job_extractor=RuleBasedJobExtractor(),
        tool_executor=executor,
    )
    agent_result = None

    def collect_raw_records() -> list[RawJobRecord]:
        nonlocal agent_result
        records, agent_result = agent.discover(profile)
        return records

    runner = PipelineRunner(
        collect_raw_records=collect_raw_records,
        repository=JobRepository(temp_db_path),
        profile=profile,
        rules=rules,
    )

    result = runner.run()

    assert result.collected_count == 1
    assert result.valid_count == 1
    assert result.inserted_count == 1
    assert agent_result is not None
    assert [event.tool_name for event in agent_result.tool_events] == ["web_search", "collect_page"]


def test_build_ai_page_input_preserves_provenance_but_drops_search_scoring() -> None:
    page = PageContent(
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
    page = PageContent(
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
    page = PageContent(
        url="https://www.boc.cn/recruitment",
        source_name="Bank of China",
        title="Spring recruitment",
        text=(
            "春季招聘网站为：\n"
            "https://campus.chinahr.com/pages/boc-2026-Spring\n"
            "请在线报名。"
        ),
        metadata={
            "links": [
                {
                    "href": "https://university.example/applyguide/index.html",
                    "text": "活动预告",
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


def test_clean_visible_text_removes_obvious_boilerplate_but_keeps_job_details() -> None:
    cleaned = clean_visible_text(
        """
        首页
        学生
        Data Analyst Graduate 2026
        岗位职责
        Build SQL dashboards and analyze product metrics.
        任职要求
        Python SQL statistics.
        温馨提示：抵制招聘诈骗，加强自我保护。
        联系我们
        """,
        max_text_chars=500,
    )

    assert "首页" not in cleaned.text
    assert "联系我们" not in cleaned.text
    assert "抵制招聘诈骗" not in cleaned.text
    assert "Data Analyst Graduate 2026" in cleaned.text
    assert "Python SQL statistics" in cleaned.text
    assert cleaned.removed_line_count >= 3


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


def test_clean_pages_cli_writes_ai_page_inputs(capsys, tmp_path) -> None:
    pages_path = tmp_path / "readable_pages.json"
    output_path = tmp_path / "cleaned_pages.json"
    report_path = tmp_path / "cleaning_report.json"
    pages_path.write_text(
        json.dumps(
            [
                {
                    "url": "https://careers.example/job/123",
                    "source_name": "Example Careers",
                    "title": "Data Analyst Graduate",
                    "text": (
                        "首页\n学生\nData Analyst Graduate\n岗位职责\nAnalyze metrics.\n"
                        "任职要求\nPython SQL.\n联系我们"
                    ),
                    "html": (
                        "<html><body><main><h1>Data Analyst Graduate</h1>"
                        "<p>Analyze metrics.</p><p>Python SQL.</p></main></body></html>"
                    ),
                    "metadata": {
                        "final_url": "https://careers.example/job/123",
                        "company_name": "Example",
                        "company_type": "Technology",
                        "is_official": True,
                        "relevance_score": 95,
                        "links": [
                            {"href": "https://careers.example/job-description.pdf", "text": "PDF"},
                            {"href": "https://careers.example/about", "text": "About"},
                        ],
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    exit_code = clean_pages_cli_main(
        [
            "--pages-file",
            str(pages_path),
            "--output-file",
            str(output_path),
            "--report-file",
            str(report_path),
            "--max-text-chars",
            "200",
            "--min-extracted-chars",
            "20",
        ]
    )

    captured = capsys.readouterr()
    cleaned_inputs = TypeAdapter(list[AIPageInput]).validate_python(
        json.loads(output_path.read_text(encoding="utf-8"))
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert len(cleaned_inputs) == 1
    assert cleaned_inputs[0].url == "https://careers.example/job/123"
    assert cleaned_inputs[0].source_name == "Example Careers"
    assert cleaned_inputs[0].source_company_name == "Example"
    assert cleaned_inputs[0].company_type == "Technology"
    assert cleaned_inputs[0].is_official is True
    assert "Analyze metrics" in cleaned_inputs[0].visible_text
    assert cleaned_inputs[0].important_links[0].kind == "attachment"
    assert "首页" not in cleaned_inputs[0].visible_text
    assert "relevance_score" not in output_path.read_text(encoding="utf-8")
    assert report["page_count"] == 1
    assert report["pages"][0]["method"] == "trafilatura"
    assert report["pages"][0]["important_link_count"] == 1
    assert "cleaned_at" in captured.out


def test_ai_job_extraction_client_prompts_with_minimal_page_input() -> None:
    page = PageContent(
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
    assert "Return every explicitly named position" in prompt


def test_ai_job_extraction_falls_back_to_source_location_after_semantic_response() -> None:
    provider = MockAIProvider(
        {
            "page_id": "page-1",
            "page_context": {"company_name": "Example"},
            "jobs": [{"title": "Software Engineer Graduate", "location": None}],
        }
    )
    page = PageContent(
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

    assert records[0].location == "Shanghai"
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


def test_extract_jobs_cli_prepares_cleaned_pages_with_ollama_provider(capsys, monkeypatch, tmp_path) -> None:
    cleaned_pages_path = tmp_path / "cleaned_pages.json"
    run_dir = tmp_path / "job_runs"
    cleaned_pages_path.write_text(
        json.dumps(
            [
                {
                    "url": "https://careers.example/job/1",
                    "final_url": "https://careers.example/job/1",
                    "source_name": "Example Careers",
                    "source_company_name": "Example Source Hint",
                    "company_type": "Technology",
                    "is_official": True,
                    "title": "Data Analyst Graduate",
                    "visible_text": "Data Analyst Graduate. Location Sydney. Requirements Python SQL.",
                    "important_links": [
                        {
                            "url": "https://careers.example/apply/1",
                            "text": "Apply",
                            "kind": "apply",
                            "reason": "apply_signal",
                        }
                    ],
                },
                {
                    "url": "https://careers.example/job/2",
                    "final_url": "https://careers.example/job/2",
                    "source_name": "Example Careers",
                    "title": "Data Analyst Graduate duplicate",
                    "visible_text": "Duplicate Data Analyst Graduate. Location Sydney.",
                    "important_links": [],
                },
                {
                    "url": "https://careers.example/job/3",
                    "final_url": "https://careers.example/job/3",
                    "source_name": "Example Careers",
                    "title": "Invalid missing title",
                    "visible_text": "Company Example. Location Sydney.",
                    "important_links": [],
                },
            ]
        ),
        encoding="utf-8",
    )

    class FakeOllamaProvider:
        calls = 0
        prompts = []

        def __init__(self, model="qwen3.5:cloud", base_url="http://localhost:11434"):
            self.model = model
            self.base_url = base_url

        def is_available(self):
            return True

        def generate_json(self, prompt, timeout_seconds=180):
            type(self).calls += 1
            type(self).prompts.append(prompt)
            return [
                {
                    "page_id": "page-1",
                    "page_context": {
                        "company_name": "Example",
                    },
                    "jobs": [
                        {
                            "title": "Data Analyst Graduate",
                            "location": "Sydney",
                            "description": "Analyze metrics.",
                            "requirements": "Python SQL.",
                        }
                    ],
                },
                {
                    "page_id": "page-2",
                    "page_context": {
                        "company_name": "Example",
                    },
                    "jobs": [
                        {
                            "title": "Data Analyst Graduate",
                            "location": "Sydney",
                            "description": "Analyze metrics.",
                            "requirements": "Python SQL.",
                        }
                    ],
                },
                {
                    "page_id": "page-3",
                    "page_context": {
                        "company_name": "Example",
                    },
                    "jobs": [{"location": "Sydney"}],
                },
            ]

    monkeypatch.setattr("job_radar.cli.extract_jobs.OllamaProvider", FakeOllamaProvider)

    exit_code = extract_jobs_cli_main(
        [
            "--cleaned-pages-file",
            str(cleaned_pages_path),
            "--output-run-dir",
            str(run_dir),
            "--max-pages",
            "3",
        ]
    )

    captured = capsys.readouterr()
    prepared_jobs = json.loads((run_dir / "prepared_jobs.json").read_text(encoding="utf-8"))
    report = json.loads(captured.out)

    assert exit_code == 0
    assert sorted(path.name for path in run_dir.iterdir()) == [
        "job_extraction_report.json",
        "pending_followups.json",
        "prepared_jobs.json",
    ]
    assert len(prepared_jobs) == 1
    assert json.loads((run_dir / "pending_followups.json").read_text(encoding="utf-8")) == []
    assert prepared_jobs[0]["normalized_title"] == "data analyst graduate"
    assert prepared_jobs[0]["source_url"] == "https://careers.example/job/1"
    assert prepared_jobs[0]["source_name"] == "Example Careers"
    assert prepared_jobs[0]["company_type"] == "Technology"
    assert prepared_jobs[0]["is_official"] is True
    assert prepared_jobs[0]["apply_url"] == "https://careers.example/apply/1"
    assert len(report["duplicate_jobs"]) == 1
    assert len(report["errors"]) == 1
    assert "title" in report["errors"][0]["reason"]
    assert report["prepared_count"] == 1
    assert report["duplicate_count"] == 1
    assert report["provider"] == "ollama"
    assert report["retry_count"] == 0
    assert report["timing"]["extraction_seconds"] >= 0
    assert report["timing"]["preparation_seconds"] >= 0
    assert report["timing"]["total_seconds"] >= report["timing"]["extraction_seconds"]
    assert "Loaded 3 cleaned page(s). Provider: ollama." in captured.err
    assert "[1-3/3] extracting" in captured.err
    assert "3 prepared candidate record(s), 0 pending page(s)" in captured.err
    assert FakeOllamaProvider.calls == 1


def test_extract_jobs_cli_moves_pages_without_extracted_jobs_to_pending(capsys, monkeypatch, tmp_path) -> None:
    cleaned_pages_path = tmp_path / "cleaned_pages.json"
    run_dir = tmp_path / "job_runs"
    cleaned_pages_path.write_text(
        json.dumps(
            [
                {
                    "url": "https://careers.example/portal",
                    "final_url": "https://careers.example/portal",
                    "source_name": "Example Careers",
                    "source_company_name": "Example",
                    "company_type": "Technology",
                    "is_official": True,
                    "title": "Example Graduate Portal",
                    "visible_text": "Search graduate programs and apply online.",
                    "important_links": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    class FakeOllamaProvider:
        def __init__(self, model="gpt-oss:20b-cloud", base_url="http://localhost:11434"):
            self.model = model
            self.base_url = base_url

        def is_available(self):
            return True

        def generate_json(self, prompt, timeout_seconds=180):
            return {
                "page_id": "page-1",
                "page_context": {"company_name": "Example"},
                "jobs": [],
            }

    monkeypatch.setattr("job_radar.cli.extract_jobs.OllamaProvider", FakeOllamaProvider)

    exit_code = extract_jobs_cli_main(
        [
            "--cleaned-pages-file",
            str(cleaned_pages_path),
            "--output-run-dir",
            str(run_dir),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    prepared_jobs = json.loads((run_dir / "prepared_jobs.json").read_text(encoding="utf-8"))
    pending_followups = json.loads((run_dir / "pending_followups.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert prepared_jobs == []
    assert report["prepared_count"] == 0
    assert report["extraction_error_count"] == 0
    assert report["new_pending_followup_count"] == 1
    assert pending_followups[0]["pending_kind"] == "no_jobs_extracted"


def test_extract_jobs_cli_prefers_extraction_ollama_model(capsys, monkeypatch, tmp_path) -> None:
    cleaned_pages_path = tmp_path / "cleaned_pages.json"
    run_dir = tmp_path / "job_runs"
    cleaned_pages_path.write_text("[]", encoding="utf-8")
    captured = {}

    class FakeOllamaProvider:
        def __init__(self, model="qwen3.5:cloud", base_url="http://localhost:11434"):
            captured["model"] = model
            self.model = model
            self.base_url = base_url

        def is_available(self):
            return True

        def generate_json(self, prompt, timeout_seconds=180):
            raise AssertionError("No extraction calls are expected for empty input")

    monkeypatch.setenv("JOB_RADAR_EXTRACTION_OLLAMA_MODEL", "gpt-oss-20b")
    monkeypatch.setattr("job_radar.cli.extract_jobs.OllamaProvider", FakeOllamaProvider)

    exit_code = extract_jobs_cli_main(
        [
            "--cleaned-pages-file",
            str(cleaned_pages_path),
            "--output-run-dir",
            str(run_dir),
        ]
    )

    assert exit_code == 0
    assert captured["model"] == "gpt-oss-20b"


def test_group_prepared_jobs_cli_writes_company_view(capsys, tmp_path) -> None:
    prepared_jobs_path = tmp_path / "prepared_jobs.json"
    output_path = tmp_path / "prepared_companies.json"
    jobs = [
        make_prepared_job(company_name="Bank of China", title="Data Analyst", location="Shanghai"),
        make_prepared_job(company_name="Bank of China", title="Software Engineer", location="Beijing"),
        make_prepared_job(company_name="Example Tech", title="Backend Engineer", location="Sydney"),
    ]
    prepared_jobs_path.write_text(
        json.dumps([job.model_dump() for job in jobs], ensure_ascii=False),
        encoding="utf-8",
    )

    exit_code = group_prepared_jobs_cli_main(
        [
            "--prepared-jobs-file",
            str(prepared_jobs_path),
            "--output-file",
            str(output_path),
        ]
    )

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    grouped = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["prepared_count"] == 3
    assert report["company_count"] == 2
    assert grouped[0]["company_name"] == "Bank of China"
    assert grouped[0]["job_count"] == 2
    assert [job["title"] for job in grouped[0]["jobs"]] == ["Data Analyst", "Software Engineer"]
    assert "company_name" not in grouped[0]["jobs"][0]


def test_llm_job_extractor_uses_llm_client_interface(temp_db_path) -> None:
    html_path = temp_db_path.parent / "job.html"
    html_path.write_text(
        """
        <html>
          <head><title>Data Analyst Graduate</title></head>
          <body>
            <h1>Data Analyst Graduate</h1>
            <p>company_name: Future Bank</p>
            <p>title: Data Analyst Graduate</p>
            <p>location: Shanghai</p>
            <p>source_name: Future Bank Careers</p>
            <p>source_url: mock://future-bank/job</p>
            <p>apply_url: https://careers.example/future-bank/job</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    source = CandidateSource(
        url=html_path.as_uri(),
        title="Future Bank local test",
        source_name="Future Bank Careers",
        is_official=True,
        relevance_score=100,
    )
    page = HttpPageTool().run(source)

    provider = MockAIProvider(
        {
            "company_name": "Future Bank",
            "title": "Data Analyst Graduate",
            "location": "Shanghai",
            "source_name": "Future Bank Careers",
            "source_url": "mock://future-bank/job",
            "apply_url": "https://careers.example/future-bank/job",
        }
    )

    class MockExtractionClient:
        def extract_jobs_from_page(self, _page):
            return [validate_model(provider.generate_json("extract"), RawJobRecord)]

    records = LLMJobExtractor(MockExtractionClient()).extract(page)

    assert records[0].company_name == "Future Bank"
    assert records[0].title == "Data Analyst Graduate"


def test_unconfigured_llm_job_extractor_fails_explicitly(temp_db_path) -> None:
    html_path = temp_db_path.parent / "job.html"
    html_path.write_text("<html><body><h1>Job</h1></body></html>", encoding="utf-8")
    source = CandidateSource(
        url=html_path.as_uri(),
        title="Unconfigured LLM test",
        source_name="Local test",
        is_official=True,
        relevance_score=100,
    )
    page = HttpPageTool().run(source)

    with pytest.raises(RuntimeError, match="LLM job extraction is not configured"):
        UnconfiguredLLMJobExtractor().extract(page)
