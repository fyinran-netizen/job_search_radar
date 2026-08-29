"""Central logging setup for terminal and UTF-8 file observability."""

from __future__ import annotations

from contextvars import ContextVar
import logging
from pathlib import Path
from uuid import uuid4

from job_radar.infra.paths import DATA_DIR


_run_id: ContextVar[str] = ContextVar("job_radar_run_id", default="-")
_configured = False


class _RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id.get()
        return True


def new_run_id() -> str:
    """Return the identifier used to correlate one pipeline execution."""

    return uuid4().hex


def configure_logging(run_id: str | None = None, log_file: Path | None = None) -> str:
    """Configure process-wide terminal and UTF-8 file logging once."""

    global _configured
    current_run_id = run_id or _run_id.get()
    if current_run_id == "-":
        current_run_id = new_run_id()
    _run_id.set(current_run_id)

    if _configured:
        return current_run_id

    target = log_file or DATA_DIR / "job_radar.log"
    target.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s run_id=%(run_id)s - %(message)s"
    )
    run_filter = _RunIdFilter()
    stream_handler = logging.StreamHandler()
    file_handler = logging.FileHandler(target, encoding="utf-8")
    for handler in (stream_handler, file_handler):
        handler.setFormatter(formatter)
        handler.addFilter(run_filter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)
    _configured = True
    return current_run_id


def get_logger(name: str) -> logging.Logger:
    """Return a module logger using the centralized application handlers."""

    configure_logging()
    return logging.getLogger(name)


