"""Load runtime prompts and development skill instructions."""

from dataclasses import dataclass
from pathlib import Path

from job_radar.infra.paths import PROJECT_ROOT


DEVELOPMENT_SKILLS_DIR = PROJECT_ROOT / ".agents" / "skills"
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
class SkillDocument:
    """Loaded runtime prompt plus optional development examples."""

    name: str
    instructions: str
    examples: str = ""


def load_skill(name: str, skills_dir: Path = DEVELOPMENT_SKILLS_DIR) -> SkillDocument:
    """Load a runtime prompt by name, falling back to the development skill copy."""

    prompt_path = RUNTIME_PROMPTS.get(name)
    if prompt_path is not None and prompt_path.exists():
        examples_path = skills_dir / name / "examples.md"
        examples = examples_path.read_text(encoding="utf-8-sig") if examples_path.exists() else ""
        return SkillDocument(
            name=name,
            instructions=prompt_path.read_text(encoding="utf-8-sig"),
            examples=examples,
        )

    skill_dir = skills_dir / name
    skill_path = skill_dir / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill or runtime prompt is not available: {name}")
    examples_path = skill_dir / "examples.md"
    examples = examples_path.read_text(encoding="utf-8-sig") if examples_path.exists() else ""
    return SkillDocument(
        name=name,
        instructions=skill_path.read_text(encoding="utf-8-sig"),
        examples=examples,
    )
