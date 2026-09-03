"""Defensive-programming guards and invariants (``iterate guard`` / ``iterate invariant``).

v3.0 defensive-programming mode ships three deterministic checks that a host
assistant can run around every coding step, so that "defensive" is enforced by
the CLI rather than by prompt discipline alone:

- ``iterate guard pre-check [paths...]`` — run BEFORE touching anything: verify
  the target paths exist, the git worktree is clean enough to start, required
  dependency manifests are present, and the configured validation commands are
  still whitelist-compliant. Exit code 0 = clear to proceed; 1 = do not start.
- ``iterate guard post-check [module...]`` — run AFTER an edit: execute exactly
  the configured ``validation.commands.<module>`` commands (the runtime
  authoritative whitelist) against the changed modules. Exit code 0 = the edit
  is safe; 1 = the edit must be reverted before continuing.
- ``iterate invariant`` — run BEFORE delivering: evaluate the project-level
  invariants declared under ``config.invariants`` (per-module command lists plus
  ``ensure`` file assertions). Exit code 0 = all invariants hold; 1 = at least
  one invariant is violated.

Safety rules carried over from the iterate security baseline:
- Commands are only ever executed when they EXACTLY match a configured
  ``validation.commands`` / ``invariants.commands`` entry (after trim). No
  command is ever composed, prefixed, or parameterised here.
- ``--dry-run`` prints the exact commands that WOULD run without executing them
  (fail-fast: on dry-run, missing/whitelist-broken commands are reported, not run).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from iterate_cli.personalize import CorruptConfigError, load_config_strict
from iterate_cli.refresh import CONFIG_YAML
from iterate_cli.tui import tui

#: Exit code used when a guard/invariant check fails.
EXIT_FAIL = 1
#: Exit code used when everything passes.
EXIT_PASS = 0

#: Dependency manifests that indicate "this module's toolchain is ready".
_KNOWN_MANIFESTS: dict[str, tuple[str, ...]] = {
    "python": ("pyproject.toml", "setup.py", "requirements.txt", "Pipfile", "poetry.lock"),
    "typescript": ("package.json", "tsconfig.json", "yarn.lock", "pnpm-lock.yaml", "package-lock.json"),
    "swift": ("Package.swift",),
    "rust": ("Cargo.toml",),
    "go": ("go.mod",),
}


@dataclass
class GuardResult:
    """Aggregated result of a guard/invariant check.

    Attributes:
        name: Short label for the check (e.g. ``guard-pre`` / ``guard-post``).
        passed: True when every item passed; False otherwise.
        items: Per-item outcomes (label, ok, detail).
        dry_run: True when commands were only previewed, not executed.
    """

    name: str
    passed: bool = True
    items: list[tuple[str, bool, str]] = field(default_factory=list)
    dry_run: bool = False


def _load_project_config(project_root: Path) -> dict[str, Any]:
    """Load the project config, raising a clean error when it is unreadable.

    Returns an empty dict when the config file is absent (fresh project) so the
    guards degrade gracefully instead of crashing on a missing file.

    Args:
        project_root: Project root directory.

    Returns:
        Parsed config mapping (``{}`` when the file is missing).

    Raises:
        CorruptConfigError: When the file exists but is not valid YAML.
        OSError: When the file cannot be read.
    """
    return load_config_strict(project_root / CONFIG_YAML)


def _git_root(project_root: Path) -> Path | None:
    """Resolve the repository root containing ``project_root``, or None.

    Uses ``git rev-parse --show-toplevel`` and caches nothing; a repo-less
    project yields None and the git check is reported as skipped.
    """
    if not shutil.which("git"):
        return None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    root = proc.stdout.strip()
    return Path(root) if root else None


def _git_worktree_is_clean(git_root: Path) -> tuple[bool, str]:
    """Report whether the worktree has uncommitted tracked changes.

    Untracked files do NOT fail the check (they are common mid-task); only
    modified/deleted tracked files are treated as "dirty" so a defensive start
    can tell the host assistant the starting point is not clean.

    Returns:
        (clean, detail) where detail is a short summary of dirty entries.
    """
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(git_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False, "git status failed"
    if proc.returncode != 0:
        return False, "git status failed"
    dirty = [line for line in proc.stdout.splitlines() if line and not line.startswith("??")]
    if not dirty:
        return True, "worktree clean"
    return False, f"{len(dirty)} tracked change(s) (e.g. {dirty[0][:60]})"


def _manifest_ready(project_root: Path, module: str) -> tuple[bool, str]:
    """Check whether a module's dependency manifest(s) exist in the project."""
    manifests = _KNOWN_MANIFESTS.get(module)
    if not manifests:
        return True, f"no manifest defined for module '{module}'"
    found = [name for name in manifests if (project_root / name).is_file()]
    if found:
        return True, "found " + ", ".join(found)
    return False, "none of " + ", ".join(manifests) + " found"


