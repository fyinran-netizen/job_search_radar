"""Read demo jobs from CSV as a deterministic function tool."""

from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel

from job_radar.models.job import RawJobRecord
from job_radar.tools.base import BaseTool
from job_radar.utils.paths import DEMO_JOBS_PATH


class DemoCsvTool(BaseTool):
    """Read demo jobs from a CSV file."""

    name = "read_demo_csv"

    def __init__(self, csv_path: Path = DEMO_JOBS_PATH) -> None:
        self.csv_path = csv_path

    def run(self, payload: BaseModel | dict[str, Any] | None = None) -> list[RawJobRecord]:
        """Read CSV rows and convert them into raw job records."""

        return self.collect()

    def collect(self) -> list[RawJobRecord]:
        """Return demo CSV rows as raw job records."""

        frame = pd.read_csv(self.csv_path)
        records: list[RawJobRecord] = []
        for row in frame.to_dict(orient="records"):
            data = {
                key: (None if pd.isna(value) else value)
                for key, value in row.items()
            }
            if isinstance(data.get("graduation_years"), str):
                data["graduation_years"] = [
                    item.strip()
                    for item in data["graduation_years"].split(";")
                    if item.strip()
                ]
            records.append(RawJobRecord.model_validate(data))
        return records
