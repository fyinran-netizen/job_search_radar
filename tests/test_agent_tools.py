import pytest

from job_radar.agent.orchestrator import JobDiscoveryAgent
from job_radar.ai.providers.mock import MockAIProvider
from job_radar.ai.structured_output import validate_model
from job_radar.ai.tasks.profile_completeness import ProfileCompletenessChecker
from job_radar.ai.tasks.search_strategy import SearchPlanBuilder
from job_radar.config import load_candidate_sources, load_matching_rules, load_profile
from job_radar.extractors.llm import LLMJobExtractor, UnconfiguredLLMJobExtractor
from job_radar.extractors.rule_based import RuleBasedJobExtractor
from job_radar.models.job import RawJobRecord
from job_radar.models.search import CandidateSource
from job_radar.models.profile import UserProfile
from job_radar.pipeline.runner import PipelineRunner
from job_radar.services.ingestion_service import IngestionService
from job_radar.storage.repository import JobRepository
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.factory import create_mock_tool_executor
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


def test_search_plan_builder_generates_keywords() -> None:
    profile, _, _ = load_profile(CONFIG_DIR)

    plan = SearchPlanBuilder().build(profile)

    assert "Data Analyst graduate" in plan.keywords
    assert "graduate jobs Shanghai" in plan.keywords
    assert "Bank graduate program" in plan.keywords


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
    assert page.metadata["links"][0]["href"].endswith("/apply")


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