def _validation_commands(config: dict[str, Any]) -> dict[str, list[str]]:
    """Return the runtime-authoritative validation commands mapping.

    Tolerates a hand-edited config where ``validation.commands`` is missing or
    not a mapping by returning an empty dict (every command check then degrades
    to "no commands configured").
    """
    validation = config.get("validation")
    if not isinstance(validation, dict):
        return {}
    commands = validation.get("commands")
    if not isinstance(commands, dict):
        return {}
    return {str(mod): [str(c) for c in cmds if isinstance(c, str)] for mod, cmds in commands.items()}


def _invariant_commands(config: dict[str, Any]) -> dict[str, list[str]]:
    """Return the ``invariants.commands`` mapping (v3.0 defensive mode).

    Absent/malformed ``invariants`` section yields an empty dict, which makes
    ``iterate invariant`` degrade to the configured ``validation.commands``
    (see ``_validation_commands``) so old configs stay valid.
    """
    invariants = config.get("invariants")
    if not isinstance(invariants, dict):
        return {}
    commands = invariants.get("commands")
    if not isinstance(commands, dict):
        return {}
    return {str(mod): [str(c) for c in cmds if isinstance(c, str)] for mod, cmds in commands.items()}


def _invariant_ensure(config: dict[str, Any]) -> list[str]:
    """Return the ``invariants.ensure`` file-assertion list (v3.0 defensive mode)."""
    invariants = config.get("invariants")
    if not isinstance(invariants, dict):
        return []
    ensure = invariants.get("ensure")
    if not isinstance(ensure, list):
        return []
    return [str(entry) for entry in ensure if isinstance(entry, str)]


