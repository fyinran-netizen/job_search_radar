"""Collector that adapts agent discovery output to the existing pipeline."""

from job_radar.agents.discovery import JobDiscoveryAgent
from job_radar.agents.models import AgentRunResult, ProfileCompletenessResult
from job_radar.collectors.base import BaseCollector
from job_radar.models.job import RawJobRecord
from job_radar.models.profile import UserProfile


class AgentDiscoveryCollector(BaseCollector):
    """Collect raw records by running a job discovery agent."""

    source_name = "Mock Agent Discovery"

    def __init__(self, agent: JobDiscoveryAgent, profile: UserProfile) -> None:
        self.agent = agent
        self.profile = profile
        self.last_agent_result = AgentRunResult(
            profile_check=ProfileCompletenessResult(is_complete=False)
        )

    def collect(self) -> list[RawJobRecord]:
        """Run agent discovery and return extracted raw job records."""

        records, result = self.agent.discover(self.profile)
        self.last_agent_result = result
        return records
