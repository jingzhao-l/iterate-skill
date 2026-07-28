"""iterate CLI entry point.

Provides subcommands for onboarding and personalization management:
    iterate onboard     — Run interactive CLI onboarding wizard (multi-path)
    iterate personalize — Direct personalization configuration (mid-project)
    iterate refresh     — Incremental refresh of ITERATE.md (preserve user sections)
    iterate reonboard   — Full re-onboarding (backup old files, run wizard)
    iterate status      — Show onboarding status and drift detection
    iterate --version   — Print version
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from iterate_cli import __version__
from iterate_cli.generator import (
    USER_END_MARKER,
    USER_START_MARKER,
    write_onboarding_outputs,
)
from iterate_cli.refresh import (
    check_onboarding_drift,
    full_reonboard,
    incremental_refresh,
    is_onboarding_complete,
    load_onboarding_config,
)
from iterate_cli.wizard import run_wizard


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code: 0 for success, 1 for error/cancel.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    project_root = Path(args.project).resolve()

    if not project_root.is_dir():
        print(f"Error: project directory not found: {project_root}", file=sys.stderr)
        return 1

    if args.command == "onboard":
        return _cmd_onboard(project_root)
    elif args.command == "personalize":
        return _cmd_personalize(project_root)
    elif args.command == "refresh":
        return _cmd_refresh(project_root)
    elif args.command == "reonboard":
        return _cmd_reonboard(project_root)
    elif args.command == "status":
        return _cmd_status(project_root)
    else:
        parser.print_help()
        return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser."""
    parser = argparse.ArgumentParser(
        prog="iterate",
        description="Iterate skill onboarding and project knowledge management.",
    )
    parser.add_argument("--version", action="version", version=f"iterate {__version__}")
    parser.add_argument(
        "-p", "--project",
        default=".",
        help="Project root directory (default: current directory).",
    )

    subparsers = parser.add_subparsers(dest="command")

    # Shared project argument for subcommands (allows -p after subcommand).
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "-p", "--project",
        default=".",
        help="Project root directory (default: current directory).",
    )

    subparsers.add_parser(
        "onboard",
        parents=[parent],
        help="Run interactive CLI onboarding wizard (multi-path).",
        description="Run the interactive onboarding wizard. First-time projects get "
        "basic onboarding + personalization offer; existing projects get "
        "config update + personalization offer.",
    )
    subparsers.add_parser(
        "personalize",
        parents=[parent],
        help="Direct personalization configuration (mid-project).",
        description="Skip basic onboarding and go directly to the 9-step "
        "personalization wizard. Ideal for adding constraints mid-project.",
    )
    subparsers.add_parser(
        "refresh",
        parents=[parent],
        help="Incrementally refresh ITERATE.md (preserve user sections).",
        description="Re-scan the project and update AI-maintained sections of ITERATE.md "
        "while preserving user-owned sections. Also updates manifest fingerprints.",
    )
    subparsers.add_parser(
        "reonboard",
        parents=[parent],
        help="Full re-onboarding (backup old files, run wizard).",
        description="Back up existing ITERATE.md and iterate.config.yaml, then run the "
        "full onboarding wizard from scratch.",
    )
    subparsers.add_parser(
        "status",
        parents=[parent],
        help="Show onboarding status and drift detection.",
        description="Check whether onboarding is complete and whether the project's "
        "tech stack has drifted since the last onboarding.",
    )

    return parser


def _cmd_onboard(project_root: Path) -> int:
    """Handle the 'onboard' subcommand with multi-path branching."""
    data = run_wizard(project_root)
    if data is None:
        return 1

    iterate_md, config_yaml = write_onboarding_outputs(data, project_root)
    print()
    print(f"✅ Onboarding complete!")
    print(f"   Written: {iterate_md}")
    print(f"   Written: {config_yaml}")
    if data.personalization is not None:
        print(f"   Personalization: applied")
    print()
    print("You can now use /iterate in your AI coding tool.")
    return 0


