"""Best-effort startup hook for local runtime paths."""

try:
    from job_radar.utils.runtime_paths import configure_local_runtime_paths
except Exception:
    configure_local_runtime_paths = None


if configure_local_runtime_paths is not None:
    configure_local_runtime_paths()
