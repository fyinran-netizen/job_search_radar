from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from job_radar.utils.paths import PROJECT_ROOT


@pytest.fixture
def temp_db_path() -> Iterator[Path]:
    base = PROJECT_ROOT / ".test_tmp"
    base.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=base) as directory:
        yield Path(directory) / "jobs.db"
