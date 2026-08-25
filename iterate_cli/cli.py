"""iterate CLI entry point.

Provides subcommands for onboarding and personalization management:
    iterate onboard     — Run interactive CLI onboarding wizard (multi-path)
    iterate personalize — Direct personalization configuration (mid-project)
    iterate refresh     — Incremental refresh of ITERATE.md (preserve user sections)
    iterate reonboard   — Full re-onboarding (backup old files, run wizard)
    iterate status      — Show onboarding status and drift detection
    iterate show        — Read-only resolved config + personalization detail
    iterate doctor      — Project health diagnostics (--json / --json-out / --fix)
    iterate --version   — Print version

All user-facing output is routed through the unified TUI layer
(``iterate_cli.tui``) for consistent skills.sh / Claude Code style styling.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from iterate_cli import __version__
from iterate_cli.generator import (
    write_onboarding_outputs,
)
from iterate_cli.refresh import (
    REONBOARD_CANCELLED,
    REONBOARD_COMPLETED,
    REONBOARD_NO_CHANGES,
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
    return not os.environ.get("ITERATE_NO_BANNER", "").strip()


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
        if _should_show_banner(args):
            tui.banner()
        tui.info(f"iterate {__version__}")
        tui.empty_line()
        tui.hint("Install the skill across AI assistants: npx iterate-skill-installer")
        tui.hint("Initialize a project: iterate onboard")
        return 0

    project_root = Path(args.project).resolve()

    if not project_root.is_dir():
        tui.error(f"Error: project directory not found: {project_root}")
        return 1

    # Structured (JSON) output must not be polluted by the ASCII banner.
    show_banner = _should_show_banner(args) and not getattr(args, "json", False)

    try:
        return _dispatch_command(args, parser, project_root, show_banner)
    except KeyboardInterrupt:
        # Ctrl+C mid-interaction must not surface a raw traceback.
        tui.cancel()
        tui.hint("已中断，本次未写入任何文件 / Interrupted, nothing was written.", indent=2)
        return 1
    except EOFError:
        # Ctrl+D / closed stdin (e.g. piped without data) mid-prompt. Show a
        # clean cancellation instead of an unhandled-input traceback.
        tui.cancel()
        tui.hint(
            "输入已结束（Ctrl+D / EOF），本次未写入任何文件 / "
            "Input ended (Ctrl+D / EOF), nothing was written.",
            indent=2,
        )
        return 1


def _dispatch_command(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    project_root: Path,
    show_banner: bool,
) -> int:
    """Route a parsed subcommand to its handler.

    Centralized so that interactive handlers (onboard, personalize) can be
    wrapped once by the caller for graceful Ctrl+C/EOF handling.
    """
    if args.command == "onboard":
        if show_banner:
            tui.banner()
        return _cmd_onboard(project_root)
    if args.command == "personalize":
        if show_banner:
            tui.banner()
        return _cmd_personalize(
            project_root,
            clear=getattr(args, "clear", False),
            yes=getattr(args, "yes", False),
        )
    if args.command == "refresh":
        if show_banner:
            tui.banner()
        return _cmd_refresh(project_root, dry_run=getattr(args, "dry_run", False))
    if args.command == "reonboard":
        if show_banner:
            tui.banner()
        return _cmd_reonboard(project_root)
    if args.command == "status":
        if show_banner:
            tui.banner()
        return _cmd_status(project_root, json_output=getattr(args, "json", False))
    if args.command == "show":
        if show_banner:
            tui.banner()
        return _cmd_show(project_root, json_output=getattr(args, "json", False))
    if args.command == "doctor":
        if show_banner:
            tui.banner()
        return _cmd_doctor(
            project_root,
            json_output=getattr(args, "json", False),
            fix=getattr(args, "fix", False),
            json_out=getattr(args, "json_out", None),
        )
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
        "--json",
        action="store_true",
        default=False,
        help="Emit structured JSON for status/doctor instead of TUI output.",
    )
    parser.add_argument(
        "-p", "--project",
        default=".",
        help="Project root directory (default: current directory).",
    )

    subparsers = parser.add_subparsers(dest="command")

    # Shared arguments for subcommands: allows -p and --no-banner after the
    # subcommand, matching the global flags so `iterate status --no-banner`
    # works the same as `iterate --no-banner status`.
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "-p", "--project",
        default=argparse.SUPPRESS,
        help="Project root directory (default: current directory).",
    )
    parent.add_argument(
        "--no-banner",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Disable the ITERATE ASCII art banner at startup.",
    )

    subparsers.add_parser(
        "onboard",
        parents=[parent],
        help="Run interactive CLI onboarding wizard (multi-path).",
        description="Run the interactive onboarding wizard. First-time projects get "
        "basic onboarding + personalization offer; existing projects get "
        "config update + personalization offer.",
    )
    personalize_parser = subparsers.add_parser(
        "personalize",
        parents=[parent],
        help="Direct personalization configuration (mid-project).",
        description="Skip basic onboarding and go directly to the 9-step "
        "personalization wizard. Ideal for adding constraints mid-project. "
        "Use --clear to remove all personalization.",
    )
    personalize_parser.add_argument(
        "--clear",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Remove all personalization (structured rules + ITERATE.md "
        "sections) without running the wizard.",
    )
    personalize_parser.add_argument(
        "--yes",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Skip the confirmation prompt (only meaningful with --clear).",
    )
    refresh_parser = subparsers.add_parser(
        "refresh",
        parents=[parent],
        help="Incrementally refresh ITERATE.md (preserve user sections).",
        description="Re-scan the project and update AI-maintained sections of ITERATE.md "
        "while preserving user-owned sections. Also updates manifest fingerprints.",
    )
    refresh_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Preview what would change without writing any files.",
    )
    subparsers.add_parser(
        "reonboard",
        parents=[parent],
        help="Full re-onboarding (backup old files, run wizard).",
        description="Back up existing ITERATE.md and iterate.config.yaml, then run the "
        "full onboarding wizard from scratch.",
    )
    status_parser = subparsers.add_parser(
        "status",
        parents=[parent],
        help="Show onboarding status and drift detection.",
        description="Check whether onboarding is complete and whether the project's "
        "tech stack has drifted since the last onboarding.",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit a structured JSON report instead of TUI output.",
    )
    show_parser = subparsers.add_parser(
        "show",
        parents=[parent],
        help="Show resolved config and personalization (read-only).",
        description="Read-only inspection of the resolved project state: "
        "onboarding metadata, effective config, drift status, and the full "
        "personalization detail. Never writes files.",
    )
    show_parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit a structured JSON report instead of TUI output.",
    )
    doctor_parser = subparsers.add_parser(
        "doctor",
        parents=[parent],
        help="Run project health diagnostics against the skill.",
        description="Validate the project's iterate.config.yaml, ITERATE.md and "
        "onboarding state against the skill's canonical definitions. "
        "Exits non-zero when errors are found.",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit a structured JSON report instead of TUI output.",
    )
    doctor_parser.add_argument(
        "--json-out",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="Write a structured JSON report to PATH (created if missing).",
    )
    doctor_parser.add_argument(
        "--fix",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Apply safe, non-destructive fixes to iterate.config.yaml "
        "(backup written first) before running diagnostics.",
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
        except (OSError, UnicodeDecodeError) as exc:
            # If ITERATE.md exists but cannot be read, regenerating from scratch
            # would silently drop the user-owned (manual) section. Refuse to
            # proceed rather than risk losing manual edits.
            tui.warning(f"未能读取现有 {existing_md_path.name}：{exc}")
            tui.info("为避免覆盖你的手动编辑区，已中止。请先修复该文件读取问题。")
            return 1

    # Preserve existing personalization when the user did not re-personalize,
    # so a basic-config update does not silently drop structured rules
    # (protected paths, risk areas, extra validation commands, etc.) or
    # free-form notes/conventions stored in ITERATE.md.
    if data.personalization is None:
        from iterate_cli.personalize import load_existing_personalization

        existing_config = load_onboarding_config(project_root) or {}
        existing_personalization = load_existing_personalization(project_root, existing_config)
        if not existing_personalization.is_empty():
            data.personalization = existing_personalization

    try:
        iterate_md, config_yaml = write_onboarding_outputs(data, project_root, existing_md)
    except (OSError, UnicodeDecodeError) as exc:
        # Writing either artifact failed (disk full, permissions, locked file,
        # or a corrupt template). Surface a clear message instead of a bare
        # traceback; the writer already rolled back partially-written files.
        tui.error(f"写入 onboarding 产物失败：{exc}")
        tui.warning("未写入或已回滚 ITERATE.md / iterate.config.yaml，请检查目录权限后重试。")
        return 1
    tui.empty_line()
    tui.success("Onboarding complete!")
    tui.key_value("Written", str(iterate_md))
    tui.key_value("Written", str(config_yaml))
    if data.personalization is not None:
        tui.key_value("Personalization", "applied")
    tui.empty_line()
    tui.hint("You can now use /iterate in your AI coding tool.")
    return 0


def _cmd_personalize(project_root: Path, clear: bool = False, yes: bool = False) -> int:
    """Handle the 'personalize' subcommand — direct personalization configuration.

    Without ``clear``, runs the 9-step personalization wizard (with existing
    content pre-loaded for editing). With ``clear``, removes all
    personalization (structured rules + ITERATE.md sections) after a
    confirmation prompt (bypassed with ``yes``).

    Args:
        project_root: Project root directory.
        clear: When True, clear personalization instead of running the wizard.
        yes: When True, skip the clear confirmation prompt.

    Returns:
        Exit code: 0 on success/cancel, 1 on failure.
    """
    from iterate_cli.personalize import (
        has_personalization,
        load_existing_personalization,
        run_personalize_wizard,
        save_personalization,
    )

    # Personalization requires existing onboarding (ITERATE.md + config).
    if not is_onboarding_complete(project_root):
        tui.warning("Onboarding not yet completed. Run 'iterate onboard' first.")
        return 1

    config_path = project_root / "iterate.config.yaml"
    if not config_path.is_file():
        tui.warning("iterate.config.yaml not found. Run 'iterate onboard' first.")
        return 1

    if clear:
        return _cmd_personalize_clear(project_root, yes=yes, has=has_personalization)

    # Load existing personalization for editing (structured from config +
    # free-form notes/conventions from ITERATE.md) so re-running the wizard
    # preserves previously entered content instead of wiping it.
    existing_config = load_onboarding_config(project_root) or {}
    existing_personalization = load_existing_personalization(project_root, existing_config)

    personalization = run_personalize_wizard(
        project_root,
        existing=existing_personalization,
    )
    if personalization is None:
        return 1

    # Save structured fields to config.yaml and free-form notes/conventions
    # to ITERATE.md atomically (with rollback on failure).
    config_path, iterate_md_path = save_personalization(project_root, personalization)

    tui.empty_line()
    tui.success("Personalization saved!")
    tui.key_value("Updated", str(config_path))
    tui.key_value("Updated", str(iterate_md_path))
    return 0


def _cmd_personalize_clear(
    project_root: Path,
    yes: bool,
    has: Callable[[Path, dict[str, Any]], bool],
) -> int:
    """Handle ``iterate personalize --clear`` — reset all personalization.

    Args:
        project_root: Project root directory.
        yes: When True, skip the confirmation prompt.
        has: The ``has_personalization`` callable (injected for testability).

    Returns:
        Exit code: 0 on success/cancel/nothing-to-clear, 1 on failure.
    """
    config = load_onboarding_config(project_root) or {}
    if not has(project_root, config):
        tui.info("No personalization to clear.")
        return 0

    if not yes:
        import builtins

        from iterate_cli.wizard import _ask_yes_no

        confirmed = _ask_yes_no(
            "确认清空所有个性化配置? / Confirm clearing all personalization?",
            builtins.input,
            default=False,
        )
        if not confirmed:
            tui.info("已取消 / Cancelled.")
            return 0

    from iterate_cli.personalize import clear_personalization

    try:
        config_path, iterate_md_path = clear_personalization(project_root)
    except (OSError, UnicodeDecodeError) as exc:
        tui.error(f"Failed to clear personalization: {exc}")
        return 1

    tui.empty_line()
    tui.success("Personalization cleared!")
    tui.key_value("Updated", str(config_path))
    if iterate_md_path.is_file():
        tui.key_value("Updated", str(iterate_md_path))
    return 0


def _cmd_show(project_root: Path, json_output: bool = False) -> int:
    """Handle the 'show' subcommand — read-only resolved config inspection.

    Args:
        project_root: Project root directory.
        json_output: When True, emit a structured JSON report.

    Returns:
        Exit code: 0 on success.
    """
    from iterate_cli.show import run_show

    return run_show(project_root, json_output=json_output)


def _cmd_refresh(project_root: Path, dry_run: bool = False) -> int:
    """Handle the 'refresh' subcommand.

    Args:
        project_root: Project root directory.
        dry_run: When True, only preview what would change without writing.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    if not is_onboarding_complete(project_root):
        tui.warning("Onboarding not yet completed. Run 'iterate onboard' first.")
        return 1

    if dry_run:
        from iterate_cli.refresh import preview_refresh

        preview = preview_refresh(project_root)
        if not preview["ok"]:
            tui.error(
                f"Refresh preview failed. Could not read ITERATE.md / iterate.config.yaml: "
                f"{preview['error']}"
            )
            return 1
        if preview["changed"]:
            stats = preview["stats"]
            tui.warning("Refresh would make the following changes:")
            tui.key_value("ITERATE.md", f"{preview['md_changed_lines']} line(s) changed")
            tui.bullet(
                f"+{stats.get('added', 0)} / -{stats.get('removed', 0)}",
                indent=4,
            )
            tui.key_value(
                "iterate.config.yaml",
                "would be updated" if preview["config_changed"] else "unchanged",
            )
            tui.empty_line()
            tui.hint("Run 'iterate refresh' (without --dry-run) to apply these changes.", indent=2)
        else:
            tui.success("No changes needed — ITERATE.md and iterate.config.yaml are already up to date.")
        return 0

    success = incremental_refresh(project_root)
    if success:
        tui.success("Incremental refresh complete.")
        tui.hint("AI-maintained sections updated, user-owned sections preserved.", indent=2)
        return 0
    else:
        tui.error("Refresh failed. Could not read or write ITERATE.md / iterate.config.yaml (see stderr).")
        return 1


