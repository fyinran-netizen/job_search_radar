"""Generate a search plan from a profile without running the full pipeline."""

from __future__ import annotations

import argparse
import json
import sys

from pydantic import ValidationError

from job_radar.infra.llm.codex import CodexCliProvider
from job_radar.tools.web_search.search_strategy import AISearchPlanBuilder, AutoSearchPlanBuilder, SearchPlanBuilder
from job_radar.config import load_profile
from job_radar.profile.models import UserProfile
from job_radar.profile.completeness import ProfileCompletenessChecker
from job_radar.infra.paths import CONFIG_DIR


def main(argv: list[str] | None = None) -> int:
    """Run the search-strategy generator and print JSON."""

    parser = argparse.ArgumentParser(description="Generate a Job Radar SearchPlan.")
    parser.add_argument(
        "--provider",
        choices=["auto", "codex", "deterministic"],
        default="auto",
        help="Strategy provider to use. 'auto' uses Codex when available and falls back locally.",
    )
    parser.add_argument(
        "--profile-json",
        help="Inline UserProfile JSON. If omitted, config/profile.yaml or profile.example.yaml is used.",
    )
    parser.add_argument(
        "--profile-file",
        help="Path to a UserProfile JSON file. Takes precedence over --profile-json.",
    )
    parser.add_argument(
        "--show-meta",
        action="store_true",
        help="Print provider metadata next to the generated search plan.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print prompt and raw Codex CLI stdout/stderr when available.",
    )
    args = parser.parse_args(argv)

    try:
        profile = _load_profile_from_args(args.profile_json, args.profile_file)
    except (json.JSONDecodeError, ValidationError) as exc:
        print(f"Invalid profile input: {exc}", file=sys.stderr)
        return 2

    completeness = ProfileCompletenessChecker().check(profile)
    if not completeness.is_complete:
        print(
            json.dumps(
                {
                    "is_complete": False,
                    "missing_fields": completeness.missing_fields,
                    "questions": completeness.questions,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    codex_provider: CodexCliProvider | None = None
    if args.provider == "codex":
        codex_provider = CodexCliProvider()
        if not codex_provider.is_available():
            print("Codex CLI is not installed or not authenticated. Run `codex login` first.", file=sys.stderr)
            return 3
        builder = AISearchPlanBuilder(codex_provider)
    elif args.provider == "deterministic":
        builder = SearchPlanBuilder()
    else:
        builder = AutoSearchPlanBuilder()

    try:
        plan = builder.build(profile)
    except Exception as exc:
        print(f"Search strategy generation failed: {exc}", file=sys.stderr)
        if args.debug:
            _print_debug(builder, codex_provider)
        return 3

    output = plan.model_dump()
    if args.show_meta:
        output = {
            "provider": getattr(builder, "last_source", args.provider),
            "error": getattr(builder, "last_error", None),
            "search_plan": output,
        }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if args.debug:
        _print_debug(builder, codex_provider)
    return 0


def _load_profile_from_args(profile_json: str | None, profile_file: str | None) -> UserProfile:
    if profile_file:
        with open(profile_file, encoding="utf-8-sig") as file:
            return UserProfile.model_validate(json.load(file))
    if profile_json:
        return UserProfile.model_validate(json.loads(profile_json))
    profile, _, _ = load_profile(CONFIG_DIR)
    return profile


def _print_debug(builder: object, codex_provider: CodexCliProvider | None) -> None:
    provider = codex_provider
    if provider is None and isinstance(builder, AutoSearchPlanBuilder):
        provider = builder.codex_provider
    debug_info = getattr(provider, "last_debug_info", None) if provider else None
    if debug_info is None:
        print("\n--- DEBUG ---", file=sys.stderr)
        print("No Codex CLI call debug info is available.", file=sys.stderr)
        return
    print("\n--- DEBUG: Codex command ---", file=sys.stderr)
    print(" ".join(debug_info.command), file=sys.stderr)
    print("\n--- DEBUG: Prompt sent to Codex ---", file=sys.stderr)
    print(debug_info.prompt, file=sys.stderr)
    print("\n--- DEBUG: Codex stdout ---", file=sys.stderr)
    print(debug_info.stdout or "<empty>", file=sys.stderr)
    print("\n--- DEBUG: Codex stderr ---", file=sys.stderr)
    print(debug_info.stderr or "<empty>", file=sys.stderr)
    print(f"\n--- DEBUG: Codex return code ---\n{debug_info.returncode}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())


