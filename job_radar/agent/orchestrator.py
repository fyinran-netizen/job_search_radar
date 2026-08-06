"""Agent workflow for discovering job records through tools."""

from job_radar.agent.guardrails import select_candidate_sources
from job_radar.ai.tasks.search_strategy import SearchPlanBuilder, SearchPlanBuilderProtocol
from job_radar.extractors.base import JobExtractor
from job_radar.models.decisions import AgentRunResult
from job_radar.models.job import RawJobRecord
from job_radar.models.profile import UserProfile
from job_radar.models.run import AgentLimits
from job_radar.models.search import CandidateSource
from job_radar.profile.completeness import ProfileCompletenessChecker
from job_radar.tools.executor import ToolExecutor


class JobDiscoveryAgent:
    """Coordinate profile checks, search tools, page collection, and extraction."""

    def __init__(
        self,
        job_extractor: JobExtractor,
        tool_executor: ToolExecutor,
        profile_checker: ProfileCompletenessChecker | None = None,
        search_plan_builder: SearchPlanBuilderProtocol | None = None,
        limits: AgentLimits | None = None,
    ) -> None:
        self.job_extractor = job_extractor
        self.tool_executor = tool_executor
        self.profile_checker = profile_checker or ProfileCompletenessChecker()
        self.search_plan_builder = search_plan_builder or SearchPlanBuilder()
        self.limits = limits or AgentLimits()

    def discover(self, profile: UserProfile) -> tuple[list[RawJobRecord], AgentRunResult]:
        """Run a local agent discovery pass and return raw job records."""

        self.tool_executor.reset()
        profile_check = self.profile_checker.check(profile)
        result = AgentRunResult(profile_check=profile_check)
        if not profile_check.is_complete:
            return [], result

        search_plan = self.search_plan_builder.build(profile)
        result.search_plan = search_plan
        result.search_plan_source = self.search_plan_builder.last_source
        result.search_plan_error = self.search_plan_builder.last_error

        candidate_sources = self.tool_executor.run("web_search", search_plan)
        if not isinstance(candidate_sources, list):
            raise TypeError("web_search must return a list of CandidateSource objects")
        result.candidate_sources = [
            source if isinstance(source, CandidateSource) else CandidateSource.model_validate(source)
            for source in candidate_sources
        ]
        result.selected_sources = select_candidate_sources(
            result.candidate_sources,
            min_relevance_score=self.limits.min_relevance_score,
        )[: self.limits.max_sources_per_round]

        records: list[RawJobRecord] = []
        for source in result.selected_sources:
            try:
                page = self.tool_executor.run("collect_page", source)
                page_records = self.job_extractor.extract(page)
            except Exception as exc:
                result.errors.append(
                    {
                        "source_url": source.url,
                        "source_name": source.source_name,
                        "reason": str(exc),
                    }
                )
                continue
            records.extend(page_records)

        result.collected_pages_count = len(result.selected_sources)
        result.extracted_count = len(records)
        result.tool_events = self.tool_executor.events
        return records, result
