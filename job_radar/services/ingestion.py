"""Application orchestration for the Job Radar real search pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from job_radar.agent.models import AgentLimits, AgentRunResult

from job_radar.config import load_runtime_settings

from job_radar.infra.llm.ollama import OllamaProvider
from job_radar.infra.logging import configure_logging, get_logger, new_run_id
from job_radar.infra.paths import DEFAULT_DB_PATH
from job_radar.infra.storage.repository import JobRepository

from job_radar.profile.completeness import ProfileCompletenessChecker
from job_radar.profile.models import UserProfile

from job_radar.tools.executor import ToolExecutor

from job_radar.tools.job_extraction.models import JobRecord

from job_radar.tools.job_extraction.tool import (
    JobExtractionInput,
    JobExtractionOutput,
)

from job_radar.tools.job_understanding.tool import (
    JobUnderstandingToolInput,
    JobUnderstandingToolOutput,
)

from job_radar.tools.match_analysis.tool import (
    MatchAnalysisToolInput,
    MatchAnalysisToolOutput,
)

from job_radar.tools.page_acquisition.models import PageDocument

from job_radar.tools.page_analysis.models import (
    PendingFollowup,
)

from job_radar.tools.page_acquisition.technical_triage import (
    RejectedPage,
)

from job_radar.tools.page_analysis.tool import (
    PageAnalysisInput,
    PageAnalysisOutput,
)

from job_radar.tools.registry import (
    create_real_search_tool_executor,
)

from job_radar.tools.web_search.models import CandidateSource

from job_radar.tools.search_plan import SearchPlanBuilder
from job_radar.tools.web_search.source_selection import select_sources


logger = get_logger(__name__)


@dataclass
class PipelineResult:
    """Summary of one completed pipeline run."""

    collected_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    duplicate_count: int = 0

    inserted_count: int = 0
    updated_count: int = 0
    failed_count: int = 0

    errors: list[dict[str, Any]] = field(
        default_factory=list
    )


class IngestionService:
    """
    Application service for the current real Job Radar pipeline.

    Current flow:

        profile
          ↓
        web_search
          ↓
        page_acquisition
          ↓
        analyze_page
          ↓
        job_extraction
          ↓
        job_understanding
          ↓
        match_analysis
          ↓
        persistence

    The internal implementation details of Job Extraction
    (validation, normalization, deduplication and quality checks)
    stay inside the Job Extraction capability.
    """

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        enable_codex_ai: bool = False,
    ) -> None:
        self.db_path = db_path
        self.enable_codex_ai = enable_codex_ai

    def run_real_search_pipeline(
        self,
        profile: UserProfile,
    ) -> tuple[
        PipelineResult,
        list[str],
        AgentRunResult,
    ]:
        """
        Run the current real end-to-end search pipeline.
        """

        notices: list[str] = []
        run_id = configure_logging(new_run_id())
        logger.info("pipeline_start kind=real run_id=%s", run_id)

        limits = AgentLimits()

        profile_check = (
            ProfileCompletenessChecker()
            .check(profile)
        )

        agent_result = AgentRunResult(
            run_id=run_id,
            profile_check=profile_check
        )

        metadata = self._real_run_metadata()

        # -----------------------------------------------------
        # Profile validation
        # -----------------------------------------------------

        if not profile_check.is_complete:
            pipeline_result = PipelineResult()
            logger.warning("pipeline_stopped reason=incomplete_profile")

            return (
                pipeline_result,
                notices,
                agent_result,
            )

        # -----------------------------------------------------
        # Run notices
        # -----------------------------------------------------

        notices.append(
            "Using Tavily-backed web search "
            "and HTTP page acquisition."
        )

        notices.append(
            f"Using Page Analysis with {metadata['analyze_page_provider']} "
            f"semantic classification "
            f"({metadata['analyze_page_model']}), "
            "Ollama job extraction "
            f"({metadata['extraction_model']}), "
            "job understanding "
            f"({metadata['understanding_model']}), "
            "and match analysis "
            f"({metadata['match_model']})."
        )

        # -----------------------------------------------------
        # Search plan
        # -----------------------------------------------------

        search_plan_builder = SearchPlanBuilder()

        search_plan = (
            search_plan_builder.build(
                profile
            )
        )

        agent_result.search_plan = search_plan

        agent_result.search_plan_source = (
            search_plan_builder.last_source
        )

        agent_result.search_plan_error = (
            search_plan_builder.last_error
        )

        # -----------------------------------------------------
        # Tool executor
        # -----------------------------------------------------

        executor = (
            self._create_real_tool_executor(
                metadata
            )
        )

        # -----------------------------------------------------
        # Web Search
        # -----------------------------------------------------

        candidate_sources = executor.run(
            "web_search",
            search_plan,
        )

        if not isinstance(
            candidate_sources,
            list,
        ):
            raise TypeError(
                "web_search must return a list "
                "of CandidateSource objects"
            )

        agent_result.candidate_sources = [
            (
                source
                if isinstance(
                    source,
                    CandidateSource,
                )
                else CandidateSource.model_validate(
                    source
                )
            )
            for source in candidate_sources
        ]

        agent_result.selected_sources = (
            select_sources(
                agent_result.candidate_sources,
                min_relevance_score=limits.min_relevance_score,
                max_sources=limits.max_sources_per_round,
            )
        )

        # -----------------------------------------------------
        # Page Acquisition
        # -----------------------------------------------------

        (
            pages,
            acquisition_pending_followups,
            acquisition_rejected_pages,
        ) = self._collect_real_pages(
            executor,
            agent_result.selected_sources,
        )

        # -----------------------------------------------------
        # Page Analysis
        # -----------------------------------------------------

        analyze_page_output = executor.run(
            "analyze_page",
            PageAnalysisInput(
                pages=pages,
                search_plan=search_plan,
            ),
        )

        if not isinstance(
            analyze_page_output,
            PageAnalysisOutput,
        ):
            raise TypeError(
                "analyze_page must return "
                "PageAnalysisOutput"
            )

        all_pending_followups = [
            *acquisition_pending_followups,
            *analyze_page_output.pending_followups,
        ]

        logger.info(
            "analyze_page acquisition_pages=%s acquisition_pending=%s acquisition_rejected=%s",
            len(pages),
            len(acquisition_pending_followups),
            len(acquisition_rejected_pages),
        )

        # -----------------------------------------------------
        # Job Extraction
        # -----------------------------------------------------

        job_extraction_output = executor.run(
            "job_extraction",
            JobExtractionInput(
                pages=(
                    analyze_page_output
                    .accepted_pages
                ),
            ),
        )

        if not isinstance(
            job_extraction_output,
            JobExtractionOutput,
        ):
            raise TypeError(
                "job_extraction must return "
                "JobExtractionOutput"
            )

        raw_records = job_extraction_output.raw_records

        prepared_records = (
            job_extraction_output.prepared_records
        )

        # Job Extraction can discover that a page
        # looked like a JD but still requires
        # another page/detail-page lookup.
        all_pending_followups.extend(
            job_extraction_output.pending_followups
        )

        # -----------------------------------------------------
        # Job Understanding
        # -----------------------------------------------------

        job_understanding_output = executor.run(
            "job_understanding",
            JobUnderstandingToolInput(
                jobs=prepared_records,
                profile=profile,
            ),
        )

        if not isinstance(
            job_understanding_output,
            JobUnderstandingToolOutput,
        ):
            raise TypeError(
                "job_understanding must return "
                "JobUnderstandingToolOutput"
            )

        # -----------------------------------------------------
        # Match Analysis
        # -----------------------------------------------------

        match_analysis_output = executor.run(
            "match_analysis",
            MatchAnalysisToolInput(
                records=(
                    job_understanding_output
                    .records
                ),
                profile=profile,
            ),
        )

        if not isinstance(
            match_analysis_output,
            MatchAnalysisToolOutput,
        ):
            raise TypeError(
                "match_analysis must return "
                "MatchAnalysisToolOutput"
            )

        final_jobs = (
            self._apply_match_assessments(
                prepared_records,
                match_analysis_output,
            )
        )

        # -----------------------------------------------------
        # Persistence
        # -----------------------------------------------------

        persistence_result = (
            JobRepository(
                self.db_path
            ).upsert_jobs(
                final_jobs
            )
        )
        logger.info(
            "persistence saved inserted=%s updated=%s failed=%s",
            persistence_result.inserted_count,
            persistence_result.updated_count,
            persistence_result.failed_count,
        )

        extraction_report = (
            job_extraction_output.report
        )

        extraction_errors = (
            extraction_report.get(
                "errors",
                [],
            )
        )

        if not isinstance(
            extraction_errors,
            list,
        ):
            extraction_errors = []

        pipeline_result = PipelineResult(
            collected_count=len(
                raw_records
            ),
            valid_count=int(
                extraction_report.get(
                    "valid_record_count",
                    len(prepared_records),
                )
            ),
            invalid_count=int(
                extraction_report.get(
                    "invalid_record_count",
                    0,
                )
            ),
            duplicate_count=int(
                extraction_report.get(
                    "duplicate_count",
                    0,
                )
            ),
            inserted_count=(
                persistence_result.inserted_count
            ),
            updated_count=(
                persistence_result.updated_count
            ),
            failed_count=(
                persistence_result.failed_count
            ),
            errors=[
                *extraction_errors,
                *persistence_result.errors,
            ],
        )

        # -----------------------------------------------------
        # Agent run result
        # -----------------------------------------------------

        agent_result.acquired_pages_count = (
            len(pages)
        )

        agent_result.extracted_count = (
            len(raw_records)
        )

        agent_result.tool_events = (
            executor.events
        )

        notices.extend(
            self._search_plan_notices(
                agent_result
            )
        )

        logger.info(
            "pipeline_complete kind=real collected=%s extracted=%s persisted=%s",
            len(pages),
            len(raw_records),
            len(final_jobs),
        )

        return (
            pipeline_result,
            notices,
            agent_result,
        )

    # =========================================================
    # Page Acquisition
    # =========================================================

    def _collect_real_pages(
        self,
        executor: ToolExecutor,
        sources: list[CandidateSource],
    ) -> tuple[
        list[PageDocument],
        list[PendingFollowup],
        list[RejectedPage],
    ]:
        """
        Collect candidate pages while explicitly preserving
        fetch failures.
        """

        pages: list[PageDocument] = []

        pending_followups: list[
            PendingFollowup
        ] = []

        rejected_pages: list[
            RejectedPage
        ] = []

        for source in sources:
            try:
                page = executor.run(
                    "acquire_page",
                    source,
                )

            except Exception as exc:
                logger.warning(
                    "page_acquisition failed url=%s pending=%s reason=%s",
                    source.url,
                    self._is_pending_fetch_error(exc),
                    exc,
                )
                metadata = (
                    self._source_error_metadata(
                        source
                    )
                )

                if self._is_pending_fetch_error(
                    exc
                ):
                    pending_followups.append(
                        PendingFollowup(
                            url=source.url,
                            final_url=None,
                            title=source.title,
                            source_name=(
                                source.source_name
                            ),
                            company_name=(
                                source.company_name
                            ),
                            company_type=(
                                source.company_type
                            ),
                            is_official=(
                                source.is_official
                            ),
                            pending_kind=(
                                "anti_bot_or_rate_limited"
                            ),
                            reasons=[
                                f"fetch_error: {exc}"
                            ],
                            evidence={
                                "collection_metadata": (
                                    metadata
                                )
                            },
                            suggested_next_action=(
                                "retry_with_browser_or_rendered_collection"
                            ),
                            priority=65,
                            links=[],
                            stage="collection",
                        )
                    )

                else:
                    rejected_pages.append(
                        RejectedPage(
                            url=source.url,
                            source_name=(
                                source.source_name
                            ),
                            title=source.title,
                            reasons=[
                                f"fetch_error: {exc}"
                            ],
                            metadata=metadata,
                        )
                    )

                continue

            if not isinstance(
                page,
                PageDocument,
            ):
                raise TypeError(
                    "acquire_page must return "
                    "PageDocument"
                )

            pages.append(page)

        return (
            pages,
            pending_followups,
            rejected_pages,
        )

    # =========================================================
    # Tool Executor
    # =========================================================

    def _create_real_tool_executor(
        self,
        metadata: dict[str, object],
    ) -> ToolExecutor:
        """
        Create the tool executor used by the current real pipeline.
        """

        extraction_provider = str(
            metadata[
                "extraction_provider"
            ]
        )

        classification_provider = str(
            metadata[
                "analyze_page_provider"
            ]
        )

        understanding_provider = str(
            metadata[
                "understanding_provider"
            ]
        )

        match_provider = str(
            metadata[
                "match_provider"
            ]
        )

        if classification_provider != "ollama":
            raise RuntimeError(
                "JOB_RADAR_PAGE_ANALYSIS_PROVIDER must be ollama: "
                f"got {classification_provider!r}."
            )

        if extraction_provider != "ollama":
            raise RuntimeError(
                "Real search supports "
                "JOB_RADAR_EXTRACTION_PROVIDER=ollama, "
                f"got {extraction_provider!r}."
            )

        if understanding_provider != "ollama":
            raise RuntimeError(
                "Real search supports "
                "JOB_RADAR_UNDERSTANDING_PROVIDER=ollama, "
                f"got {understanding_provider!r}."
            )

        if match_provider != "ollama":
            raise RuntimeError(
                "Real search supports "
                "JOB_RADAR_MATCH_PROVIDER=ollama, "
                f"got {match_provider!r}."
            )

        classification_ollama = OllamaProvider(
            model=str(metadata["analyze_page_model"]),
            base_url=str(metadata["ollama_base_url"]),
        )

        extraction_ollama = OllamaProvider(
            model=str(
                metadata[
                    "extraction_model"
                ]
            ),
            base_url=str(
                metadata[
                    "ollama_base_url"
                ]
            ),
        )

        understanding_ollama = OllamaProvider(
            model=str(
                metadata[
                    "understanding_model"
                ]
            ),
            base_url=str(
                metadata[
                    "ollama_base_url"
                ]
            ),
        )

        match_ollama = OllamaProvider(
            model=str(
                metadata[
                    "match_model"
                ]
            ),
            base_url=str(
                metadata[
                    "ollama_base_url"
                ]
            ),
        )

        ollama_providers = [
            classification_ollama,
            extraction_ollama,
            understanding_ollama,
            match_ollama,
        ]

        if not all(
            provider.is_available()
            for provider in ollama_providers
        ):
            raise RuntimeError(
                "Ollama server is not reachable at "
                f"{metadata['ollama_base_url']}."
            )

        return create_real_search_tool_executor(
            analyze_page_provider=(
                classification_ollama
            ),
            job_extraction_provider=(
                extraction_ollama
            ),
            job_understanding_provider=(
                understanding_ollama
            ),
            match_analysis_provider=(
                match_ollama
            ),
        )

    # =========================================================
    # Match result application
    # =========================================================

    @staticmethod
    def _apply_match_assessments(
        jobs: list[JobRecord],
        match_output: MatchAnalysisToolOutput,
    ) -> list[JobRecord]:
        """
        Apply semantic match assessments back onto JobRecord objects.
        """

        assessments_by_key = {
            str(
                item.get(
                    "deduplication_key"
                )
            ): item.get(
                "assessment"
            )
            for item
            in match_output.assessments
            if (
                item.get(
                    "deduplication_key"
                )
                and isinstance(
                    item.get(
                        "assessment"
                    ),
                    dict,
                )
            )
        }

        final_jobs: list[
            JobRecord
        ] = []

        for job in jobs:
            assessment = (
                assessments_by_key.get(
                    job.deduplication_key
                )
            )

            if assessment:
                job.match_score = int(
                    assessment.get(
                        "match_score",
                        0,
                    )
                )

                job.match_reasons = [
                    str(item)
                    for item in (
                        assessment.get(
                            "match_reasons",
                            [],
                        )
                    )
                ]

                job.missing_requirements = [
                    str(item)
                    for item in (
                        assessment.get(
                            "missing_requirements",
                            [],
                        )
                    )
                ]

                if not job.match_reasons:
                    recommendation = (
                        assessment.get(
                            "recommendation"
                        )
                    )

                    confidence = (
                        assessment.get(
                            "confidence"
                        )
                    )

                    job.match_reasons = [
                        "Semantic match completed: "
                        f"recommendation={recommendation}, "
                        f"confidence={confidence}"
                    ]

            else:
                job.match_score = 0

                job.match_reasons = [
                    "Semantic match was not "
                    "completed for this job."
                ]

                job.missing_requirements = []

            final_jobs.append(job)

        return final_jobs

    # =========================================================
    # Collection helpers
    # =========================================================

    @staticmethod
    def _source_error_metadata(
        source: CandidateSource,
    ) -> dict[str, object]:
        """Build deterministic metadata for collection failures."""

        return {
            "company_name": (
                source.company_name
            ),
            "company_type": (
                source.company_type
            ),
            "location": (
                source.location
            ),
            "is_official": (
                source.is_official
            ),
            "relevance_score": (
                source.relevance_score
            ),
            "reason": (
                source.reason
            ),
        }

    @staticmethod
    def _is_pending_fetch_error(
        exc: Exception,
    ) -> bool:
        """
        Return whether a collection failure may be recoverable
        through another collection strategy.
        """

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

    # =========================================================
    # Runtime configuration
    # =========================================================

    @staticmethod
    def _real_run_metadata() -> dict[str, object]:
        """Return runtime provider and model configuration."""

        settings = (
            load_runtime_settings()
        )

        return {
            "web_search_provider": "tavily",

            "page_acquisition_provider": (
                "http"
            ),

            "analyze_page_provider": (
                settings.analyze_page.provider
            ),

            "analyze_page_model": (
                settings.analyze_page.model
            ),

            "extraction_provider": (
                settings.extraction.provider
            ),

            "extraction_model": (
                settings.extraction.model
            ),

            "understanding_provider": (
                settings.understanding.provider
            ),

            "understanding_model": (
                settings.understanding.model
            ),

            "match_provider": (
                settings.match.provider
            ),

            "match_model": (
                settings.match.model
            ),

            "ollama_base_url": (
                settings.ollama_base_url
            ),
        }

    # =========================================================
    # Notices
    # =========================================================

    @staticmethod
    def _search_plan_notices(
        agent_result: AgentRunResult,
    ) -> list[str]:
        """Build user-facing search-plan notices."""

        if (
            agent_result.search_plan_source
            == "codex_cli"
        ):
            return [
                "Search plan generated with local Codex CLI "
                "using the active user's own Codex login."
            ]

        if agent_result.search_plan_error:
            return [
                "Using deterministic search plan fallback: "
                f"{agent_result.search_plan_error}"
            ]

        return []