def _cmd_reonboard(project_root: Path) -> int:
    """Handle the 'reonboard' subcommand."""
    if not is_onboarding_complete(project_root):
        tui.warning("No existing onboarding found. Run 'iterate onboard' first.")
        return 1

    status = full_reonboard(project_root)
    if status == REONBOARD_COMPLETED:
        tui.success("Full re-onboarding complete.")
        tui.hint("Old files backed up with .bak-<timestamp> suffix.", indent=2)
        return 0
    elif status == REONBOARD_NO_CHANGES:
        tui.info("Re-onboarding not needed — no changes to apply.")
        tui.hint("Old files backed up with .bak-<timestamp> suffix.", indent=2)
        return 0
    elif status == REONBOARD_CANCELLED:
        # Cancelling is a normal (non-error) user decision; mirror onboarding's
        # cancel message and exit code so scripts see "not written" clearly.
        tui.cancel()
        tui.hint("Re-onboarding cancelled. Old files are intact (a .bak snapshot was taken).", indent=2)
        return 1
    else:
        tui.error("Re-onboarding failed. Old files were backed up but not replaced.")
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


def _cmd_status(project_root: Path, json_output: bool = False) -> int:
    """Handle the 'status' subcommand.

    Output is routed through the TUI layer but keeps plain-text keywords
    (``Onboarded``, ``Not onboarded``, ``Drift``, ``No drift``,
    ``Personalization: N rule(s)``) so that automated tests and grep-based
    checks continue to work. When ``json_output`` is True, a structured JSON
    blob is emitted instead (useful for scripts and CI).
    """
    # Structured gathering shared by both render modes. Onboarding state and
    # config are loaded exactly once so the JSON and TUI branches cannot drift
    # from each other (and re-reading the file mid-render cannot yield a stale
    # half-loaded snapshot).
    data: dict[str, Any] = {"project": str(project_root)}
    onboarded = is_onboarding_complete(project_root)
    config = load_onboarding_config(project_root) if onboarded else None
    data["onboarded"] = onboarded

    drift = None
    if config:
        onboarding = config.get("onboarding") or {}
        data["completed_at"] = onboarding.get("completed_at", "unknown")
        data["channel"] = onboarding.get("channel", "unknown")
        data["skill_version"] = onboarding.get("skill_version", "unknown")
        data["drift_check"] = onboarding.get("drift_check", True)
        raw_fingerprints = onboarding.get("fingerprints") or []
        data["fingerprints"] = (
            len(raw_fingerprints) if isinstance(raw_fingerprints, list) else 0
        )
        personalization = config.get("personalization") or {}
        data["personalization_rules"] = (
            _count_personalization_rules(personalization) if personalization else 0
        )

        drift = check_onboarding_drift(project_root)
        if drift is None:
            data["drift"] = "unknown"
        elif drift.has_drift:
            data["drift"] = drift.summary()
        else:
            data["drift"] = "none"

    if json_output:
        import json

        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    tui.intro("Iterate Skill — Status")
    tui.key_value("Project", str(project_root))
    tui.empty_line()

    if not onboarded:
        tui.warning("Status: Not onboarded")
        tui.hint("Run 'iterate onboard' to initialize.", indent=2)
        return 0

    tui.success("Status: Onboarded")

    if not config:
        tui.hint("(iterate.config.yaml not found — only ITERATE.md exists)", indent=2)
        return 0

    onboarding = config.get("onboarding") or {}
    tui.key_value("Completed", data["completed_at"])
    tui.key_value("Channel", data["channel"])
    tui.key_value("Skill version", data["skill_version"])

    # Drift configuration summary.
    drift_enabled = onboarding.get("drift_check", True)
    fp_count = data["fingerprints"]
    tui.key_value("Fingerprints", f"{fp_count} manifest(s)")
    tui.key_value("Drift check", "enabled" if drift_enabled else "disabled")

    # Show personalization summary (metadata ``version`` field excluded).
    if data["personalization_rules"]:
        # Use plain info() to keep 'Personalization: N rule(s)' as a
        # contiguous substring (tests assert this exact text).
        tui.info(f"Personalization: {data['personalization_rules']} rule(s)", indent=2)

    # Surface drift and actionable advice (already computed once above).
    if drift is None:
        if not drift_enabled:
            tui.key_value("Drift", "check disabled")
        elif fp_count == 0:
            tui.key_value("Drift", "no fingerprints recorded yet")
        else:
            tui.key_value("Drift", "unknown")
    elif drift.has_drift:
        tui.warning(f"Drift: {drift.summary()}", indent=2)
        tui.hint(drift.advice(), indent=4)
    else:
        tui.success("Drift: No drift detected", indent=2)

    return 0


