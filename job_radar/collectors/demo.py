"""Demo CSV collector used for the first project phase."""

from pathlib import Path
from typing import Any

import pandas as pd

from job_radar.collectors.base import BaseCollector
from job_radar.models.job import RawJobRecord
from job_radar.utils.paths import DEMO_JOBS_PATH


class DemoCollector(BaseCollector):
    """Read demonstration jobs from a local CSV file."""

    source_name = "Demo CSV"

    def __init__(self, csv_path: Path = DEMO_JOBS_PATH) -> None:
        self.csv_path = csv_path

    def collect(self) -> list[RawJobRecord]:
        """Load demo records from CSV."""

        frame = pd.read_csv(self.csv_path).where(pd.notnull, None)
        records: list[RawJobRecord] = []
        for row in frame.to_dict(orient="records"):
            records.append(RawJobRecord.model_validate(self._clean_row(row)))
        return records

    @staticmethod
    def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
        return {key: (None if value == "" or pd.isna(value) else value) for key, value in row.items()}
