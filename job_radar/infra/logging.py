"""Central logging setup for terminal and UTF-8 file observability."""

from __future__ import annotations

from contextvars import ContextVar
import logging
from pathlib import Path
from uuid import uuid4

from job_radar.infra.paths import DATA_DIR


_run_id: ContextVar[str] = ContextVar("job_radar_run_id", default="-")
_configured = False
_HANDLER_MARKER = "_job_radar_handler"
_LOGGER_NAMESPACE = "job_radar"


class _RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id.get()
        return True


def new_run_id() -> str:
    """Return the identifier used to correlate one pipeline execution."""

    return uuid4().hex


def configure_logging(run_id: str | None = None, log_file: Path | None = None) -> str:
    """Configure process-wide terminal and UTF-8 file logging once.

    The marker-based cleanup also makes this idempotent across module reloads
    and test/app reinitialization, where the module-level flag is reset but
    old Job Radar handlers remain attached to the root logger.
    """

    global _configured
    current_run_id = run_id or _run_id.get()
    if current_run_id == "-":
        current_run_id = new_run_id()
    _run_id.set(current_run_id)

    root = logging.getLogger()
    namespace = logging.getLogger(_LOGGER_NAMESPACE)
    owned_handlers = [
        handler for handler in [*root.handlers, *namespace.handlers]
        if getattr(handler, _HANDLER_MARKER, False)
    ]
    if _configured and owned_handlers:
        return current_run_id

    for handler in owned_handlers:
        root.removeHandler(handler)
        namespace.removeHandler(handler)
        handler.close()

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

    # Keep application events out of handlers installed by Streamlit, pytest,
    # or another host application.  Those handlers were the second delivery
    # path for the same event (often before the run_id context was set).
    namespace.setLevel(logging.INFO)
    namespace.propagate = False
    for handler in (stream_handler, file_handler):
        setattr(handler, _HANDLER_MARKER, True)
        namespace.addHandler(handler)
    _configured = True
    return current_run_id


def get_logger(name: str) -> logging.Logger:
    """Return a module logger using the centralized application handlers."""

    configure_logging()
    return logging.getLogger(name)


