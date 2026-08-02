"""Codex CLI provider for local AI calls.

This provider is optional. It requires a working, authenticated `codex` command
on the user's machine. It is intentionally generic: business-specific prompts
belong in `job_radar.ai.tasks`, not here.
"""

import subprocess
from typing import Any

from job_radar.ai.providers.base import AIProvider
from job_radar.ai.structured_output import parse_json_output


class CodexCliError(RuntimeError):
    """Raised when Codex CLI execution fails."""


class CodexCliProvider(AIProvider):
    """Call `codex exec` and parse JSON output."""

    def __init__(self, command: str = "codex") -> None:
        self.command = command

    def generate_json(self, prompt: str, timeout_seconds: int = 180) -> Any:
        """Run Codex CLI and return parsed JSON-compatible data."""

        result = subprocess.run(
            [self.command, "exec", prompt],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise CodexCliError(message or f"Codex CLI exited with {result.returncode}")
        return parse_json_output(result.stdout)
