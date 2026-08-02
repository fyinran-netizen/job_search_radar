"""Ingestion use cases for the Streamlit UI and tests."""

from pathlib import Path

from job_radar.agent.orchestrator import JobDiscoveryAgent
from job_radar.config import load_candidate_sources, load_matching_rules, load_profile
from job_radar.extractors.rule_based import RuleBasedJobExtractor
from job_radar.models.decisions import AgentRunResult
from job_radar.models.job import RawJobRecord
from job_radar.models.profile import MatchingRules, UserProfile
from job_radar.pipeline.runner import PipelineResult, PipelineRunner
from job_radar.storage.repository import JobRepository
from job_radar.tools.factory import create_manual_http_tool_executor, create_mock_tool_executor
from job_radar.tools.functions.demo_csv import DemoCsvTool
from job_radar.utils.paths import CONFIG_DIR, DEFAULT_DB_PATH, DEMO_JOBS_PATH


class IngestionService:
    """Application service for running job ingestion."""

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        config_dir: Path = CONFIG_DIR,
        demo_csv_path: Path = DEMO_JOBS_PATH,
    ) -> None:
        self.db_path = db_path
        self.config_dir = config_dir
        self.demo_csv_path = demo_csv_path

    def run_demo_pipeline(self) -> tuple[PipelineResult, list[str]]:
        """Run the demo CSV tool through the complete pipeline."""

        profile, rules, notices = self._load_profile_rules_and_notices()

        runner = PipelineRunner(
            collect_raw_records=DemoCsvTool(self.demo_csv_path).collect,
            repository=JobRepository(self.db_path),
            profile=profile,
            rules=rules,
        )
        return runner.run(), notices

    def run_mock_agent_pipeline(self) -> tuple[PipelineResult, list[str], AgentRunResult]:
        """Run the mock agent and feed its output into the existing pipeline."""

        profile, rules, notices = self._load_profile_rules_and_notices()
        notices.append("Using mock web tools and rule-based extraction; no network requests or LLM API calls are made.")

        agent = JobDiscoveryAgent(
            job_extractor=RuleBasedJobExtractor(),
            tool_executor=create_mock_tool_executor(),
        )
        agent_result: AgentRunResult | None = None

        def collect_raw_records() -> list[RawJobRecord]:
            nonlocal agent_result
            records, agent_result = agent.discover(profile)
            return records

        runner = PipelineRunner(
            collect_raw_records=collect_raw_records,
            repository=JobRepository(self.db_path),
            profile=profile,
            rules=rules,
        )
        pipeline_result = runner.run()
        if agent_result is None:
            raise RuntimeError("Agent did not produce a run result.")
        return pipeline_result, notices, agent_result

    def run_manual_source_pipeline(self) -> tuple[PipelineResult, list[str], AgentRunResult]:
        """Run manually configured URLs through HTTP collection and extraction."""

        profile, rules, notices = self._load_profile_rules_and_notices()
        sources, sources_are_example, sources_path = load_candidate_sources(self.config_dir)
        if sources_are_example:
            notices.append(f"Using example sources config: {sources_path}")
        notices.append("Using manual source URLs, Python HTTP page collection, and rule-based extraction. No search API or LLM API is used.")

        agent = JobDiscoveryAgent(
            job_extractor=RuleBasedJobExtractor(),
            tool_executor=create_manual_http_tool_executor(sources),
        )
        agent_result: AgentRunResult | None = None

        def collect_raw_records() -> list[RawJobRecord]:
            nonlocal agent_result
            records, agent_result = agent.discover(profile)
            return records

        runner = PipelineRunner(
            collect_raw_records=collect_raw_records,
            repository=JobRepository(self.db_path),
            profile=profile,
            rules=rules,
        )
        pipeline_result = runner.run()
        if agent_result is None:
            raise RuntimeError("Agent did not produce a run result.")
        return pipeline_result, notices, agent_result

    def _load_profile_rules_and_notices(self) -> tuple[UserProfile, MatchingRules, list[str]]:
        profile, profile_is_example, profile_path = load_profile(self.config_dir)
        rules, rules_are_example, rules_path = load_matching_rules(self.config_dir)
        notices: list[str] = []
        if profile_is_example:
            notices.append(f"Using example profile config: {profile_path}")
        if rules_are_example:
            notices.append(f"Using example matching rules config: {rules_path}")
        return profile, rules, notices