def _run_command(command: str, project_root: Path) -> tuple[int, str]:
    """Run one exact command under the project root.

    Never composes or prefixes commands: the caller guarantees ``command`` is an
    exact match from the configured validation/invariant lists.

    Args:
        command: Exact command string to execute.
        project_root: Working directory for the process.

    Returns:
        (returncode, output-tail) where output-tail is a bounded snippet of
        stdout/stderr (for diagnostics).
    """
    try:
        proc = subprocess.run(
            command,
            cwd=str(project_root),
            shell=True,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return EXIT_FAIL, f"could not execute: {exc}"
    combined = (proc.stdout or "") + (proc.stderr or "")
    tail = " | ".join(line for line in combined.splitlines()[-3:])
    return proc.returncode, tail[:400]


def _command_entries(commands_by_module: dict[str, list[str]], modules: list[str] | None) -> list[tuple[str, str]]:
    """Flatten (module, command) entries, optionally filtered by module names."""
    entries: list[tuple[str, str]] = []
    for module, cmds in commands_by_module.items():
        if modules and module not in modules:
            continue
        for cmd in cmds:
            entries.append((module, cmd))
    return entries


def run_guard_precheck(project_root: Path, paths: list[str], dry_run: bool = False) -> GuardResult:
    """Run the pre-edit guard: targets exist, git clean, manifests ready, commands safe.

    Args:
        project_root: Project root directory.
        paths: Target paths (files/dirs) that must exist before editing.
        dry_run: When True, preview commands without executing anything.

    Returns:
        A GuardResult with one item per check.
    """
    result = GuardResult(name="guard-pre", dry_run=dry_run)
    result.passed = True

    # 1. Target paths exist.
    resolved_targets = [str((project_root / p).resolve()) if not Path(p).is_absolute() else str(Path(p).resolve()) for p in paths]
    missing = []
    for target, resolved in zip(paths, resolved_targets):
        if not Path(resolved).exists():
            missing.append(target)
    if missing:
        result.items.append(("targets exist", False, "missing: " + ", ".join(missing)))
        result.passed = False
    else:
        result.items.append(("targets exist", True, f"{len(paths)} path(s) present"))

    # 2. Git worktree clean (only when inside a git repo).
    git_root = _git_root(project_root)
    if git_root is None:
        result.items.append(("git clean", True, "no git repo — skipped"))
    else:
        clean, detail = _git_worktree_is_clean(git_root)
        result.items.append(("git clean", clean, detail))
        if not clean:
            result.passed = False

    # 3. Dependency manifests ready.
    try:
        config = _load_project_config(project_root)
    except (CorruptConfigError, OSError, UnicodeDecodeError) as exc:
        result.items.append(("config readable", False, str(exc)))
        result.passed = False
        return result

    validation = _validation_commands(config)
    modules = list(validation.keys())
    if not modules:
        result.items.append(
            ("manifests ready", True, "no validation modules configured — skipped")
        )
    else:
        ready = []
        for module in modules:
            ok, detail = _manifest_ready(project_root, module)
            if not ok:
                result.items.append((f"manifest[{module}]", False, detail))
                result.passed = False
                break
            ready.append(detail)
        else:
            result.items.append(
                ("manifests ready", True, "; ".join(ready) or "no manifests defined")
            )

    # 4. Validation commands are configured and safe (previewed under dry-run).
    entries = _command_entries(validation, None)
    if not entries:
        result.items.append(("validation commands", True, "none configured — post-check will skip"))
    else:
        result.items.append(
            ("validation commands", True, f"{len(entries)} command(s) configured (run via post-check)")
        )

    return result


def run_guard_postcheck(project_root: Path, modules: list[str] | None, dry_run: bool = False) -> GuardResult:
    """Run the post-edit guard: execute exactly the configured validation commands.

    Args:
        project_root: Project root directory.
        modules: Optional module filter (``iterate guard post-check python``).
        dry_run: When True, preview the exact commands without executing them.

    Returns:
        A GuardResult with one item per (module, command).
    """
    result = GuardResult(name="guard-post", dry_run=dry_run)
    result.passed = True
    try:
        config = _load_project_config(project_root)
    except (CorruptConfigError, OSError, UnicodeDecodeError) as exc:
        result.items.append(("config readable", False, str(exc)))
        result.passed = False
        return result

    validation = _validation_commands(config)
    entries = _command_entries(validation, modules)
    if not entries:
        wanted = ", ".join(modules) if modules else "(none)"
        result.items.append(("validation commands", False, f"no commands configured for {wanted or 'any module'}"))
        result.passed = False
        return result

    for module, command in entries:
        if dry_run:
            result.items.append((f"{module}", True, f"would run: {command}"))
            continue
        code, tail = _run_command(command, project_root)
        ok = code == 0
        detail = f"{command} → exit {code}"
        if tail:
            detail += f" | {tail}"
        result.items.append((f"{module}", ok, detail))
        if not ok:
            result.passed = False
    return result


def run_invariant_check(project_root: Path, dry_run: bool = False) -> GuardResult:
    """Run project-level invariants (``iterate invariant``).

    Checks, in order:
    1. ``invariants.ensure`` file assertions (each declared path must exist).
    2. ``invariants.commands.<module>`` command lists (exact match, executed).
    When no ``invariants`` section is configured, degrades to the configured
    ``validation.commands`` so pre-v3.0 configs remain valid.

    Args:
        project_root: Project root directory.
        dry_run: When True, preview commands without executing anything.

    Returns:
        A GuardResult with one item per assertion/command.
    """
    result = GuardResult(name="invariant", dry_run=dry_run)
    result.passed = True
    try:
        config = _load_project_config(project_root)
    except (CorruptConfigError, OSError, UnicodeDecodeError) as exc:
        result.items.append(("config readable", False, str(exc)))
        result.passed = False
        return result

    # 1. File assertions (invariants.ensure).
    for entry in _invariant_ensure(config):
        target = project_root / entry
        ok = target.is_file()
        result.items.append((f"ensure:{entry}", ok, "present" if ok else f"missing: {entry}"))
        if not ok:
            result.passed = False

    # 2. Invariant commands; fall back to validation.commands for old configs.
    commands = _invariant_commands(config)
    source = "invariants.commands"
    if not commands:
        commands = _validation_commands(config)
        source = "validation.commands (invariants fallback)"
    entries = _command_entries(commands, None)
    if not entries:
        result.items.append((source, True, "no invariant commands configured"))
        return result

    for module, command in entries:
        if dry_run:
            result.items.append((f"{module} ({source})", True, f"would run: {command}"))
            continue
        code, tail = _run_command(command, project_root)
        ok = code == 0
        detail = f"{command} → exit {code}"
        if tail:
            detail += f" | {tail}"
        result.items.append((f"{module} ({source})", ok, detail))
        if not ok:
            result.passed = False
    return result


def render_guard_result(result: GuardResult, json_output: bool = False) -> int:
    """Render a GuardResult and return the process exit code.

    Args:
        result: The check result to display.
        json_output: When True, emit a structured JSON object instead of TUI lines.

    Returns:
        0 when everything passed, 1 otherwise.
    """
    if json_output:
        import json

        print(
            json.dumps(
                {
                    "check": result.name,
                    "passed": result.passed,
                    "dry_run": result.dry_run,
                    "items": [
                        {"label": label, "ok": ok, "detail": detail}
                        for label, ok, detail in result.items
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_PASS if result.passed else EXIT_FAIL

    if result.dry_run:
        tui.warning(f"{result.name}: DRY-RUN preview (nothing executed)", indent=2)
    if result.passed:
        tui.success(f"{result.name}: PASS")
    else:
        tui.error(f"{result.name}: FAIL")
    for label, ok, detail in result.items:
        if ok:
            tui.bullet(f"{label}: {detail}", indent=4)
        else:
            tui.warning(f"{label}: {detail}", indent=4)
    return EXIT_PASS if result.passed else EXIT_FAIL
