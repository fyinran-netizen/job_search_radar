"""Runtime path defaults for local-first execution."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from job_radar.infra.paths import PROJECT_ROOT


LOCAL_TMP_DIR = Path(os.environ.get("JOB_RADAR_LOCAL_TMP_DIR", PROJECT_ROOT / ".local_tmp")).resolve()
TEMP_DIR = LOCAL_TMP_DIR / "temp"
PYCACHE_DIR = LOCAL_TMP_DIR / "pycache"
UV_CACHE_DIR = LOCAL_TMP_DIR / "uv-cache"


def configure_local_runtime_paths() -> None:
    """Keep Python runtime temp/cache artifacts inside the project by default."""

    if os.environ.get("JOB_RADAR_DISABLE_LOCAL_RUNTIME_PATHS"):
        return

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    PYCACHE_DIR.mkdir(parents=True, exist_ok=True)
    UV_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("TMP", str(TEMP_DIR))
    os.environ.setdefault("TEMP", str(TEMP_DIR))
    os.environ.setdefault("TMPDIR", str(TEMP_DIR))
    os.environ.setdefault("UV_CACHE_DIR", str(UV_CACHE_DIR))

    tempfile.tempdir = str(TEMP_DIR)
    if sys.pycache_prefix is None:
        sys.pycache_prefix = str(PYCACHE_DIR)


