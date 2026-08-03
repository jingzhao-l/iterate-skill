"""iterate CLI entry point.

Provides subcommands for onboarding and personalization management:
    iterate onboard     — Run interactive CLI onboarding wizard (multi-path)
    iterate personalize — Direct personalization configuration (mid-project)
    iterate refresh     — Incremental refresh of ITERATE.md (preserve user sections)
    iterate reonboard   — Full re-onboarding (backup old files, run wizard)
    iterate status      — Show onboarding status and drift detection
    iterate --version   — Print version

All user-facing output is routed through the unified TUI layer
(``iterate_cli.tui``) for consistent skills.sh / Claude Code style styling.
"""

from __future__ import annotations

import argparse
import os
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
from iterate_cli.tui import tui
from iterate_cli.wizard import NO_CHANGES_NEEDED, run_wizard


def _should_show_banner(args: argparse.Namespace) -> bool:
    """Determine whether the ASCII banner should be shown.

    Banner is disabled by ``--no-banner`` or the ``ITERATE_NO_BANNER``
    environment variable (any non-empty value).
    """
    if getattr(args, "no_banner", False):
        return False
    if os.environ.get("ITERATE_NO_BANNER", "").strip():
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code: 0 for success, 1 for error/cancel.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        tui.banner()
        tui.info(f"iterate {__version__}")
        tui.empty_line()
        tui.hint("Install the skill across AI assistants: npx iterate-skill-installer")
        tui.hint("Initialize a project: iterate onboard")
        raise SystemExit(0)

    project_root = Path(args.project).resolve()

    if not project_root.is_dir():
        tui.error(f"Error: project directory not found: {project_root}")
        return 1

    if args.command == "onboard":
        if _should_show_banner(args):
            tui.banner()
        return _cmd_onboard(project_root)
    elif args.command == "personalize":
        if _should_show_banner(args):
            tui.banner()
        return _cmd_personalize(project_root)
    elif args.command == "refresh":
        if _should_show_banner(args):
            tui.banner()
        return _cmd_refresh(project_root)
    elif args.command == "reonboard":
        if _should_show_banner(args):
            tui.banner()
        return _cmd_reonboard(project_root)
    elif args.command == "status":
        if _should_show_banner(args):
            tui.banner()
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
    parser.add_argument(
        "-v", "--version",
        action="store_true",
        default=False,
        help="Show version and exit.",
    )
    parser.add_argument(
        "--no-banner",
        action="store_true",
        default=False,
        help="Disable the ITERATE ASCII art banner at startup.",
    )
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
    if data is NO_CHANGES_NEEDED:
        # Returning user explicitly declined all updates.
        tui.info("No changes made. Onboarding is already complete.")
        return 0
    if data is None:
        # User cancelled mid-flow (gate, basic wizard, or personalization
        # that was accepted but then aborted).
        return 1

    # Preserve the user-owned section of ITERATE.md when re-onboarding an
    # existing project, so manual edits and personalization content survive.
    existing_md: str | None = None
    existing_md_path = project_root / "ITERATE.md"
    if existing_md_path.is_file():
        try:
            existing_md = existing_md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            existing_md = None

    # Preserve existing personalization when the user did not re-personalize,
    # so a basic-config update does not silently drop structured rules
    # (protected paths, risk areas, extra validation commands, etc.).
    if data.personalization is None:
        from iterate_cli.personalize import load_personalization_from_config

        existing_config = load_onboarding_config(project_root) or {}
        existing_personalization = load_personalization_from_config(existing_config)
        if not existing_personalization.is_empty():
            data.personalization = existing_personalization

    iterate_md, config_yaml = write_onboarding_outputs(data, project_root, existing_md)
    tui.empty_line()
    tui.success("Onboarding complete!")
    tui.key_value("Written", str(iterate_md))
    tui.key_value("Written", str(config_yaml))
    if data.personalization is not None:
        tui.key_value("Personalization", "applied")
    tui.empty_line()
    tui.hint("You can now use /iterate in your AI coding tool.")
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
        tui.warning("Onboarding not yet completed. Run 'iterate onboard' first.")
        return 1

    config_path = project_root / "iterate.config.yaml"
    if not config_path.is_file():
        tui.warning("iterate.config.yaml not found. Run 'iterate onboard' first.")
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

    tui.empty_line()
    tui.success("Personalization saved!")
    tui.key_value("Updated", str(config_path))
    tui.key_value("Updated", str(project_root / "ITERATE.md"))
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
        tui.warning("Onboarding not yet completed. Run 'iterate onboard' first.")
        return 1

    success = incremental_refresh(project_root)
    if success:
        tui.success("Incremental refresh complete.")
        tui.hint("AI-maintained sections updated, user-owned sections preserved.", indent=2)
        return 0
    else:
        tui.error("Refresh failed. ITERATE.md not found.")
        return 1


