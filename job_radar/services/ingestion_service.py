"""Ingestion use cases for the Streamlit UI and tests."""

from dataclasses import asdict
import json
import os
from pathlib import Path

from job_radar.agent.guardrails import select_candidate_sources
from job_radar.agent.orchestrator import JobDiscoveryAgent
from job_radar.ai.providers.ollama import OllamaProvider
from job_radar.ai.tasks.search_strategy import create_search_plan_builder
from job_radar.config import load_candidate_sources, load_matching_rules, load_profile
from job_radar.extractors.rule_based import RuleBasedJobExtractor
from job_radar.models.decisions import AgentRunResult
from job_radar.models.job import JobRecord, RawJobRecord
from job_radar.models.profile import MatchingRules, UserProfile
from job_radar.models.run import AgentLimits
from job_radar.models.search import CandidateSource
from job_radar.models.tool import PageContent
from job_radar.pipeline.job_preparation import prepare_records_for_analysis
from job_radar.pipeline.page_filter import PendingPage, RejectedPage
from job_radar.profile.completeness import ProfileCompletenessChecker
from job_radar.pipeline.runner import PipelineResult, PipelineRunner
from job_radar.storage.repository import JobRepository
from job_radar.tools.factory import create_manual_http_tool_executor, create_mock_tool_executor, create_real_search_tool_executor
from job_radar.tools.executor import ToolExecutor
from job_radar.tools.functions.job_semantics import (
    JobExtractionInput,
    JobExtractionOutput,
    JobUnderstandingToolInput,
    JobUnderstandingToolOutput,
    MatchAnalysisToolInput,
    MatchAnalysisToolOutput,
)
from job_radar.tools.functions.page_processing import (
    PageClassificationInput,
    PageClassificationOutput,
    PageCleaningInput,
    PageCleaningOutput,
    PageFilterInput,
    PageFilterOutput,
)
from job_radar.utils.paths import CONFIG_DIR, DEFAULT_DB_PATH, TEST_TMP_DIR


