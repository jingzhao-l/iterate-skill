"""iterate CLI entry point.

Provides subcommands for onboarding management:
    iterate onboard    — Run interactive CLI onboarding wizard
    iterate refresh    — Incremental refresh of ITERATE.md (preserve user sections)
    iterate reonboard  — Full re-onboarding (backup old files, run wizard)
    iterate status     — Show onboarding status and drift detection
    iterate --version  — Print version
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from iterate_cli import __version__
from iterate_cli.generator import write_onboarding_outputs
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
        help="Run interactive CLI onboarding wizard.",
        description="Run the interactive onboarding wizard to generate ITERATE.md "
        "and iterate.config.yaml for the project.",
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
    """Handle the 'onboard' subcommand."""
    if is_onboarding_complete(project_root):
        print("Onboarding already completed. ITERATE.md exists.")
        print("Use 'iterate refresh' for incremental update, or 'iterate reonboard' to redo.")
        return 1

    data = run_wizard(project_root)
    if data is None:
        return 1

    iterate_md, config_yaml = write_onboarding_outputs(data, project_root)
    print()
    print(f"✅ Onboarding complete!")
    print(f"   Written: {iterate_md}")
    print(f"   Written: {config_yaml}")
    print()
    print("You can now use /iterate in your AI coding tool.")
    return 0


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