def _cmd_reonboard(project_root: Path) -> int:
    """Handle the 'reonboard' subcommand."""
    if not is_onboarding_complete(project_root):
        tui.warning("No existing onboarding found. Run 'iterate onboard' first.")
        return 1

    success = full_reonboard(project_root)
    if success:
        tui.success("Full re-onboarding complete.")
        tui.hint("Old files backed up with .bak-<timestamp> suffix.", indent=2)
        return 0
    else:
        tui.error("Re-onboarding cancelled or failed.")
        return 1


def _count_personalization_rules(personalization: dict[str, Any]) -> int:
    """Count structured personalization rules for status display.

    Excludes the ``version`` field (schema metadata, not a rule) and
    properly handles ``extra_validation_commands`` which is a dict of
    module -> command list (each command counts as one rule).

    Args:
        personalization: The ``personalization`` section of iterate.config.yaml.
            May be None or non-dict if the config was manually edited;
            in that case 0 is returned.

    Returns:
        Total number of structured personalization rules across all categories.
    """
    # Defensive: caller may pass None if config was manually edited.
    if not isinstance(personalization, dict):
        return 0

    # Fields that are metadata, not rules — excluded from the count.
    META_FIELDS: frozenset[str] = frozenset({"version"})

    total = 0
    for key, value in personalization.items():
        if key in META_FIELDS:
            continue
        if isinstance(value, list):
            total += len(value)
        elif isinstance(value, dict):
            # extra_validation_commands: {module: [cmd, ...]}
            total += sum(len(cmds) for cmds in value.values() if isinstance(cmds, list))
    return total


def _cmd_status(project_root: Path) -> int:
    """Handle the 'status' subcommand.

    Output is routed through the TUI layer but keeps plain-text keywords
    (``Onboarded``, ``Not onboarded``, ``Drift``, ``No drift``,
    ``Personalization: N rule(s)``) so that automated tests and grep-based
    checks continue to work.
    """
    tui.intro("Iterate Skill — Status")
    tui.key_value("Project", str(project_root))
    tui.empty_line()

    if not is_onboarding_complete(project_root):
        tui.warning("Status: Not onboarded")
        tui.hint("Run 'iterate onboard' to initialize.", indent=2)
        return 0

    tui.success("Status: Onboarded")

    config = load_onboarding_config(project_root)
    if config:
        onboarding = config.get("onboarding") or {}
        completed_at = onboarding.get("completed_at", "unknown")
        channel = onboarding.get("channel", "unknown")
        tui.key_value("Completed", completed_at)
        tui.key_value("Channel", channel)

        # Show personalization summary.
        # Count structured rules, excluding the schema "version" field
        # (metadata, not a rule) and properly handling
        # extra_validation_commands (a dict of module -> command list).
        personalization = config.get("personalization") or {}
        if personalization:
            total = _count_personalization_rules(personalization)
            # Use plain info() to keep 'Personalization: N rule(s)' as a
            # contiguous substring (tests assert this exact text).
            tui.info(f"Personalization: {total} rule(s)", indent=2)

        # Check drift.
        drift = check_onboarding_drift(project_root)
        if drift is None:
            tui.key_value("Drift", "check disabled or no fingerprints")
        elif drift.has_drift:
            tui.warning(f"Drift: {drift.summary()}", indent=2)
            tui.hint("Consider running 'iterate refresh' or 'iterate reonboard'.", indent=4)
        else:
            tui.success("Drift: No drift detected", indent=2)
    else:
        tui.hint("(iterate.config.yaml not found — only ITERATE.md exists)", indent=2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