def _cmd_personalize(project_root: Path) -> int:
    """Handle the 'personalize' subcommand — direct personalization configuration."""
    from iterate_cli.personalize import (
        load_personalization_from_config,
        run_personalize_wizard,
        save_personalization_to_config,
    )

    # Personalization requires existing onboarding (ITERATE.md + config).
    if not is_onboarding_complete(project_root):
        print("Onboarding not yet completed. Run 'iterate onboard' first.")
        return 1

    config_path = project_root / "iterate.config.yaml"
    if not config_path.is_file():
        print("iterate.config.yaml not found. Run 'iterate onboard' first.")
        return 1

    # Load existing personalization for editing.
    existing_config = load_onboarding_config(project_root) or {}
    existing_personalization = load_personalization_from_config(existing_config)

    personalization = run_personalize_wizard(
        project_root,
        existing=existing_personalization,
    )
    if personalization is None:
        return 1

    # Save structured fields to config.yaml.
    config_path = save_personalization_to_config(project_root, personalization)

    # Update ITERATE.md user-owned section with notes/conventions.
    _update_iterate_md_user_section(project_root, personalization)

    print()
    print(f"✅ Personalization saved!")
    print(f"   Updated: {config_path}")
    print(f"   Updated: {project_root / 'ITERATE.md'}")
    return 0


def _update_iterate_md_user_section(project_root: Path, personalization: Any) -> None:
    """Merge personalization content into the user-owned section of ITERATE.md.

    Preserves user's manually written sections; only replaces sections
    generated by personalization (identified by their headers).

    Args:
        project_root: Project root directory containing ITERATE.md.
        personalization: PersonalizationData with notes/conventions.
    """
    from iterate_cli.generator import extract_user_owned_section
    from iterate_cli.personalize import merge_user_sections

    iterate_md_path = project_root / "ITERATE.md"
    if not iterate_md_path.is_file():
        return

    content = iterate_md_path.read_text(encoding="utf-8")
    new_personalization_md = personalization.to_user_md_sections()

    start_idx = content.find(USER_START_MARKER)
    end_idx = content.find(USER_END_MARKER)

    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        return

    # Extract existing user-owned content to preserve manual edits.
    existing_user_content = extract_user_owned_section(content)

    # Merge: remove old personalization sections, append new ones.
    merged = merge_user_sections(existing_user_content, new_personalization_md)

    before = content[: start_idx + len(USER_START_MARKER)]
    after = content[end_idx:]
    updated = f"{before}\n{merged}\n{after}"

    iterate_md_path.write_text(updated, encoding="utf-8")


def _cmd_refresh(project_root: Path) -> int:
    """Handle the 'refresh' subcommand."""
    if not is_onboarding_complete(project_root):
        print("Onboarding not yet completed. Run 'iterate onboard' first.")
        return 1

    success = incremental_refresh(project_root)
    if success:
        print("✅ Incremental refresh complete.")
        print("   AI-maintained sections updated, user-owned sections preserved.")
        return 0
    else:
        print("❌ Refresh failed. ITERATE.md not found.")
        return 1


def _cmd_reonboard(project_root: Path) -> int:
    """Handle the 'reonboard' subcommand."""
    if not is_onboarding_complete(project_root):
        print("No existing onboarding found. Run 'iterate onboard' first.")
        return 1

    success = full_reonboard(project_root)
    if success:
        print("✅ Full re-onboarding complete.")
        print("   Old files backed up with .bak-<timestamp> suffix.")
        return 0
    else:
        print("❌ Re-onboarding cancelled or failed.")
        return 1


def _cmd_status(project_root: Path) -> int:
    """Handle the 'status' subcommand."""
    print(f"Project: {project_root}")
    print()

    if not is_onboarding_complete(project_root):
        print("Status: Not onboarded")
        print("Run 'iterate onboard' to initialize.")
        return 0

    print("Status: Onboarded ✅")

    config = load_onboarding_config(project_root)
    if config:
        onboarding = config.get("onboarding") or {}
        completed_at = onboarding.get("completed_at", "unknown")
        channel = onboarding.get("channel", "unknown")
        print(f"  Completed: {completed_at}")
        print(f"  Channel:   {channel}")

        # Show personalization summary.
        personalization = config.get("personalization") or {}
        if personalization:
            total = sum(
                len(v) if isinstance(v, list) else 0
                for v in personalization.values()
            )
            print(f"  Personalization: {total} rule(s)")

        # Check drift.
        drift = check_onboarding_drift(project_root)
        if drift is None:
            print("  Drift:     check disabled or no fingerprints")
        elif drift.has_drift:
            print(f"  Drift:     ⚠️  {drift.summary()}")
            print("  Consider running 'iterate refresh' or 'iterate reonboard'.")
        else:
            print("  Drift:     No drift detected ✅")
    else:
        print("  (iterate.config.yaml not found — only ITERATE.md exists)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
