"""Shared filesystem paths."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "jobs.db"
DEMO_JOBS_PATH = DATA_DIR / "demo_jobs.csv"
