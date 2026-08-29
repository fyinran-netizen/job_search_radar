"""Load static Agent test data without turning it into pytest lifecycle state."""

import json
from pathlib import Path
from typing import Any


FIXTURES_DIR = Path(__file__).parent


def load_json(relative_path: str) -> Any:
    """Load one repository-owned JSON fixture."""

    return json.loads((FIXTURES_DIR / relative_path).read_text(encoding="utf-8"))
