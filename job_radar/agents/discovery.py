"""Agent workflow for discovering job records through scheduled tools."""

from job_radar.agents.models import AgentRunResult, CandidateSource
from job_radar.agents.profile import ProfileCompletenessChecker
from job_radar.agents.search_plan import SearchPlanBuilder
from job_radar.extractors.base import JobExtractor
from job_radar.models.job import RawJobRecord
from job_radar.models.profile import UserProfile
from job_radar.tools.base import ToolScheduler


class JobDiscoveryAgent:
    """Coordinate profile checks, search tools, page collection, and extraction."""

    def __init__(
        self,
        job_extractor: JobExtractor,
        tool_scheduler: ToolScheduler,
        profile_checker: ProfileCompletenessChecker | None = None,
        search_plan_builder: SearchPlanBuilder | None = None,
        min_relevance_score: int = 70,
    ) -> None:
        self.job_extractor = job_extractor
        self.tool_scheduler = tool_scheduler
        self.profile_checker = profile_checker or ProfileCompletenessChecker()
        self.search_plan_builder = search_plan_builder or SearchPlanBuilder()
        self.min_relevance_score = min_relevance_score

    def discover(self, profile: UserProfile) -> tuple[list[RawJobRecord], AgentRunResult]:
        """Run a local agent discovery pass and return raw job records."""

        self.tool_scheduler.reset()
        profile_check = self.profile_checker.check(profile)
        result = AgentRunResult(profile_check=profile_check)
        if not profile_check.is_complete:
            return [], result

        search_plan = self.search_plan_builder.build(profile)
        result.search_plan = search_plan

        candidate_sources = self.tool_scheduler.run("web_search", search_plan)
        if not isinstance(candidate_sources, list):
            raise TypeError("web_search must return a list of CandidateSource objects")
        result.candidate_sources = [
            source if isinstance(source, CandidateSource) else CandidateSource.model_validate(source)
            for source in candidate_sources
        ]
        result.selected_sources = self._select_sources(result.candidate_sources)

        records: list[RawJobRecord] = []
        for source in result.selected_sources:
            try:
                page = self.tool_scheduler.run("collect_page", source)
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
        result.tool_events = self.tool_scheduler.events
        return records, result

    def _select_sources(self, sources: list[CandidateSource]) -> list[CandidateSource]:
        return [
            source
            for source in sources
            if source.is_official and source.relevance_score >= self.min_relevance_score
        ]
