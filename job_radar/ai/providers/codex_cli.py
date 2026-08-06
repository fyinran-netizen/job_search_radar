"""Codex CLI provider for local AI calls.

This provider is optional. It requires a working, authenticated `codex` command
on the user's machine. It is intentionally generic: business-specific prompts
belong in `job_radar.ai.tasks`, not here.
"""

import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from job_radar.ai.providers.base import AIProvider
from job_radar.ai.structured_output import StructuredOutputError, parse_json_output


class CodexCliError(RuntimeError):
    """Raised when Codex CLI execution fails."""


@dataclass
class CodexCliDebugInfo:
    """Captured details from the latest Codex CLI call."""

    command: list[str]
    prompt: str
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None


class CodexCliProvider(AIProvider):
    """Call `codex exec` and parse JSON output."""

    def __init__(self, command: str = "codex") -> None:
        self.command = command
        self.last_debug_info: CodexCliDebugInfo | None = None

    def _command_prefix(self) -> list[str]:
        """Resolve the configured command to an executable subprocess prefix."""

        resolved = shutil.which(self.command)
        if resolved is None:
            raise CodexCliError(f"Codex CLI command was not found: {self.command}")
        return [resolved]

    def is_available(self, timeout_seconds: int = 10) -> bool:
        """Return whether Codex CLI is installed and currently authenticated."""

        try:
            result = subprocess.run(
                [*self._command_prefix(), "login", "status"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def generate_json(self, prompt: str, timeout_seconds: int = 180) -> Any:
        """Run Codex CLI and return parsed JSON-compatible data."""

        command = [*self._command_prefix(), "exec"]
        self.last_debug_info = CodexCliDebugInfo(command=command, prompt=prompt)
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        self.last_debug_info.stdout = result.stdout
        self.last_debug_info.stderr = result.stderr
        self.last_debug_info.returncode = result.returncode
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise CodexCliError(message or f"Codex CLI exited with {result.returncode}")
        try:
            return parse_json_output(result.stdout)
        except StructuredOutputError as exc:
            raise CodexCliError(str(exc)) from exc
