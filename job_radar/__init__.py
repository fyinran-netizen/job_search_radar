"""Job Radar package."""

import os
from pathlib import Path

from job_radar.utils.runtime_paths import configure_local_runtime_paths


def _load_project_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name:
            os.environ.setdefault(name, value)


_load_project_env()
configure_local_runtime_paths()

__version__ = "0.1.0"
