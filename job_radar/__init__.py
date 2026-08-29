"""Job Radar package."""

from job_radar.config import load_project_env
from job_radar.infra.runtime import configure_local_runtime_paths

load_project_env()
configure_local_runtime_paths()

__version__ = "0.1.0"
