"""Load prompts shipped with the runtime tools."""

from dataclasses import dataclass
from pathlib import Path

from job_radar.infra.paths import PROJECT_ROOT


RUNTIME_PROMPTS: dict[str, Path] = {
    "page-jd-classification": PROJECT_ROOT
    / "job_radar"
    / "tools"
    / "page_analysis"
    / "prompts"
    / "semantic_classification.md",
    "job-extraction": PROJECT_ROOT / "job_radar" / "tools" / "job_extraction" / "prompts" / "extraction.md",
    "job-understanding": PROJECT_ROOT
    / "job_radar"
    / "tools"
    / "job_understanding"
    / "prompts"
    / "understanding.md",
    "match-analysis": PROJECT_ROOT / "job_radar" / "tools" / "match_analysis" / "prompts" / "analysis.md",
}


@dataclass(frozen=True)
class RuntimePrompt:
    """A prompt loaded from the runtime tool assets."""

    name: str
    instructions: str


def load_runtime_prompt(name: str) -> RuntimePrompt:
    """Load a named runtime prompt."""
    prompt_path = RUNTIME_PROMPTS.get(name)
    if prompt_path is None or not prompt_path.exists():
        raise FileNotFoundError(f"Runtime prompt is not available: {name}")
    return RuntimePrompt(name=name, instructions=prompt_path.read_text(encoding="utf-8-sig"))
