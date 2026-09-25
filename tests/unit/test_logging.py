import logging

from job_radar.infra.logging import configure_logging


def test_logging_configuration_does_not_duplicate_job_radar_handlers(tmp_path):
    configure_logging("logging-test", log_file=tmp_path / "job-radar.log")
    root = logging.getLogger("job_radar")
    owned = [
        handler for handler in root.handlers
        if getattr(handler, "_job_radar_handler", False)
    ]
    assert len(owned) == 2

    configure_logging("logging-test-again", log_file=tmp_path / "job-radar-2.log")
    owned_again = [
        handler for handler in root.handlers
        if getattr(handler, "_job_radar_handler", False)
    ]
    assert len(owned_again) == 2
