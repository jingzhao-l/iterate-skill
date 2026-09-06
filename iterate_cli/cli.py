"""iterate CLI entry point.

Provides subcommands for onboarding and personalization management:
    iterate onboard     — Run interactive CLI onboarding wizard (multi-path)
    iterate personalize — Direct personalization configuration (mid-project)
    iterate refresh     — Incremental refresh of ITERATE.md (preserve user sections)
    iterate reonboard   — Full re-onboarding (backup old files, run wizard)
    iterate status      — Show onboarding status and drift detection
    iterate show        — Read-only resolved config + personalization detail
    iterate doctor      — Project health diagnostics (--json / --json-out / --fix)
    iterate guard       — Defensive-programming pre/post-edit checks (v3.0)
    iterate invariant   — Project-level invariant check (v3.0, defensive mode)
    iterate --version   — Print version

All user-facing output is routed through the unified TUI layer
(``iterate_cli.tui``) for consistent skills.sh / Claude Code style styling.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from iterate_cli import __version__
from iterate_cli.fingerprint import drift_summary
from iterate_cli.generator import (
    USER_END_MARKER,
    USER_START_MARKER,
    write_onboarding_outputs,
)
from iterate_cli.refresh import (
    REONBOARD_CANCELLED,
    REONBOARD_COMPLETED,
    REONBOARD_NO_CHANGES,
    check_onboarding_drift,
    full_reonboard,
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
        # Structured (JSON) output must not be polluted by the ASCII banner,
        # matching the subcommand paths below.
        if _should_show_banner(args) and not getattr(args, "json", False):
            tui.banner()
        # A bare "iterate <version>" line is emitted on non-TTY (piped) stdout
        # so scripts can parse `iterate --version` without ANSI/prompt noise.
        if sys.stdout.isatty():
            tui.info(f"iterate {__version__}")
            tui.empty_line()
            tui.hint("Install the skill across AI assistants: npx iterate-skill-installer")
            tui.hint("Initialize a project: iterate onboard")
        else:
            print(f"iterate {__version__}")
        return 0

    # Interactive commands never produce structured output; a caller passing
    # --json to them has a misunderstanding, not a silent success.
    non_json_commands = {"onboard", "personalize", "reonboard"}
    if getattr(args, "json", False) and args.command in non_json_commands:
        tui.error(
            f"--json is not supported for '{args.command}' (interactive command). "
            "Use `iterate status/show/doctor --json` for structured output, or "
            "`iterate config get KEY --json` for single values."
        )
        return 2

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
        return _cmd_refresh(
            project_root,
            dry_run=getattr(args, "dry_run", False),
            json_output=getattr(args, "json", False),
        )
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
            strict=getattr(args, "strict", False),
            json_out=getattr(args, "json_out", None),
        )
    if args.command == "config":
        if show_banner:
            tui.banner()
        return _cmd_config(
            project_root,
            action=getattr(args, "config_action", None),
            key=getattr(args, "key", None),
            value=getattr(args, "value", None),
            json_output=getattr(args, "json", False),
        )
    if args.command == "guard":
        if show_banner:
            tui.banner()
        return _cmd_guard(
            project_root,
            guard_action=getattr(args, "guard_action", None),
            targets=getattr(args, "targets", None),
            json_output=getattr(args, "json", False),
            dry_run=getattr(args, "dry_run", False),
        )
    if args.command == "invariant":
        if show_banner:
            tui.banner()
        return _cmd_invariant(
            project_root,
            json_output=getattr(args, "json", False),
            dry_run=getattr(args, "dry_run", False),
        )
    if args.command == "fingerprint":
        if show_banner:
            tui.banner()
        return _cmd_fingerprint(
            project_root,
            json_output=getattr(args, "json", False),
        )
    parser.print_help()
    # No subcommand given (bare `iterate`): this is a usage error, not success.
    return 2


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
        help="Emit structured JSON for status/show/doctor/refresh/config instead "
        "of TUI output (interactive commands reject it).",
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
    refresh_parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit a structured JSON report instead of TUI output.",
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
    doctor_parser.add_argument(
        "--strict",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Treat warnings as failures too: exit 1 when any warning is "
        "present (default: only errors are blocking). Useful for CI gating.",
    )
    config_parser = subparsers.add_parser(
        "config",
        parents=[parent],
        help="Inspect or modify config values without the interactive wizard.",
        description="Non-interactive config inspection and editing. With no "
        "action, prints every settable value; 'get KEY' prints one resolved "
        "value; 'set KEY VALUE' validates and writes one value with a "
        "timestamped backup.",
    )
    config_parser.add_argument(
        "config_action",
        nargs="?",
        choices=["get", "set"],
        default=None,
        help="Action to perform: 'get' (default when omitted) or 'set'.",
    )
    config_parser.add_argument(
        "key",
        nargs="?",
        default=None,
        help="Flat config key to read or write (omit to list all keys).",
    )
    config_parser.add_argument(
        "value",
        nargs="?",
        default=None,
        help="Value to set (only used with 'set').",
    )
    config_parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit a structured JSON object instead of TUI output.",
    )

    guard_parser = subparsers.add_parser(
        "guard",
        parents=[parent],
        help="Defensive-programming pre/post-edit checks (v3.0 defensive mode).",
        description="Deterministic checks a host AI runs around every coding step: "
        "'pre-check' verifies targets exist / worktree is clean / manifests are "
        "ready before editing; 'post-check' executes exactly the configured "
        "validation.commands after editing. Exits non-zero on failure. "
        "Use --dry-run to preview exact commands without executing them.",
    )
    guard_parser.add_argument(
        "guard_action",
        choices=["pre-check", "post-check"],
        help="Which guard to run: 'pre-check' (before edits) or 'post-check' (after edits).",
    )
    guard_parser.add_argument(
        "targets",
        nargs="*",
        default=None,
        help="Paths to check (pre-check: must exist; post-check: module names to filter).",
    )
    guard_parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit a structured JSON object instead of TUI output.",
    )
    guard_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Preview the exact commands that would run without executing anything.",
    )

    invariant_parser = subparsers.add_parser(
        "invariant",
        parents=[parent],
        help="Run project-level invariant checks (v3.0 defensive mode).",
        description="Evaluate the invariants declared under config.invariants "
        "(per-module command lists plus 'ensure' file assertions). Degrades to "
        "validation.commands when no invariants section is configured. "
        "Exits non-zero when any invariant is violated. Use --dry-run to preview.",
    )
    invariant_parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit a structured JSON object instead of TUI output.",
    )
    invariant_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Preview the exact commands that would run without executing anything.",
    )

    fingerprint_parser = subparsers.add_parser(
        "fingerprint",
        parents=[parent],
        help="Verify manifest fingerprints against the project state.",
        description="Compare the SHA-256 manifest fingerprints recorded at "
        "onboarding/refresh time against the current project root. Detects "
        "added, removed, and changed tech-stack manifests. Exits non-zero "
        "when drift is detected.",
    )
    fingerprint_parser.add_argument(
        "fingerprint_action",
        nargs="?",
        choices=["verify"],
        default="verify",
        help="Action to perform (default: 'verify').",
    )
    fingerprint_parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit a structured JSON object instead of TUI output.",
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
        # An ITERATE.md without the USER-OWNED markers cannot preserve manual
        # edits — regenerating would silently replace them with the template.
        # Refuse and point the user at `iterate reonboard` (which backs the
        # file up first) instead of overwriting possibly hand-edited content.
        start_idx = existing_md.find(USER_START_MARKER)
        end_idx = existing_md.find(USER_END_MARKER)
        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
            tui.error(
                "Existing ITERATE.md is missing the USER-OWNED section markers; "
                "refusing to overwrite possibly hand-edited content."
            )
            tui.hint(
                "Restore the markers <!-- ITERATE:USER-OWNED:START --> / ...END -->, "
                "or run `iterate reonboard` which backs up the file first.",
                indent=2,
            )
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
        Exit code: 0 on success/nothing-to-clear, 1 on failure/cancel.
    """
    from iterate_cli.personalize import (
        CorruptConfigError,
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
    # to ITERATE.md atomically (with rollback on failure). A corrupt config
    # must not be rewritten over, so the strict loader's error is surfaced
    # cleanly instead of a bare traceback.
    try:
        config_path, iterate_md_path = save_personalization(project_root, personalization)
    except CorruptConfigError as exc:
        tui.error(str(exc))
        return 1
    except (OSError, UnicodeDecodeError) as exc:
        tui.error(f"Failed to write personalization: {exc}")
        return 1

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
    from iterate_cli.personalize import (
        CorruptConfigError,
        clear_personalization,
        load_config_strict,
    )

    # A corrupt config is not "nothing to clear": silently treating it as such
    # would hide the damage. Surface it as a clean error (return 1) instead.
    try:
        config = load_config_strict(project_root / "iterate.config.yaml")
    except CorruptConfigError as exc:
        tui.error(str(exc))
        return 1
    except (OSError, UnicodeDecodeError) as exc:
        tui.error(f"Failed to read iterate.config.yaml: {exc}")
        return 1

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

    try:
        config_path, iterate_md_path = clear_personalization(project_root)
    except CorruptConfigError as exc:
        tui.error(str(exc))
        return 1
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


def _cmd_refresh(
    project_root: Path, dry_run: bool = False, json_output: bool = False
) -> int:
    """Handle the 'refresh' subcommand.

    Args:
        project_root: Project root directory.
        dry_run: When True, only preview what would change without writing.
        json_output: When True, emit a structured JSON report instead of TUI
            lines. With ``--dry-run --json`` the preview is reported without
            writing; with ``--json`` alone the refresh runs and reports what
            changed.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    from iterate_cli.refresh import incremental_refresh, preview_refresh

    def _json(error: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {
            "project": str(project_root),
            "ok": error == "",
            "dry_run": dry_run,
            "changed": False,
            "config_changed": False,
            "md_changed_lines": 0,
            "stats": {},
        }
        if error:
            payload["error"] = error
        return payload

    if not is_onboarding_complete(project_root):
        tui.warning("Onboarding not yet completed. Run 'iterate onboard' first.")
        if json_output:
            print(json.dumps(_json("onboarding not completed"), ensure_ascii=False))
        return 1

    if dry_run:
        preview = preview_refresh(project_root)
        if not preview["ok"]:
            if json_output:
                print(json.dumps(_json(preview["error"]), ensure_ascii=False))
            else:
                tui.error(
                    f"Refresh preview failed. Could not read ITERATE.md / iterate.config.yaml: "
                    f"{preview['error']}"
                )
            return 1
        if json_output:
            print(
                json.dumps(
                    {
                        "project": str(project_root),
                        "ok": True,
                        "dry_run": True,
                        "changed": preview["changed"],
                        "config_changed": preview["config_changed"],
                        "md_changed_lines": preview["md_changed_lines"],
                        "stats": preview["stats"],
                    },
                    ensure_ascii=False,
                )
            )
            return 0
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

    if json_output:
        # Preview first to report accurate changed/line statistics, then apply.
        preview = preview_refresh(project_root)
        if not preview["ok"]:
            print(json.dumps(_json(preview["error"]), ensure_ascii=False))
            return 1
        success = incremental_refresh(project_root)
        if not success:
            print(json.dumps(_json("refresh failed (see stderr)"), ensure_ascii=False))
            return 1
        print(
            json.dumps(
                {
                    "project": str(project_root),
                    "ok": True,
                    "dry_run": False,
                    "changed": preview["changed"],
                    "config_changed": preview["config_changed"],
                    "md_changed_lines": preview["md_changed_lines"],
                    "stats": preview["stats"],
                },
                ensure_ascii=False,
            )
        )
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
        # REONBOARD_FAILED may be a backup failure (nothing was backed up) or
        # a write failure after a successful backup; say so accurately.
        tui.error(
            "Re-onboarding failed (see stderr). Old files are backed up "
            "only when the backup step succeeded."
        )
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
        data["drift"] = drift_summary(drift)
        # Machine-readable drift detail (B4): scripts can key off
        # drift_detected plus the concrete added/removed/changed lists
        # instead of parsing the human summary string.
        if drift is None:
            data["drift_detected"] = None
            data["drifted_added"] = []
            data["drifted_removed"] = []
            data["drifted_changed"] = []
        else:
            data["drift_detected"] = drift.has_drift
            data["drifted_added"] = list(drift.added)
            data["drifted_removed"] = list(drift.removed)
            data["drifted_changed"] = list(drift.changed)

    if json_output:
        import json

        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    return _render_status_tui(project_root, data, config, drift)


def _render_status_tui(
    project_root: Path,
    data: dict[str, Any],
    config: dict[str, Any] | None,
    drift: Any,
) -> int:
    """Render the TUI view of ``_cmd_status`` data."""
    tui.intro("Iterate Skill — Status")
    tui.key_value("Project", str(project_root))
    tui.empty_line()

    if not data["onboarded"]:
        tui.warning("Status: Not onboarded")
        tui.hint("Run 'iterate onboard' to initialize.", indent=2)
        return 0

    tui.success("Status: Onboarded")

    if not config:
        tui.hint("(iterate.config.yaml not found — only ITERATE.md exists)", indent=2)
        return 0

    tui.key_value("Completed", data["completed_at"])
    tui.key_value("Channel", data["channel"])
    tui.key_value("Skill version", data["skill_version"])

    # Drift configuration summary.
    drift_enabled = data["drift_check"]
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
    strict: bool = False,
    json_out: str | None = None,
) -> int:
    """Handle the 'doctor' subcommand — project health diagnostics.

    When ``fix`` is True, safe non-destructive config fixes are applied
    (with a timestamped backup) before diagnostics are re-run.

    When ``json_out`` is set, the structured report is additionally written
    to that file (its parent directory is created as needed).

    When ``strict`` is True, warnings flip the exit code to 1 (errors are
    always blocking); this lets CI gate on any non-clean state.

    Args:
        project_root: Project root directory.
        json_output: When True, emit a structured JSON report.
        fix: When True, apply safe config fixes before running diagnostics.
        strict: When True, warnings are treated as failures.
        json_out: When set, export the JSON report to this path.

    Returns:
        Exit code: 0 when healthy, 1 when errors are found (or warnings too
        under --strict).
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
                # Match the DoctorReport JSON contract (project/skill_version/
                # healthy/fixes/findings) so consumers can decode a failed
                # --fix the same shape as a successful run.
                print(
                    json.dumps(
                        {
                            "project": str(project_root),
                            "skill_version": __version__,
                            "healthy": False,
                            "fixes": [],
                            "findings": [
                                {
                                    "severity": "error",
                                    "check": "config",
                                    "message": (
                                        "doctor --fix failed: could not read or safely "
                                        "fix iterate.config.yaml (run `iterate doctor` "
                                        "without --fix for details)."
                                    ),
                                    "detail": "",
                                }
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 1
            tui.error("doctor --fix: could not read or safely fix iterate.config.yaml (see stderr).")
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
    # Attach applied fixes to the structured report so JSON consumers (both
    # --json and --json-out) see them without the report being polluted by
    # TUI text or the fixes list being dropped from the exported file.
    report.fixes = fixes
    code = render_report(report, json_output=json_output, strict=strict)

    if json_out:
        try:
            export_report_json(report, Path(json_out).resolve())
            if not json_output:
                tui.hint(f"doctor: JSON report written to {json_out}")
        except OSError as exc:
            tui.error(f"doctor: failed to write JSON report to {json_out}: {exc}")
            return 1

    return code


def _cmd_config(
    project_root: Path,
    action: str | None,
    key: str | None,
    value: str | None,
    json_output: bool = False,
) -> int:
    """Handle the 'config' subcommand — non-interactive config inspection/edit.

    ``iterate config`` prints every settable value, ``iterate config get [k]``
    prints one (or all) resolved value(s), and ``iterate config set k v``
    validates and writes a single value with a timestamped backup. With
    ``--json``, read/get/set emit a structured JSON object on stdout (for
    scripts/CI) instead of TUI lines.

    Args:
        project_root: Project root directory.
        action: The config action ("get", "set", or None to list all).
        key: Flat config key to read or write (None to list all keys).
        value: Raw CLI value to write (only used with "set").
        json_output: When True, emit JSON objects instead of TUI output.

    Returns:
        Exit code: 0 on success, 1 on unknown key / invalid value / write
        failure.
    """
    from iterate_cli.configcmd import run_config_get, run_config_set

    if action == "set":
        if key is None:
            tui.error("Usage: iterate config set KEY VALUE")
            return 1
        if value is None:
            tui.error("Usage: iterate config set KEY VALUE")
            return 1
        return run_config_set(project_root, key, value, json_output=json_output)

    # 'get' (explicit or implicit) lists all values when no key is given.
    return run_config_get(project_root, key, json_output=json_output)


def _cmd_guard(
    project_root: Path,
    guard_action: str | None,
    targets: list[str] | None,
    json_output: bool = False,
    dry_run: bool = False,
) -> int:
    """Handle the 'guard' subcommand — defensive-programming pre/post-edit checks.

    Args:
        project_root: Project root directory.
        guard_action: Which guard to run (``pre-check`` / ``post-check``).
        targets: For pre-check, paths that must exist; for post-check, module
            names to filter the validation commands.
        json_output: When True, emit a structured JSON object instead of TUI.
        dry_run: When True, preview exact commands without executing anything.

    Returns:
        Exit code: 0 when all checks pass, 1 otherwise.
    """
    from iterate_cli.guard import (
        render_guard_result,
        run_guard_postcheck,
        run_guard_precheck,
    )

    if guard_action == "pre-check":
        result = run_guard_precheck(project_root, targets or [], dry_run=dry_run)
    else:
        result = run_guard_postcheck(project_root, targets or None, dry_run=dry_run)
    return render_guard_result(result, json_output=json_output)


def _cmd_invariant(
    project_root: Path,
    json_output: bool = False,
    dry_run: bool = False,
) -> int:
    """Handle the 'invariant' subcommand — project-level invariant check.

    Args:
        project_root: Project root directory.
        json_output: When True, emit a structured JSON object instead of TUI.
        dry_run: When True, preview exact commands without executing anything.

    Returns:
        Exit code: 0 when every invariant holds, 1 otherwise.
    """
    from iterate_cli.guard import render_guard_result, run_invariant_check

    result = run_invariant_check(project_root, dry_run=dry_run)
    return render_guard_result(result, json_output=json_output)


def _cmd_fingerprint(project_root: Path, json_output: bool = False) -> int:
    """Handle the 'fingerprint' subcommand — verify manifest drift.

    Compares the fingerprints stored in iterate.config.yaml against the
    current project root via ``check_onboarding_drift``. Drift is
    non-blocking (an iteration can always continue), so this command is an
    informational health check: it exits 0 when no drift is detected and 1
    when added/removed/changed manifests are found.

    Args:
        project_root: Project root directory.
        json_output: When True, emit a structured JSON object instead of TUI.

    Returns:
        Exit code: 0 when no drift (or drift checking is unavailable), 1 when
        drift is detected.
    """
    from iterate_cli.refresh import check_onboarding_drift

    drift = check_onboarding_drift(project_root)

    if json_output:
        if drift is None:
            # Distinguish the three reasons drift checking is unavailable
            # (mirroring doctor's drift check) so a JSON consumer can tell
            # "not onboarded" from "check disabled" from "no fingerprints yet".
            reason = "onboarding not completed"
            config = load_onboarding_config(project_root)
            if config is not None:
                onboarding = config.get("onboarding") or {}
                if not onboarding.get("drift_check", True):
                    reason = "drift check is disabled (drift_check: false)"
                else:
                    stored = onboarding.get("fingerprints") or []
                    if not isinstance(stored, list) or not stored:
                        reason = "no fingerprints recorded yet (run `iterate refresh` to capture them)"
                    else:
                        reason = "drift check unavailable"
            print(
                json.dumps(
                    {
                        "project": str(project_root),
                        "available": False,
                        "reason": reason,
                        "drift": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        print(
            json.dumps(
                {
                    "project": str(project_root),
                    "available": True,
                    "drift": drift.has_drift,
                    "summary": drift.summary(),
                    "added": drift.added,
                    "removed": drift.removed,
                    "changed": drift.changed,
                    "unchanged": drift.unchanged,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if drift.has_drift else 0

    tui.intro(f"Iterate Skill — Fingerprint Verify / {project_root.name}")

    if drift is None:
        tui.info("Fingerprint verification unavailable.", indent=2)
        tui.hint(
            "Run 'iterate onboard' first, or enable drift_check in "
            "iterate.config.yaml.",
            indent=4,
        )
        return 0

    if drift.has_drift:
        tui.warning("Drift detected:", indent=2)
        if drift.added:
            tui.bullet(f"added: {', '.join(sorted(drift.added))}", indent=4)
        if drift.removed:
            tui.bullet(f"removed: {', '.join(sorted(drift.removed))}", indent=4)
        if drift.changed:
            tui.bullet(f"changed: {', '.join(sorted(drift.changed))}", indent=4)
        tui.empty_line()
        tui.hint(
            "Drift is non-blocking. Run 'iterate refresh' to resync the "
            "knowledge base when the tech stack changed.",
            indent=2,
        )
        return 1

    tui.success("No drift detected.", indent=2)
    if drift.unchanged:
        tui.hint(
            f"{len(drift.unchanged)} manifest(s) verified: "
            f"{', '.join(sorted(drift.unchanged))}.",
            indent=4,
        )
    return 0