def _cmd_doctor(
    project_root: Path,
    json_output: bool = False,
    fix: bool = False,
    json_out: str | None = None,
) -> int:
    """Handle the 'doctor' subcommand — project health diagnostics.

    When ``fix`` is True, safe non-destructive config fixes are applied
    (with a timestamped backup) before diagnostics are re-run.

    When ``json_out`` is set, the structured report is additionally written
    to that file (its parent directory is created as needed).

    Args:
        project_root: Project root directory.
        json_output: When True, emit a structured JSON report.
        fix: When True, apply safe config fixes before running diagnostics.
        json_out: When set, export the JSON report to this path.

    Returns:
        Exit code: 0 when healthy, 1 when errors are found.
    """
    from iterate_cli.doctor import (
        export_report_json,
        render_report,
        run_doctor,
        run_doctor_fix,
    )

    fixes: list[str] = []
    if fix:
        ok, fixes = run_doctor_fix(project_root)
        if not ok:
            if json_output:
                import json

                print(
                    json.dumps(
                        {"error": "doctor --fix: could not apply fixes"},
                        ensure_ascii=False,
                    )
                )
                return 1
            tui.error("doctor --fix: could not apply fixes (see stderr).")
            return 1
        if not json_output:
            if fixes:
                tui.success(f"doctor --fix: applied {len(fixes)} safe fix(es).")
                for fix_note in fixes:
                    tui.bullet(fix_note, indent=4)
                tui.empty_line()
            else:
                tui.success("doctor --fix: no safe fixes needed.")
                tui.empty_line()

    report = run_doctor(project_root)
    if json_output:
        # Attach applied fixes to the structured report so JSON consumers
        # see them without the JSON blob being polluted by TUI text.
        report.fixes = fixes
    code = render_report(report, json_output=json_output)

    if json_out:
        try:
            export_report_json(report, Path(json_out).resolve())
            if not json_output:
                tui.hint(f"doctor: JSON report written to {json_out}")
        except OSError as exc:
            tui.error(f"doctor: failed to write JSON report to {json_out}: {exc}")
            return 1

    return code

