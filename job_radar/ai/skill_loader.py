"""Load local Codex-style skill instructions."""

from dataclasses import dataclass
from pathlib import Path

from job_radar.utils.paths import PROJECT_ROOT


SKILLS_DIR = PROJECT_ROOT / ".agents" / "skills"


@dataclass(frozen=True)
class SkillDocument:
    """Loaded skill instructions and examples."""

    name: str
    instructions: str
    examples: str = ""


def load_skill(name: str, skills_dir: Path = SKILLS_DIR) -> SkillDocument:
    """Load `SKILL.md` and optional `examples.md` for one skill."""

    skill_dir = skills_dir / name
    skill_path = skill_dir / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill is not available: {name}")
    examples_path = skill_dir / "examples.md"
    examples = examples_path.read_text(encoding="utf-8") if examples_path.exists() else ""
    return SkillDocument(
        name=name,
        instructions=skill_path.read_text(encoding="utf-8"),
        examples=examples,
    )
