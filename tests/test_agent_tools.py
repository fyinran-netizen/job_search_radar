import json

import pytest
from pydantic import TypeAdapter, ValidationError

from job_radar.agent.orchestrator import JobDiscoveryAgent
from job_radar.cli.clean_pages import main as clean_pages_cli_main
from job_radar.cli.collect_pages import main as collect_pages_cli_main
from job_radar.cli.search_strategy import main as search_strategy_cli_main
from job_radar.cli.web_search import main as web_search_cli_main
from job_radar.ai.providers.codex_cli import CodexCliDebugInfo, CodexCliProvider
from job_radar.ai.providers.mock import MockAIProvider
from job_radar.ai.structured_output import validate_model
from job_radar.ai.tasks.job_extraction import (
    AIJobExtractionClient,
    AIPageInput,
    ImportantLink,
    build_ai_page_input,
    extract_important_links,
)
from job_radar.ai.tasks.search_strategy import AISearchPlanBuilder, AutoSearchPlanBuilder, SearchPlanBuilder
from job_radar.config import load_candidate_sources, load_matching_rules, load_profile
from job_radar.extractors.llm import LLMJobExtractor, UnconfiguredLLMJobExtractor
from job_radar.extractors.rule_based import RuleBasedJobExtractor
from job_radar.models.job import RawJobRecord
from job_radar.models.search import CandidateSource, SearchPlan
from job_radar.models.profile import UserProfile
from job_radar.models.tool import PageContent
from job_radar.pipeline.page_cleaning import clean_page_text, clean_visible_text
from job_radar.pipeline.page_filter import filter_pages
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
    profile, _, _ = load_profile(CONFIG_DIR)

    plan = SearchPlanBuilder().build(profile)

    assert "Data Analyst graduate" in plan.keywords
    assert "graduate jobs Shanghai" in plan.keywords
    assert "Bank graduate program" in plan.keywords


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

    profile, _, _ = load_profile(CONFIG_DIR)
    builder = AutoSearchPlanBuilder(codex_provider=UnavailableCodexProvider())  # type: ignore[arg-type]

    plan = builder.build(profile)

    assert builder.last_source == "deterministic"
    assert "not installed or not authenticated" in (builder.last_error or "")
    assert "Data Analyst graduate" in plan.keywords


def test_auto_search_plan_builder_falls_back_when_codex_output_fails() -> None:
    class FailingCodexProvider:
        def is_available(self) -> bool:
            return True

        def generate_json(self, _prompt):
            raise RuntimeError("bad codex output")

    profile, _, _ = load_profile(CONFIG_DIR)
    builder = AutoSearchPlanBuilder(codex_provider=FailingCodexProvider())  # type: ignore[arg-type]

    plan = builder.build(profile)

    assert builder.last_source == "deterministic"
    assert builder.last_error == "bad codex output"
    assert "Data Analyst graduate" in plan.keywords


def test_search_strategy_cli_prints_deterministic_plan(capsys) -> None:
    exit_code = search_strategy_cli_main(["--provider", "deterministic", "--show-meta"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"provider": "deterministic"' in captured.out
    assert "Data Analyst graduate" in captured.out


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
    plan = SearchPlanBuilder().build(load_profile(CONFIG_DIR)[0])

    sources = CodexWebSearchTool(provider=provider).run(plan)  # type: ignore[arg-type]

    assert sources[0].url == "https://careers.example/job/123"
    assert sources[0].relevance_score == 92
    assert "Use web search" in provider.prompt


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

    assert result.accepted_pages == [page]
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

    assert result.accepted_pages == []
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

    assert result.accepted_pages == [page]
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

    assert result.accepted_pages == [page]
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

    assert result.accepted_pages == []
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

    assert result.accepted_pages == []
    assert any("redirected_to_error_page" in reason for reason in result.rejected_pages[0].reasons)


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
    pages_path = tmp_path / "accepted_pages.json"
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
            "--output-pages-file",
            str(pages_path),
        ]
    )

    captured = capsys.readouterr()
    saved_pages = json.loads(pages_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert '"accepted_count": 1' in captured.out
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
    pages_path = runs_dir / "accepted_pages.json"
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
    assert saved_report["artifacts"]["accepted_pages_file"] == str(pages_path)
    assert saved_report["artifacts"]["pending_pages_file"] == str(pending_path)
    assert "accepted_pages_file" in captured.out


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


def test_build_ai_page_input_drops_search_metadata() -> None:
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

    assert [link.kind for link in links] == ["attachment", "apply"]
    assert links[0].url.endswith(".pdf")


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
    pages_path = tmp_path / "accepted_pages.json"
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
        [
            {
                "company_name": "Example",
                "title": "Data Analyst Graduate",
                "source_url": "https://careers.example/job/123",
                "source_name": "Example Careers",
            }
        ]
    )

    records = AIJobExtractionClient(provider, max_text_chars=200).extract_jobs_from_page(page)

    assert records[0].title == "Data Analyst Graduate"
    assert provider.prompts
    prompt = provider.prompts[0]
    input_payload = prompt.rsplit("Input:\n", maxsplit=1)[1]
    assert "visible_text" in input_payload
    assert "relevance_score" not in input_payload
    assert "Search result explanation" not in input_payload
    assert '"company_type": "Technology"' not in input_payload
    assert '"is_official": true' not in input_payload


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