class IngestionService:
    """Application service for running job ingestion."""

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        config_dir: Path = CONFIG_DIR,
        enable_codex_ai: bool = False,
    ) -> None:
        self.db_path = db_path
        self.config_dir = config_dir
        self.enable_codex_ai = enable_codex_ai

    def run_mock_agent_pipeline(self, profile: UserProfile | None = None) -> tuple[PipelineResult, list[str], AgentRunResult]:
        """Run the mock agent and feed its output into the existing pipeline."""

        profile, rules, notices = self._load_profile_rules_and_notices(profile)
        notices.append("Using mock web tools and rule-based extraction; no network requests or LLM API calls are made.")

        agent = JobDiscoveryAgent(
            job_extractor=RuleBasedJobExtractor(),
            tool_executor=create_mock_tool_executor(),
            search_plan_builder=create_search_plan_builder(self.enable_codex_ai),
        )
        agent_result: AgentRunResult | None = None
        raw_records: list[RawJobRecord] = []

        def collect_raw_records() -> list[RawJobRecord]:
            nonlocal agent_result, raw_records
            raw_records, agent_result = agent.discover(profile)
            return raw_records

        runner = PipelineRunner(
            collect_raw_records=collect_raw_records,
            repository=JobRepository(self.db_path),
            profile=profile,
            rules=rules,
        )
        pipeline_result = runner.run()
        if agent_result is None:
            raise RuntimeError("Agent did not produce a run result.")
        notices.extend(self._search_plan_notices(agent_result))
        artifact_dir = self._write_run_artifacts(
            "mock",
            profile=profile,
            agent_result=agent_result,
            raw_records=raw_records,
            pipeline_result=pipeline_result,
        )
        notices.append(f"Mock artifacts written to: {artifact_dir}")
        return pipeline_result, notices, agent_result

    def run_real_search_pipeline(self, profile: UserProfile) -> tuple[PipelineResult, list[str], AgentRunResult]:
        """Run the real E2E path with Codex search and Ollama semantic extraction."""

        profile, rules, notices = self._load_profile_rules_and_notices(profile)
        limits = AgentLimits()
        profile_check = ProfileCompletenessChecker().check(profile)
        agent_result = AgentRunResult(profile_check=profile_check)
        metadata = self._real_run_metadata()
        if not profile_check.is_complete:
            pipeline_result = PipelineResult()
            artifact_dir = self._write_run_artifacts(
                "real",
                profile=profile,
                agent_result=agent_result,
                raw_records=[],
                pipeline_result=pipeline_result,
                extra_artifacts={"run_metadata": metadata},
            )
            notices.append(f"Real artifacts written to: {artifact_dir}")
            return pipeline_result, notices, agent_result

        notices.append("Using Codex CLI-backed web search and HTTP page collection.")
        notices.append(
            "Using Ollama page classification "
            f"({metadata['page_classification_model']}) and Ollama job extraction "
            f"({metadata['extraction_model']})."
        )

        search_plan_builder = create_search_plan_builder(self.enable_codex_ai)
        search_plan = search_plan_builder.build(profile)
        agent_result.search_plan = search_plan
        agent_result.search_plan_source = search_plan_builder.last_source
        agent_result.search_plan_error = search_plan_builder.last_error

        executor = self._create_real_tool_executor(metadata)
        candidate_sources = executor.run("web_search", search_plan)
        if not isinstance(candidate_sources, list):
            raise TypeError("web_search must return a list of CandidateSource objects")
        agent_result.candidate_sources = candidate_sources
        agent_result.selected_sources = select_candidate_sources(
            agent_result.candidate_sources,
            min_relevance_score=limits.min_relevance_score,
        )[: limits.max_sources_per_round]

        pages, collection_pending_pages, collection_rejected_pages = self._collect_real_pages(executor, agent_result.selected_sources)
        page_filter_output = executor.run(
            "page_filter",
            PageFilterInput(
                pages=pages,
                search_plan=search_plan,
                pending_pages=collection_pending_pages,
                rejected_pages=collection_rejected_pages,
            ),
        )
        if not isinstance(page_filter_output, PageFilterOutput):
            raise TypeError("page_filter must return PageFilterOutput")
        page_cleaning_output = executor.run(
            "page_cleaning",
            PageCleaningInput(pages=page_filter_output.readable_pages),
        )
        if not isinstance(page_cleaning_output, PageCleaningOutput):
            raise TypeError("page_cleaning must return PageCleaningOutput")
        page_classification_output = executor.run(
            "page_classification",
            PageClassificationInput(pages=page_cleaning_output.cleaned_pages),
        )
        if not isinstance(page_classification_output, PageClassificationOutput):
            raise TypeError("page_classification must return PageClassificationOutput")
        job_extraction_output = executor.run(
            "job_extraction",
            JobExtractionInput(pages=page_classification_output.jd_pages),
        )
        if not isinstance(job_extraction_output, JobExtractionOutput):
            raise TypeError("job_extraction must return JobExtractionOutput")
        raw_records = job_extraction_output.raw_records
        preparation = prepare_records_for_analysis(raw_records)
        job_understanding_output = executor.run(
            "job_understanding",
            JobUnderstandingToolInput(jobs=preparation.prepared_records, profile=profile),
        )
        if not isinstance(job_understanding_output, JobUnderstandingToolOutput):
            raise TypeError("job_understanding must return JobUnderstandingToolOutput")
        match_analysis_output = executor.run(
            "match_analysis",
            MatchAnalysisToolInput(records=job_understanding_output.records, profile=profile),
        )
        if not isinstance(match_analysis_output, MatchAnalysisToolOutput):
            raise TypeError("match_analysis must return MatchAnalysisToolOutput")
        final_jobs = self._apply_match_assessments(preparation.prepared_records, match_analysis_output)
        persistence_result = JobRepository(self.db_path).upsert_jobs(final_jobs)
        pipeline_result = PipelineResult(
            collected_count=len(raw_records),
            valid_count=preparation.valid_count,
            invalid_count=preparation.invalid_count,
            duplicate_count=preparation.duplicate_count,
            inserted_count=persistence_result.inserted_count,
            updated_count=persistence_result.updated_count,
            failed_count=persistence_result.failed_count,
            errors=[*preparation.errors, *persistence_result.errors],
        )

        agent_result.collected_pages_count = len(page_filter_output.readable_pages)
        agent_result.extracted_count = len(raw_records)
        agent_result.tool_events = executor.events
        notices.extend(self._search_plan_notices(agent_result))
        artifact_dir = self._write_run_artifacts(
            "real",
            profile=profile,
            agent_result=agent_result,
            raw_records=raw_records,
            pipeline_result=pipeline_result,
            extra_artifacts={
                "run_metadata": metadata,
                "readable_pages": [page.model_dump() for page in page_filter_output.readable_pages],
                "pending_pages": [page.model_dump() for page in page_filter_output.pending_pages],
                "rejected_pages": [page.model_dump() for page in page_filter_output.rejected_pages],
                "cleaned_pages": [page.model_dump() for page in page_cleaning_output.cleaned_pages],
                "jd_cleaned_pages": [page.model_dump() for page in page_classification_output.jd_pages],
                "page_cleaning_report": page_cleaning_output.report,
                "page_classification_report": page_classification_output.report,
                "job_extraction_report": job_extraction_output.report,
                "prepared_jobs": [record.model_dump() for record in preparation.prepared_records],
                "job_understandings": [record.model_dump() for record in job_understanding_output.records],
                "job_understanding_report": job_understanding_output.report,
                "match_assessments": match_analysis_output.assessments,
                "match_analysis_report": match_analysis_output.report,
                "matched_jobs": [record.model_dump() for record in final_jobs],
            },
        )
        notices.append(f"Real artifacts written to: {artifact_dir}")
        return pipeline_result, notices, agent_result

    def run_manual_source_pipeline(self, profile: UserProfile | None = None) -> tuple[PipelineResult, list[str], AgentRunResult]:
        """Run manually configured URLs through HTTP collection and extraction."""

        profile, rules, notices = self._load_profile_rules_and_notices(profile)
        sources, sources_are_example, sources_path = load_candidate_sources(self.config_dir)
        if sources_are_example:
            notices.append(f"Using example sources config: {sources_path}")
        notices.append("Using manual source URLs, Python HTTP page collection, and rule-based extraction. No search API or LLM API is used.")

        agent = JobDiscoveryAgent(
            job_extractor=RuleBasedJobExtractor(),
            tool_executor=create_manual_http_tool_executor(sources),
            search_plan_builder=create_search_plan_builder(False),
        )
        agent_result: AgentRunResult | None = None
        raw_records: list[RawJobRecord] = []

        def collect_raw_records() -> list[RawJobRecord]:
            nonlocal agent_result, raw_records
            raw_records, agent_result = agent.discover(profile)
            return raw_records

        runner = PipelineRunner(
            collect_raw_records=collect_raw_records,
            repository=JobRepository(self.db_path),
            profile=profile,
            rules=rules,
        )
        pipeline_result = runner.run()
        if agent_result is None:
            raise RuntimeError("Agent did not produce a run result.")
        notices.extend(self._search_plan_notices(agent_result))
        artifact_dir = self._write_run_artifacts(
            "real",
            profile=profile,
            agent_result=agent_result,
            raw_records=raw_records,
            pipeline_result=pipeline_result,
        )
        notices.append(f"Real artifacts written to: {artifact_dir}")
        return pipeline_result, notices, agent_result

    def _load_profile_rules_and_notices(self, profile: UserProfile | None = None) -> tuple[UserProfile, MatchingRules, list[str]]:
        if profile is None:
            profile, profile_is_example, profile_path = load_profile(self.config_dir)
        else:
            profile_is_example = False
            profile_path = None
        rules, rules_are_example, rules_path = load_matching_rules(self.config_dir)
        notices: list[str] = []
        if profile_is_example and profile_path is not None:
            notices.append(f"Using example profile config: {profile_path}")
        if rules_are_example:
            notices.append(f"Using example matching rules config: {rules_path}")
        return profile, rules, notices

    def _collect_real_pages(
        self,
        executor: ToolExecutor,
        sources: list[CandidateSource],
    ) -> tuple[list[PageContent], list[PendingPage], list[RejectedPage]]:
        pages: list[PageContent] = []
        pending_pages: list[PendingPage] = []
        rejected_pages: list[RejectedPage] = []
        for source in sources:
            try:
                page = executor.run("collect_page", source)
            except Exception as exc:
                if self._is_pending_fetch_error(exc):
                    pending_pages.append(
                        PendingPage(
                            url=source.url,
                            source_name=source.source_name,
                            title=source.title,
                            reasons=[f"fetch_error: {exc}"],
                            metadata=self._source_error_metadata(source),
                        )
                    )
                else:
                    rejected_pages.append(
                        RejectedPage(
                            url=source.url,
                            source_name=source.source_name,
                            title=source.title,
                            reasons=[f"fetch_error: {exc}"],
                            metadata=self._source_error_metadata(source),
                        )
                    )
                continue
            if not isinstance(page, PageContent):
                raise TypeError("collect_page must return PageContent")
            pages.append(page)
        return pages, pending_pages, rejected_pages

    def _create_real_tool_executor(self, metadata: dict[str, object]) -> ToolExecutor:
        extraction_provider = str(metadata["extraction_provider"])
        classification_provider = str(metadata["page_classification_provider"])
        if classification_provider != "ollama":
            raise RuntimeError(
                f"Streamlit real search supports JOB_RADAR_PAGE_CLASSIFICATION_PROVIDER=ollama, got {classification_provider!r}."
            )
        if extraction_provider != "ollama":
            raise RuntimeError(f"Streamlit real search supports JOB_RADAR_EXTRACTION_PROVIDER=ollama, got {extraction_provider!r}.")
        classification_ollama = OllamaProvider(
            model=str(metadata["page_classification_model"]),
            base_url=str(metadata["ollama_base_url"]),
        )
        extraction_ollama = OllamaProvider(
            model=str(metadata["extraction_model"]),
            base_url=str(metadata["ollama_base_url"]),
        )
        understanding_ollama = OllamaProvider(
            model=str(metadata["understanding_model"]),
            base_url=str(metadata["ollama_base_url"]),
        )
        match_ollama = OllamaProvider(
            model=str(metadata["match_model"]),
            base_url=str(metadata["ollama_base_url"]),
        )
        if (
            not classification_ollama.is_available()
            or not extraction_ollama.is_available()
            or not understanding_ollama.is_available()
            or not match_ollama.is_available()
        ):
            raise RuntimeError(f"Ollama server is not reachable at {metadata['ollama_base_url']}.")
        return create_real_search_tool_executor(
            page_classification_provider=classification_ollama,
            job_extraction_provider=extraction_ollama,
            job_understanding_provider=understanding_ollama,
            match_analysis_provider=match_ollama,
        )

    @staticmethod
    def _apply_match_assessments(
        jobs: list[JobRecord],
        match_output: MatchAnalysisToolOutput,
    ) -> list[JobRecord]:
        assessments_by_key = {
            str(item.get("deduplication_key")): item.get("assessment")
            for item in match_output.assessments
            if item.get("deduplication_key") and isinstance(item.get("assessment"), dict)
        }
        final_jobs = []
        for job in jobs:
            assessment = assessments_by_key.get(job.deduplication_key)
            if assessment:
                job.match_score = int(assessment.get("match_score", 0))
                job.match_reasons = [str(item) for item in assessment.get("match_reasons", [])]
                job.missing_requirements = [str(item) for item in assessment.get("missing_requirements", [])]
                if not job.match_reasons:
                    recommendation = assessment.get("recommendation")
                    confidence = assessment.get("confidence")
                    job.match_reasons = [f"Semantic match completed: recommendation={recommendation}, confidence={confidence}"]
            else:
                job.match_score = 0
                job.match_reasons = ["Semantic match was not completed for this job."]
                job.missing_requirements = []
            final_jobs.append(job)
        return final_jobs

    @staticmethod
    def _source_error_metadata(source: CandidateSource) -> dict[str, object]:
        return {
            "company_name": source.company_name,
            "company_type": source.company_type,
            "location": source.location,
            "is_official": source.is_official,
            "relevance_score": source.relevance_score,
            "reason": source.reason,
        }

    @staticmethod
    def _is_pending_fetch_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(
            marker in text
            for marker in [
                "403",
                "forbidden",
                "429",
                "too many requests",
                "timed out",
                "timeout",
                "winerror 10013",
            ]
        )

    @staticmethod
    def _real_run_metadata() -> dict[str, object]:
        return {
            "web_search_provider": "codex_cli",
            "page_collection_provider": "http",
            "page_classification_provider": os.environ.get("JOB_RADAR_PAGE_CLASSIFICATION_PROVIDER", "ollama"),
            "page_classification_model": os.environ.get("JOB_RADAR_PAGE_CLASSIFICATION_OLLAMA_MODEL", "qwen3:8b"),
            "extraction_provider": os.environ.get("JOB_RADAR_EXTRACTION_PROVIDER", "ollama"),
            "extraction_model": os.environ.get("JOB_RADAR_EXTRACTION_OLLAMA_MODEL", "gpt-oss:20b-cloud"),
            "understanding_provider": "ollama",
            "understanding_model": os.environ.get("JOB_RADAR_UNDERSTANDING_OLLAMA_MODEL", "gpt-oss:20b-cloud"),
            "match_provider": "ollama",
            "match_model": os.environ.get("JOB_RADAR_MATCH_OLLAMA_MODEL", "gpt-oss:20b-cloud"),
            "ollama_base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        }

    @staticmethod
    def _write_run_artifacts(
        run_kind: str,
        profile: UserProfile,
        pipeline_result: PipelineResult,
        agent_result: AgentRunResult | None = None,
        raw_records: list[RawJobRecord] | None = None,
        extra_artifacts: dict[str, object] | None = None,
    ) -> Path:
        run_dir = TEST_TMP_DIR / f"{run_kind}_runs" / "latest"
        run_dir.mkdir(parents=True, exist_ok=True)
        for old_artifact in run_dir.glob("*.json"):
            old_artifact.unlink()
        IngestionService._write_json(run_dir / "profile.json", profile.model_dump())
        if agent_result is not None:
            IngestionService._write_json(run_dir / "agent_result.json", agent_result.model_dump())
            if agent_result.search_plan is not None:
                IngestionService._write_json(run_dir / "search_plan.json", agent_result.search_plan.model_dump())
            IngestionService._write_json(
                run_dir / "candidate_sources.json",
                [source.model_dump() for source in agent_result.candidate_sources],
            )
            IngestionService._write_json(
                run_dir / "selected_sources.json",
                [source.model_dump() for source in agent_result.selected_sources],
            )
            IngestionService._write_json(
                run_dir / "tool_events.json",
                [event.model_dump() for event in agent_result.tool_events],
            )
        IngestionService._write_json(
            run_dir / "raw_jobs.json",
            [record.model_dump() for record in raw_records or []],
        )
        IngestionService._write_json(
            run_dir / "extracted_raw_jobs.json",
            [record.model_dump() for record in raw_records or []],
        )
        IngestionService._write_json(run_dir / "pipeline_result.json", asdict(pipeline_result))
        for name, payload in (extra_artifacts or {}).items():
            IngestionService._write_json(run_dir / f"{name}.json", payload)
        return run_dir

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _search_plan_notices(agent_result: AgentRunResult) -> list[str]:
        if agent_result.search_plan_source == "codex_cli":
            return ["Search plan generated with local Codex CLI using the active user's own Codex login."]
        if agent_result.search_plan_error:
            return [f"Using deterministic search plan fallback: {agent_result.search_plan_error}"]
        return []
