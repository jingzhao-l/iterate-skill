#!/usr/bin/env python3
"""Iterate skill CLI.

Inspired by ui-ux-pro-max-skill's uipro-cli, this script installs the skill
into AI assistants' skills directories and provides helpers to manage the
project-level iterate.config.yaml.

Usage:
    python scripts/install.py --ai trae --target /path/to/project
    python scripts/install.py install --ai all --target /path/to/project
    python scripts/install.py config --init --target /path/to/project
    python scripts/install.py config --set goal="Improve code quality"
    python scripts/install.py config --set dimensions='[correctness, security]'
    python scripts/install.py config --interactive
    python scripts/install.py uninstall --ai trae --target /path/to/project --yes
    python scripts/install.py validate --target /path/to/project
    python scripts/install.py update --ai trae --target /path/to/project --token ghp_xxx
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

import yaml

# Type alias for the input callable used across interactive prompts so tests
# can inject mock responses without touching stdin.
InputFunc = Callable[[str], str]

# --- Lightweight TUI helpers (skills.sh style) -----------------------------
# install.py runs as a standalone script (often before iterate_cli is pip
# installed), so we cannot hard-depend on iterate_cli.tui. We try to import
# rich for nicer output and gracefully fall back to plain print when rich is
# unavailable. All output is funneled through these helpers so the install /
# update / uninstall / config flows share a consistent visual style with the
# iterate CLI commands.
try:
    from rich.console import Console
    from rich.theme import Theme
    _THEME = Theme({
        "iterate.primary": "bold cyan",
        "iterate.success": "green",
        "iterate.error": "bold red",
        "iterate.warning": "yellow",
        "iterate.hint": "dim",
        "iterate.title": "bold cyan",
        "iterate.label": "bold",
    })
    # Respect FORCE_COLOR like other CLI tools; default to auto-detect (TTY).
    _force_color = os.environ.get("FORCE_COLOR", "")
    if _force_color in ("", "0", "false", "False"):
        _force_terminal = None
    else:
        _force_terminal = True
    _CONSOLE = Console(theme=_THEME, force_terminal=_force_terminal)
    _ERR_CONSOLE = Console(theme=_THEME, stderr=True, force_terminal=_force_terminal)
    _RICH_AVAILABLE = True
except ImportError:
    _CONSOLE = None
    _ERR_CONSOLE = None
    _RICH_AVAILABLE = False


def _tui_print(message: str, *, style: str = "", stderr: bool = False) -> None:
    """Print a styled message, falling back to plain print without rich."""
    if not _RICH_AVAILABLE:
        if stderr:
            print(message, file=sys.stderr)
        else:
            print(message)
        return
    console = _ERR_CONSOLE if stderr else _CONSOLE
    if style:
        console.print(f"[{style}]{message}[/]")
    else:
        console.print(message)


def _intro(title: str, subtitle: str = "") -> None:
    """skills.sh-style intro banner."""
    _tui_print("")
    _tui_print(f"◆ {title}", style="iterate.primary")
    if subtitle:
        _tui_print(f"  {subtitle}", style="iterate.hint")
    _tui_print("")


def _success(message: str) -> None:
    """Success line with check mark."""
    _tui_print(f"✓ {message}", style="iterate.success")


def _error(message: str) -> None:
    """Error line to stderr with cross mark."""
    _tui_print(f"✗ {message}", style="iterate.error", stderr=True)


def _warning(message: str) -> None:
    """Warning line."""
    _tui_print(f"⚠  {message}", style="iterate.warning")


def _hint(message: str) -> None:
    """Dim hint line."""
    _tui_print(message, style="iterate.hint")


def _key_value(key: str, value: str) -> None:
    """Aligned key: value line."""
    padded = f"{key}:".ljust(18)
    if _RICH_AVAILABLE:
        _CONSOLE.print(f"  [iterate.label]{padded}[/] {value}")
    else:
        print(f"  {padded} {value}")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences for width calculation."""
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _strip_markup(text: str) -> str:
    """Remove rich markup tags for the plain-text fallback."""
    import re

    return re.sub(r"\[/?[a-zA-Z0-9_\-:. ]*\]", "", text)


def _frame_box(title: str, lines: list[str]) -> None:
    """Print a skills.sh-style framed box.

    Uses single-line box drawing characters so the frame stays aligned
    across terminals that render these glyphs consistently.
    """
    visible_lines = [_strip_markup(_strip_ansi(line)) for line in lines]
    max_len = max(len(title), *(len(line) for line in visible_lines), 1)
    inner_width = max_len + 2

    top = f"┌─ {title} {'─' * max(0, inner_width - len(title) - 2)}┐"
    bottom = f"└{'─' * (inner_width + 1)}┘"

    if _RICH_AVAILABLE:
        _CONSOLE.print(f"[iterate.primary]{top}[/]")
        for line, visible in zip(lines, visible_lines):
            padding = " " * (inner_width - len(visible))
            _CONSOLE.print(f"[iterate.primary]│[/] {line}{padding}[iterate.primary]│[/]")
        _CONSOLE.print(f"[iterate.primary]{bottom}[/]")
    else:
        print(top)
        for line, visible in zip(lines, visible_lines):
            plain_line = _strip_markup(line)
            padding = " " * (inner_width - len(visible))
            print(f"│ {plain_line}{padding}│")
        print(bottom)


GITHUB_REPO_OWNER = "jingzhao-l"
GITHUB_REPO_NAME = "iterate-skill"
RELEASE_API_URL = (
    f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/latest"
)
CHECKSUMS_ASSET_NAME = "SHA256SUMS.txt"
EXPECTED_TARBALL_FILENAME = "iterate-skill.tar.gz"

SUPPORTED_AI: dict[str, str] = {
    # Universal / 通用 AI 编程工具（skills.sh 热门支持）
    "claude": ".claude/skills/iterate",
    "claude-code": ".claude/skills/iterate",
    "cursor": ".cursor/skills/iterate",
    "trae": ".trae/skills/iterate",
    "windsurf": ".windsurf/skills/iterate",
    "copilot": ".github/skills/iterate",
    "codex": ".codex/skills/iterate",
    "gemini": ".gemini/skills/iterate",
    "gemini-cli": ".gemini/skills/iterate",
    "opencode": ".opencode/skills/iterate",
    "aider": ".aider/skills/iterate",
    "aiderdesk": ".aiderdesk/skills/iterate",
    "zed": ".zed/skills/iterate",
    "warp": ".warp/skills/iterate",
    "continue": ".continue/skills/iterate",
    "cline": ".cline/skills/iterate",
    "roocode": ".roo/skills/iterate",
    "qoder": ".qoder/skills/iterate",
    "augment": ".augment/skills/iterate",
    "openclaw": "skills/iterate",
    "autohand": ".autohand/skills/iterate",
    "bob": ".bob/skills/iterate",
    "codearts": ".codeartsdoer/skills/iterate",
    "antigravity": ".antigravity/skills/iterate",
    "amp": ".amp/skills/iterate",
    "deepagents": ".deepagents/skills/iterate",
    "kimi": ".kimi/skills/iterate",
    "astral": ".astral/skills/iterate",
}

# 显示名称映射：让交互菜单更友好
AI_DISPLAY_NAMES: dict[str, str] = {
    "claude": "Claude",
    "claude-code": "Claude Code",
    "cursor": "Cursor",
    "trae": "Trae",
    "windsurf": "Windsurf",
    "copilot": "GitHub Copilot",
    "codex": "Codex",
    "gemini": "Gemini",
    "gemini-cli": "Gemini CLI",
    "opencode": "OpenCode",
    "aider": "Aider",
    "aiderdesk": "AiderDesk",
    "zed": "Zed",
    "warp": "Warp",
    "continue": "Continue",
    "cline": "Cline",
    "roocode": "Roo Code",
    "qoder": "Qoder",
    "augment": "Augment",
    "openclaw": "OpenClaw",
    "autohand": "Autohand Code CLI",
    "bob": "IBM Bob",
    "codearts": "CodeArts Agent",
    "antigravity": "Antigravity",
    "amp": "Amp",
    "deepagents": "Deep Agents",
    "kimi": "Kimi Code CLI",
    "astral": "Astral",
}

REQUIRED_FILES = [
    "SKILL.md",
    "config/iterate.config.yaml",
    "config/config.schema.json",
    "config/dimensions.yaml",
    "config/dimensions",
    "scripts/validate.py",
    "scripts/requirements.txt",
    "templates/iterate-decisions.template.md",
    # v2.0.0: CLI onboarding system (iterate onboard / personalize / refresh).
    "iterate_cli",
    "pyproject.toml",
    "templates/ITERATE.template.md",
    "templates/onboarding-playbook.md",
]

OPTIONAL_FILES = [
    "README.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "CHANGELOG.md",
    "examples/python-project.md",
    "examples/swift-project.md",
    "examples/typescript-project.md",
    "tools/SKILL.trae.md",
    "tools/SKILL.claude.md",
    "tools/SKILL.cursor.md",
]

AI_CHOICES = list(SUPPORTED_AI.keys()) + ["all"]

DEFAULT_CONFIG_PATH = Path("config/iterate.config.yaml")

MIN_ROUNDS = 1
MAX_ROUNDS = 50

DIMENSION_CHOICES = [
    "correctness",
    "security",
    "performance",
    "architecture",
    "style-tests",
    "tech-debt",
    "spec-compliance",
    "frontend-backend",
    "ui-ux",
]

LANGUAGE_CHOICES = ["zh", "en"]
SCOPE_CHOICES = ["full", "changed-only"]


def copy_skill_files(
    source: Path, destination: Path, dry_run: bool, force: bool
) -> list[str]:
    """Copy skill files from source to destination."""
    copied: list[str] = []
    all_files = REQUIRED_FILES + OPTIONAL_FILES

    for relative in all_files:
        src = source / relative
        if not src.exists():
            if relative in REQUIRED_FILES:
                raise FileNotFoundError(f"Required skill file missing: {src}")
            continue

        dst = destination / relative
        if dry_run:
            copied.append(str(dst))
            _hint(f"[dry-run] Would copy: {relative} -> {dst}")
            continue

        if dst.exists() and not force:
            _hint(f"Skipped (already exists, use --force): {dst}")
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists() and force:
                shutil.rmtree(dst)
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        copied.append(str(dst))

    return copied


def detect_installed_assistants(effective_target: Path) -> list[str]:
    """Detect which supported AI assistants appear to be installed.

    Heuristic: check whether the assistant's configuration / skill parent
    directory exists under ``effective_target``. A tool is considered
    installed if its parent directory (e.g. ``.trae/skills``) exists.

    Args:
        effective_target: Base directory to inspect (home or project).

    Returns:
        Sorted list of assistant keys that appear installed.
    """
    found: list[str] = []
    for assistant, relative_dir in SUPPORTED_AI.items():
        # Use the skill directory's parent as the marker (e.g. .trae/skills).
        marker = effective_target / relative_dir
        if marker.parent.exists():
            found.append(assistant)
    return sorted(set(found))


def _prompt_multi_select(
    options: list[str],
    input_func: InputFunc,
    title: str = "Select items",
    default_all: bool = True,
    preselected: set[str] | None = None,
) -> list[str]:
    """Present a simple text-based multi-select prompt.

    This intentionally avoids extra dependencies (e.g. simple-term-menu)
    so the installer remains a single standalone script. The interaction
    mimics skills.sh: numbers toggle selection, Enter confirms.

    Args:
        options: List of option identifiers (e.g. assistant keys).
        input_func: Callable used to read user input.
        title: Prompt title.
        default_all: Whether all options start selected (ignored when
            ``preselected`` is provided).
        preselected: Optional set of options to start selected (e.g. the
            auto-detected tools). When provided, only these are pre-checked.

    Returns:
        List of selected option identifiers.
    """
    if preselected is not None:
        selected = set(preselected) & set(options)
    else:
        selected = set(options) if default_all else set()

    while True:
        _tui_print(f"\n{title}", style="iterate.primary")
        _hint("Enter numbers to toggle (comma-separated), or press Enter to confirm.")
        _hint("Tip: prefix with 'a' to select all, 'n' to select none.")
        for i, opt in enumerate(options, 1):
            display = AI_DISPLAY_NAMES.get(opt, opt)
            marker = "[✓]" if opt in selected else "[ ]"
            _tui_print(f"  {marker} {i}. {display}", style="iterate.label" if opt in selected else "")

        raw = input_func("  \u2514 ").strip()
        if not raw:
            break

        if raw.lower() == "a":
            selected = set(options)
            continue
        if raw.lower() == "n":
            selected = set()
            continue

        changed = False
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                idx = int(part) - 1
            except ValueError:
                _warning(f"Invalid input: '{part}'")
                continue
            if not (0 <= idx < len(options)):
                _warning(f"Out of range: '{part}'")
                continue
            opt = options[idx]
            if opt in selected:
                selected.remove(opt)
            else:
                selected.add(opt)
            changed = True

        if not changed:
            # User typed something but nothing valid; keep looping.
            _hint("No valid selection; try again or press Enter to confirm.")

    return sorted(selected)


class _ArrowSelectState:
    """State for the arrow-key multi-select menu.

    The visible list is ``options + [None]`` where ``None`` is the trailing
    "Done" confirmation row. Arrow keys move the highlight, Space / Enter
    toggle the current option (or confirm when on the Done row), and ``q``
    cancels. Kept as a plain state machine so the key-handling logic can be
    unit-tested without a TTY.
    """

    def __init__(
        self,
        options: list[str],
        default_all: bool = True,
        preselected: set[str] | None = None,
    ) -> None:
        self.options = list(options)
        self.rows: list[str | None] = self.options + [None]
        self.index = 0
        if preselected is not None:
            # Pre-select only the given options (e.g. auto-detected tools).
            # Options not in the preselected set are still shown but start
            # unchecked, so the user must explicitly opt in to them.
            self.selected: set[str] = set(preselected) & set(self.options)
        else:
            self.selected = set(self.options) if default_all else set()
        self.finished = False

    def move(self, delta: int) -> None:
        """Move the highlight by ``delta`` (wrap around)."""
        self.index = (self.index + delta) % len(self.rows)

    def toggle_current(self) -> None:
        """Toggle the highlighted option; on the Done row, finish instead."""
        opt = self.rows[self.index]
        if opt is None:
            self.finished = True
            return
        if opt in self.selected:
            self.selected.remove(opt)
        else:
            self.selected.add(opt)

    def cancel(self) -> None:
        """Cancel the selection (empty result, finished)."""
        self.finished = True
        self.selected = set()

    @property
    def result(self) -> list[str]:
        """Ordered, sorted list of selected option identifiers."""
        return sorted(self.selected)


def _read_arrow_key(stdin) -> str | None:
    """Decode one raw keypress into a command name.

    Commands: ``up``, ``down``, ``toggle`` (Space / Enter), ``cancel`` (q/Q).
    Returns ``None`` for unrecognized keys. Raises ``KeyboardInterrupt`` on
    Ctrl+C so the caller can restore the terminal and cancel.
    """
    ch = stdin.read(1)
    if ch == "\x1b":
        # Escape sequence: ESC [ A (up) / B (down).
        seq = stdin.read(2)
        if seq == "[A":
            return "up"
        if seq == "[B":
            return "down"
        return None
    if ch in ("\r", "\n", " "):
        return "toggle"
    if ch in ("q", "Q"):
        return "cancel"
    if ch == "\x03":
        raise KeyboardInterrupt
    return None


def _render_arrow_select(state: _ArrowSelectState, title: str) -> str:
    """Render the arrow-select menu as an ANSI string."""
    lines = [
        f"\x1b[36m◆ {title}\x1b[0m",
        "\x1b[2m    ↑/↓ 移动 · 空格/回车 勾选 · Done 确认 · q 取消\x1b[0m",
    ]
    for i, opt in enumerate(state.rows):
        if opt is None:
            marker = "\x1b[36m→\x1b[0m" if i == state.index else "  "
            lines.append(f"{marker} \x1b[1mDone / 完成\x1b[0m")
        else:
            display = AI_DISPLAY_NAMES.get(opt, opt)
            check = "\x1b[32m◉\x1b[0m" if opt in state.selected else "\x1b[90m○\x1b[0m"
            if i == state.index:
                lines.append(f"\x1b[7m  {check} {display}\x1b[0m")
            else:
                lines.append(f"  {check} {display}")
    return "\n".join(lines)


def _prompt_arrow_multi_select(
    options: list[str],
    title: str = "Select items",
    default_all: bool = True,
    preselected: set[str] | None = None,
) -> list[str]:
    """Present an arrow-key multi-select menu (requires a TTY).

    Uses raw terminal mode to read arrow keys, Space and Enter. On a non-TTY
    stdin (pipes, tests) this function is not used; callers fall back to
    ``_prompt_multi_select`` instead.

    Args:
        options: List of option identifiers (e.g. assistant keys).
        title: Menu title.
        default_all: Whether all options start selected (ignored when
            ``preselected`` is provided).
        preselected: Optional set of options to start selected (e.g. the
            auto-detected tools). When provided, only these are pre-checked.

    Returns:
        List of selected option identifiers (empty if cancelled).
    """
    import sys as _sys
    import termios
    import tty

    state = _ArrowSelectState(options, default_all, preselected)

    def redraw() -> None:
        total_lines = len(state.rows) + 2
        _sys.stdout.write(f"\x1b[{total_lines}A")
        _sys.stdout.write("\x1b[0J")
        _sys.stdout.write(_render_arrow_select(state, title))
        _sys.stdout.flush()

    _sys.stdout.write(_render_arrow_select(state, title))
    _sys.stdout.flush()

    fd = _sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while not state.finished:
            cmd = _read_arrow_key(_sys.stdin)
            if cmd is None:
                continue
            if cmd == "up":
                state.move(-1)
            elif cmd == "down":
                state.move(1)
            elif cmd == "toggle":
                state.toggle_current()
            elif cmd == "cancel":
                state.cancel()
            redraw()
    except KeyboardInterrupt:
        state.cancel()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        _sys.stdout.write("\n")
        _sys.stdout.flush()

    return state.result


def interactive_select_assistants(
    effective_target: Path,
    input_func: InputFunc = input,
) -> list[str]:
    """Interactively select AI assistants to install to.

    Auto-detects the AI tools installed on the user's machine (by inspecting
    the home directory) and pre-selects them. Tools that are not auto-detected
    are still listed so the user can pick them manually. When no tool is
    detected, all supported tools are offered for manual selection.

    On an interactive TTY an arrow-key / Space multi-select menu is shown;
    otherwise it falls back to the number-based ``_prompt_multi_select`` so
    the behavior stays testable.

    Args:
        effective_target: Unused for detection (kept for call compatibility);
            detection always inspects the user's home directory.
        input_func: Callable used to read user input (non-TTY fallback).

    Returns:
        Sorted list of selected assistant keys. Empty list means the user
        cancelled or selected nothing.
    """
    installed = detect_installed_assistants(Path.home())
    if installed:
        _tui_print("检测到本机已安装的 AI 工具 / Detected AI assistants:", style="iterate.primary")
        for assistant in installed:
            _success(f"  {AI_DISPLAY_NAMES.get(assistant, assistant)}")
        options = installed + sorted(a for a in SUPPORTED_AI if a not in installed)
        # Pre-select only the detected (installed) tools; the rest are shown
        # but unchecked so the user can opt in explicitly. This matches the
        # "detect and pre-select" intent instead of pre-selecting every tool.
        preselected = set(installed)
    else:
        _warning("未检测到已安装的 AI 工具 / No supported AI assistants detected.")
        _hint("可手动选择要安装的工具 / You can select tools manually below.")
        options = sorted(SUPPORTED_AI.keys())
        preselected = set()

    title = "选择要安装的 AI 工具 / Select AI assistants to install to"
    if sys.stdin.isatty():
        return _prompt_arrow_multi_select(options, title, preselected=preselected)
    return _prompt_multi_select(options, input_func, title, preselected=preselected)


def install_command(
    ai: str | None,
    target: Path,
    dry_run: bool,
    source: Path,
    force: bool,
    global_install: bool,
    input_func: InputFunc = input,
) -> int:
    """Install the skill for one or more AI assistants.

    Args:
        ai: Target assistant key, "all", or None for interactive selection.
        target: Project or home directory.
        dry_run: Print what would be copied without copying.
        source: Source directory containing skill files.
        force: Overwrite existing skill files.
        global_install: Install into home directory instead of project.
        input_func: Callable used to read user input (interactive mode).

    Returns:
        Exit code: 0 for success, 1 for error/cancel.
    """
    effective_target = Path.home() if global_install else target
    mode_label = " (global)" if global_install else ""

    if ai is None:
        selected = interactive_select_assistants(effective_target, input_func)
        if not selected:
            _hint("No assistants selected. Installation cancelled.")
            # Non-zero so the npx wrapper does not report a false success.
            return 1
        targets = selected
    else:
        targets = list(SUPPORTED_AI.keys()) if ai == "all" else [ai]

    installed: list[tuple[str, str, Path]] = []
    for assistant in targets:
        relative_dir = SUPPORTED_AI[assistant]
        destination = effective_target / relative_dir

        if dry_run:
            _hint(f"[dry-run] Would install for {assistant}{mode_label} into {destination}")
        else:
            _tui_print(f"Installing for {assistant}{mode_label} into {destination}", style="iterate.primary")

        copied = copy_skill_files(source, destination, dry_run, force)
        for item in copied:
            _hint(item)

        if copied or dry_run:
            display_name = AI_DISPLAY_NAMES.get(assistant, assistant)
            installed.append((assistant, display_name, destination))

    if dry_run:
        _success("Dry run complete; no files were copied.")
        return 0

    _success("Installation complete.")
    if installed:
        summary_lines: list[str] = [
            f"[iterate.success]✓[/] Installed to {len(installed)} assistant(s){mode_label}",
            "",
        ]
        for _assistant, display_name, destination in installed:
            summary_lines.append(
                f"  [iterate.label]{display_name}:[/] {destination}"
            )
        summary_lines.append("")
        summary_lines.append(
            "[iterate.hint]Run `iterate onboard` in your project to initialize.[/]"
        )
        _frame_box("Installation Summary", summary_lines)
    return 0


def uninstall_command(
    ai: str | None,
    target: Path,
    global_install: bool,
    yes: bool = False,
    input_func: InputFunc = input,
) -> int:
    """Remove the skill for one or more AI assistants.

    Args:
        ai: Target assistant key, "all", or None for auto-detect.
        target: Project or home directory.
        global_install: Uninstall from home directory instead of project.
        yes: Skip confirmation prompt.
        input_func: Callable used to read user input.

    Returns:
        Exit code: 0 for success, 1 for error/cancel.
    """
    effective_target = Path.home() if global_install else target
    mode_label = " (global)" if global_install else ""

    if ai is None:
        # Auto-detect existing iterate-skill installations.
        existing_keys = [
            assistant
            for assistant in SUPPORTED_AI
            if (effective_target / SUPPORTED_AI[assistant]).exists()
        ]
        if not existing_keys:
            _warning(f"No iterate-skill installation found in {effective_target}{mode_label}")
            return 0
        targets = existing_keys
    else:
        targets = list(SUPPORTED_AI.keys()) if ai == "all" else [ai]

    existing = [
        (assistant, effective_target / SUPPORTED_AI[assistant])
        for assistant in targets
        if (effective_target / SUPPORTED_AI[assistant]).exists()
    ]
    if not existing:
        _warning(f"No iterate-skill installation found in {effective_target}{mode_label}")
        return 0

    if not yes:
        _tui_print("The following installations will be removed:", style="iterate.primary")
        for assistant, destination in existing:
            _hint(f"- {assistant}{mode_label}: {destination}")
        answer = input_func("  \u2514 Proceed? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            _hint("Uninstall cancelled.")
            return 0

    for assistant, destination in existing:
        shutil.rmtree(destination)
        _success(f"Uninstalled {assistant}{mode_label}: {destination}")

    _success("Uninstall complete.")
    return 0


def _fetch_latest_release_info(token: str | None) -> dict[str, str] | None:
    """Query GitHub API for the latest release tag, tarball URL and checksum asset URL."""
    request = urllib.request.Request(RELEASE_API_URL, method="GET")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None

    if not isinstance(data, dict):
        return None
    tag = data.get("tag_name")
    if not isinstance(tag, str):
        return None

    tarball_url: str | None = None
    checksum_url: str | None = None
    assets = data.get("assets")
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = asset.get("name")
            asset_url = asset.get("browser_download_url")
            if not isinstance(asset_url, str):
                continue
            if name == EXPECTED_TARBALL_FILENAME:
                tarball_url = asset_url
            elif name == CHECKSUMS_ASSET_NAME:
                checksum_url = asset_url

    if not tarball_url:
        # Fallback to GitHub auto-generated tarball only if the project hasn't
        # uploaded a deterministic tarball asset yet (legacy releases).
        tarball_url = data.get("tarball_url")

    if not isinstance(tarball_url, str):
        return None

    result: dict[str, str] = {"tag": tag, "tarball_url": tarball_url}
    if checksum_url:
        result["checksum_url"] = checksum_url
    return result


def _fetch_latest_release_tag(token: str | None) -> str | None:
    """Query GitHub API for the latest release tag name."""
    info = _fetch_latest_release_info(token)
    return info["tag"] if info else None


def _detect_installed_assistants(target: Path) -> list[str]:
    """Return assistants that already have an iterate skill installed in target."""
    installed: list[str] = []
    for assistant, relative_dir in SUPPORTED_AI.items():
        if (target / relative_dir).exists():
            installed.append(assistant)
    return installed


def _safe_extractall(tar: tarfile.TarFile, path: Path) -> None:
    """Extract a tarball safely, preventing path traversal outside ``path``."""
    if hasattr(tarfile, "data_filter"):
        tar.extractall(path=path, filter="data")
        return

    # Fallback for Python < 3.12: validate each member resolves inside path.
    for member in tar.getmembers():
        member_path = (path / member.name).resolve()
        if not str(member_path).startswith(str(path.resolve()) + "/"):
            raise tarfile.TarError(f"Suspicious member path: {member.name}")
    tar.extractall(path=path)


def _download_bytes(url: str, token: str | None, timeout: int = 30) -> bytes | None:
    """Download raw bytes from a URL, optionally using a GitHub token."""
    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/vnd.github+json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError):
        return None


def _parse_checksum(checksum_text: bytes, filename: str) -> str | None:
    """Parse a SHA256SUMS-style file and return the hash for ``filename``."""
    text = checksum_text.decode("utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts
        # Handle both "HASH  filename" and "HASH *filename" formats.
        name = name.lstrip("*").strip()
        if name == filename:
            return digest.strip()
    return None


def _download_release_source(
    tarball_url: str, checksum_url: str | None, token: str | None
) -> Path | None:
    """Download a release tarball, verify checksum (mandatory), and extract it.

    Refuses to proceed if ``checksum_url`` is None or if the checksum
    cannot be verified. This prevents supply-chain attacks via
    unverified tarballs.
    """
    if not checksum_url:
        _error("Refusing to download release: SHA256SUMS.txt URL is required for integrity verification.")
        return None

    data = _download_bytes(tarball_url, token)
    if data is None:
        return None

    checksum_data = _download_bytes(checksum_url, token)
    if not checksum_data:
        _error("Refusing to proceed: could not download checksum file.")
        return None

    expected_hash = _parse_checksum(checksum_data, EXPECTED_TARBALL_FILENAME)
    if not expected_hash:
        _error(f"Refusing to proceed: {EXPECTED_TARBALL_FILENAME} not found in checksum file.")
        return None

    actual_hash = hashlib.sha256(data).hexdigest()
    if actual_hash.lower() != expected_hash.lower():
        _error(f"Checksum mismatch for release tarball: expected {expected_hash}, got {actual_hash}")
        return None
    _success("Release tarball checksum verified.")

    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            temp_dir = Path(tempfile.mkdtemp(prefix="iterate-release-"))
            _safe_extractall(tar, temp_dir)
            extracted = [p for p in temp_dir.iterdir() if p.is_dir()]
            return extracted[0] if extracted else None
    except (tarfile.TarError, OSError):
        return None


def update_command(
    ai: str | None,
    target: Path,
    source: Path,
    token: str | None,
    force: bool,
    global_install: bool,
    yes: bool = False,
) -> int:
    """Refresh installed skill files from the latest GitHub release or local source."""
    effective_target = Path.home() if global_install else target
    mode_label = " (global)" if global_install else ""

    release_info = _fetch_latest_release_info(token)
    release_source: Path | None = None
    if release_info:
        _tui_print(f"Latest GitHub release: {release_info['tag']}", style="iterate.primary")
        _hint(f"This will download code from https://github.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases and install it into your AI assistant skill directories.")
        has_checksum = "checksum_url" in release_info
        if not has_checksum:
            _error("Error: no SHA256SUMS.txt asset found for this release. Refusing to download without integrity verification. Falling back to local source.")
            release_source = None
        else:
            if not yes:
                answer = input("Continue? [y/N]: ").strip().lower()
                if answer not in ("y", "yes"):
                    _hint("Update cancelled.")
                    return 0
            _hint("Downloading release source...")
            release_source = _download_release_source(
                release_info["tarball_url"],
                release_info["checksum_url"],
                token,
            )
            if release_source:
                _hint(f"Using release source: {release_source}")
            else:
                _warning("Could not download release source; falling back to local source...")
    else:
        _warning("Could not reach GitHub releases; refreshing from local source...")

    update_source = release_source if release_source else source

    if ai is None:
        assistants = detect_installed_assistants(effective_target)
        if not assistants:
            _warning(f"No iterate-skill installation found in {effective_target}{mode_label}")
            _hint("Run 'install --ai <assistant>' first, or use 'update --ai <assistant>'.")
            if release_source:
                shutil.rmtree(release_source)
            return 1
        _tui_print(f"Updating detected installations: {', '.join(assistants)}", style="iterate.primary")
    elif ai == "all":
        assistants = list(SUPPORTED_AI.keys())
    else:
        assistants = [ai]

    try:
        for assistant in assistants:
            install_command(
                ai=assistant,
                target=target,
                dry_run=False,
                source=update_source,
                force=force,
                global_install=global_install,
            )
    finally:
        if release_source:
            shutil.rmtree(release_source, ignore_errors=True)

    _success("Update complete.")
    return 0


def _run_validate_subprocess(
    source: Path, config_path: Path, schema_path: Path, dimensions_dir: Path
) -> list[str]:
    """Run ``scripts/validate.py config`` as a subprocess and return errors.

    Uses subprocess instead of ``importlib`` dynamic execution so that
    static analyzers do not flag the skill for ``exec_module`` usage.
    The validate script is part of this skill's own source tree.
    """
    import subprocess

    validate_script = source / "scripts" / "validate.py"
    if not validate_script.exists():
        return [f"validate.py not found at {validate_script}"]

    cmd = [
        sys.executable,
        str(validate_script),
        "config",
        str(config_path),
        str(schema_path),
        str(dimensions_dir),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"Failed to run validate.py: {exc}"]

    if result.returncode == 0:
        return []

    errors: list[str] = []
    for line in result.stderr.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            errors.append(stripped[2:])
        elif stripped and not stripped.startswith("Validation failed"):
            errors.append(stripped)
    return errors if errors else ["Validation failed (see stderr for details)"]


def validate_command(target: Path, source: Path) -> int:
    """Validate the project-level iterate.config.yaml."""
    config_path = target / "iterate.config.yaml"
    schema_path = source / "config" / "config.schema.json"
    dimensions_dir = source / "config" / "dimensions"

    if not config_path.exists():
        _warning(f"No project config found at {config_path}")
        return 1

    errors = _run_validate_subprocess(source, config_path, schema_path, dimensions_dir)
    if errors:
        _error(f"Validation failed for {config_path}")
        for error in errors:
            _hint(f"- {error}")
        return 1

    _success(f"Validation passed: {config_path}")
    return 0


def _validate_project_config(target: Path, source: Path) -> list[str]:
    """Validate the saved project config and return errors."""
    config_path = target / "iterate.config.yaml"
    schema_path = source / "config" / "config.schema.json"
    dimensions_dir = source / "config" / "dimensions"
    return _run_validate_subprocess(source, config_path, schema_path, dimensions_dir)


YAML_BOOLEAN_ALIASES = {"true", "false", "True", "False", "TRUE", "FALSE"}


def parse_value(raw: str) -> object:
    """Parse a config value from CLI string using YAML/JSON semantics.

    YAML 1.1 treats yes/no/on/off as booleans; we keep only explicit
    true/false as bool to avoid surprising behavior in free-form strings.
    """
    stripped = raw.strip()
    if not stripped:
        return ""

    try:
        parsed = yaml.safe_load(stripped)
    except yaml.YAMLError:
        parsed = None

    if parsed is None:
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = stripped

    if isinstance(parsed, bool) and stripped not in YAML_BOOLEAN_ALIASES:
        return stripped

    return parsed


def set_nested_value(config: dict[str, object], key: str, value: object) -> None:
    """Set a possibly nested config key, creating intermediate mappings."""
    parts = key.split(".")
    current = config
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def load_config(path: Path) -> dict[str, object]:
    """Load a YAML config file or return an empty mapping."""
    if not path.exists():
        return {}

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}: {exc}") from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Configuration must be a YAML mapping: {path}")
    return data


def save_config(path: Path, config: dict[str, object]) -> None:
    """Save a config mapping to a YAML file with helpful comments."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def init_config(target: Path, source: Path) -> int:
    """Copy the master config to the project root if it does not exist."""
    master_path = source / DEFAULT_CONFIG_PATH
    project_path = target / "iterate.config.yaml"

    if project_path.exists():
        _warning(f"Project config already exists: {project_path}")
        _hint("Use --set to modify it, or delete it first to re-initialize.")
        return 1

    if not master_path.exists():
        _error(f"Master config not found: {master_path}")
        return 1

    project_path.write_text(master_path.read_text(encoding="utf-8"), encoding="utf-8")
    _success(f"Initialized project config: {project_path}")
    return 0


def list_config(target: Path) -> int:
    """Print the current project-level config."""
    project_path = target / "iterate.config.yaml"
    if not project_path.exists():
        _warning(f"No project config found at {project_path}")
        return 1

    config = load_config(project_path)
    print(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    return 0


def set_config_values(target: Path, source: Path, set_pairs: list[list[str]]) -> int:
    """Apply --set key=value pairs to the project-level config and validate."""
    project_path = target / "iterate.config.yaml"
    previous_text = (
        project_path.read_text(encoding="utf-8") if project_path.exists() else None
    )
    config = load_config(project_path) if previous_text is not None else {}

    for group in set_pairs:
        for pair in group:
            if "=" not in pair:
                _error(f"Invalid --set argument (expected key=value): {pair}")
                return 1
            key, value = pair.split("=", 1)
            key = key.strip()
            if not key:
                _error(f"Empty key in --set argument: {pair}")
                return 1
            set_nested_value(config, key, parse_value(value))

    save_config(project_path, config)

    errors = _validate_project_config(target, source)
    if errors:
        _error(f"Validation failed for {project_path}; changes have been reverted.")
        for error in errors:
            _hint(f"- {error}")
        if previous_text is not None:
            project_path.write_text(previous_text, encoding="utf-8")
        else:
            project_path.unlink()
        return 1

    _success(f"Updated project config: {project_path}")
    return 0


def prompt_choice(question: str, choices: list[str], default: str | None = None) -> str:
    """Ask the user to select one option from a list."""
    _tui_print("")
    _tui_print(question, style="iterate.primary")
    for idx, choice in enumerate(choices, start=1):
        marker = " (default)" if choice == default else ""
        _hint(f"{idx}. {choice}{marker}")
    while True:
        answer = input("  \u2514 Enter number or name: ").strip()
        if not answer and default is not None:
            return default
        if answer.isdigit():
            idx = int(answer) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        if answer in choices:
            return answer
        _warning("Invalid choice, please try again.")


def prompt_text(question: str, default: str | None = None) -> str:
    """Ask the user for free-form text input."""
    default_hint = f" [{default}]" if default else ""
    while True:
        answer = input(f"\n{question}{default_hint}: ").strip()
        if answer:
            return answer
        if default is not None:
            return default
        _warning("A value is required.")


def prompt_int(question: str, default: int | None = None) -> int:
    """Ask the user for an integer."""
    default_hint = f" [{default}]" if default is not None else ""
    while True:
        answer = input(f"\n{question}{default_hint}: ").strip()
        if not answer and default is not None:
            return default
        try:
            return int(answer)
        except ValueError:
            _warning("Please enter a valid integer.")


def prompt_bool(question: str, default: bool = True) -> bool:
    """Ask the user a yes/no question."""
    default_text = "Y/n" if default else "y/N"
    while True:
        answer = input(f"\n{question} [{default_text}]: ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        _warning("Please enter 'y' or 'n'.")


def interactive_config(target: Path, source: Path) -> int:
    """Run an interactive wizard to create or update the project config."""
    project_path = target / "iterate.config.yaml"
    master_path = source / DEFAULT_CONFIG_PATH

    if project_path.exists():
        config = load_config(project_path)
    elif master_path.exists():
        config = load_config(master_path)
    else:
        config = {}

    previous_text = (
        project_path.read_text(encoding="utf-8") if project_path.exists() else None
    )

    _intro("iterate-skill configuration wizard")

    config["goal"] = prompt_text("Iteration goal", config.get("goal", "Improve code quality"))
    config["max_rounds"] = prompt_int_in_range(
        "Max rounds",
        MIN_ROUNDS,
        MAX_ROUNDS,
        config.get("max_rounds", 7),
    )
    config["language"] = prompt_choice(
        "Output language", LANGUAGE_CHOICES, config.get("language", "en")
    )
    config["dimensions"] = prompt_dimensions(config.get("dimensions", DIMENSION_CHOICES))
    config["review"] = config.get("review", {})
    config["review"]["scope"] = prompt_choice(
        "Review scope", SCOPE_CHOICES, config["review"].get("scope", "full")
    )
    config["atomic"] = config.get("atomic", {})
    config["atomic"]["max_lines"] = prompt_int(
        "Atomic issue max lines", config["atomic"].get("max_lines", 20)
    )
    config["git"] = config.get("git", {})
    config["git"]["push_per_round"] = prompt_bool(
        "Push after each round", config["git"].get("push_per_round", False)
    )

    save_config(project_path, config)

    errors = _validate_project_config(target, source)
    if errors:
        _error(f"Validation failed for {project_path}; changes have been reverted.")
        for error in errors:
            _hint(f"- {error}")
        if previous_text is not None:
            project_path.write_text(previous_text, encoding="utf-8")
        else:
            project_path.unlink()
        return 1

    _success(f"Configuration saved: {project_path}")
    return 0


def prompt_int_in_range(
    question: str, min_value: int, max_value: int, default: int | None = None
) -> int:
    """Ask the user for an integer constrained to [min_value, max_value]."""
    full_question = f"{question} ({min_value}-{max_value})"
    while True:
        value = prompt_int(full_question, default)
        if min_value <= value <= max_value:
            return value
        _warning(f"Please enter a value between {min_value} and {max_value}.")


def prompt_dimensions(current: object) -> list[str]:
    """Interactively select enabled dimensions."""
    current_set = set(current) if isinstance(current, list) else set(DIMENSION_CHOICES)
    selected: list[str] = []
    _tui_print("")
    _tui_print("Select review dimensions (enter numbers/names, comma-separated):", style="iterate.primary")
    for idx, dim in enumerate(DIMENSION_CHOICES, start=1):
        marker = " [enabled]" if dim in current_set else ""
        _hint(f"{idx}. {dim}{marker}")
    answer = input("Dimensions: ").strip()
    if not answer:
        return _ensure_non_empty_dimensions(list(current_set))

    for part in answer.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(DIMENSION_CHOICES):
                selected.append(DIMENSION_CHOICES[idx])
        elif part in DIMENSION_CHOICES:
            selected.append(part)

    unique_selected = list(dict.fromkeys(selected))
    return _ensure_non_empty_dimensions(unique_selected)


def _ensure_non_empty_dimensions(dimensions: list[str]) -> list[str]:
    """Return the dimensions list, falling back to all choices if empty."""
    return dimensions if dimensions else list(DIMENSION_CHOICES)


def config_command(
    target: Path,
    source: Path,
    init: bool,
    list_config_flag: bool,
    interactive: bool,
    set_pairs: list[list[str]] | None = None,
) -> int:
    """Manage the project-level iterate.config.yaml."""
    if init:
        return init_config(target, source)
    if list_config_flag:
        return list_config(target)
    if set_pairs:
        return set_config_values(target, source, set_pairs)
    if interactive:
        return interactive_config(target, source)

    _warning("No config action specified. Use --init, --list, --set, or --interactive.")
    return 1


def _add_install_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "install", help="Install the skill into an AI assistant's skills directory."
    )
    parser.add_argument(
        "--ai",
        choices=AI_CHOICES,
        help="Target AI assistant (or 'all'). If omitted, auto-detect installed assistants and prompt.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.cwd(),
        help="Project or home directory (default: current directory).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print what would be copied without copying."
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing skill files."
    )
    parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Install into the user's home directory instead of the project.",
    )


def _add_uninstall_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "uninstall", help="Remove the skill from an AI assistant's skills directory."
    )
    parser.add_argument(
        "--ai", choices=AI_CHOICES, help="Target AI assistant (or 'all'). If omitted, auto-detect installed assistants."
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.cwd(),
        help="Project directory (default: current directory).",
    )
    parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Uninstall from the user's home directory instead of the project.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )


def _add_validate_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "validate", help="Validate the project-level iterate.config.yaml."
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.cwd(),
        help="Project directory (default: current directory).",
    )


def _add_update_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "update", help="Refresh installed skill files and check for new releases."
    )
    parser.add_argument(
        "--ai",
        choices=AI_CHOICES,
        help="Target AI assistant (default: auto-detect installed assistants).",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.cwd(),
        help="Project directory (default: current directory).",
    )
    parser.add_argument(
        "--token",
        help="GitHub Personal Access Token for higher API rate limits.",
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing skill files."
    )
    parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Update the installation in the user's home directory.",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt before downloading from GitHub.",
    )


def _add_config_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "config", help="Manage the project-level iterate.config.yaml."
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.cwd(),
        help="Project directory (default: current directory).",
    )
    parser.add_argument(
        "--init", action="store_true", help="Copy the master config to the project root."
    )
    parser.add_argument(
        "--list",
        dest="list_config",
        action="store_true",
        help="Print the current project config.",
    )
    parser.add_argument(
        "--set",
        action="append",
        nargs="+",
        metavar="KEY=VALUE",
        help="Set a config value (supports nested keys like validation.commands.python).",
    )
    parser.add_argument(
        "--interactive", action="store_true", help="Run an interactive configuration wizard."
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="iterate-skill",
        description="Install and configure iterate-skill for AI coding assistants.",
    )
    subparsers = parser.add_subparsers(dest="command")
    _add_install_parser(subparsers)
    _add_uninstall_parser(subparsers)
    _add_validate_parser(subparsers)
    _add_update_parser(subparsers)
    _add_config_parser(subparsers)
    return parser


def parse_legacy_args(argv: list[str] | None) -> argparse.Namespace | None:
    """Support the original direct install invocation for backward compatibility."""
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        return None
    if args[0] in ("install", "uninstall", "validate", "config", "update"):
        return None
    if "--ai" not in args:
        return None

    parser = argparse.ArgumentParser()
    parser.add_argument("--ai", required=True, choices=AI_CHOICES)
    parser.add_argument("--target", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--global", dest="global_install", action="store_true")
    namespace, unknown = parser.parse_known_args(args)
    if unknown:
        return None
    namespace.command = "install"
    return namespace


def main(argv: list[str] | None = None, source: Path | None = None) -> int:
    """CLI entry point."""
    if source is None:
        source = Path(__file__).resolve().parent.parent

    legacy = parse_legacy_args(argv)
    if legacy is not None:
        args = legacy
    else:
        parser = build_parser()
        args = parser.parse_args(argv)

    if not args.command:
        build_parser().print_help()
        return 1

    if args.command == "install":
        if not args.target.exists():
            _error(f"Error: target directory does not exist: {args.target}")
            return 1
        try:
            return install_command(
                args.ai,
                args.target.resolve(),
                args.dry_run,
                source,
                args.force,
                args.global_install,
                input,
            )
        except FileNotFoundError as exc:
            _error(f"Error: {exc}")
            return 1

    if args.command == "uninstall":
        return uninstall_command(
            args.ai, args.target.resolve(), args.global_install, args.yes, input
        )

    if args.command == "validate":
        if not args.target.exists():
            _error(f"Error: target directory does not exist: {args.target}")
            return 1
        return validate_command(args.target.resolve(), source)

    if args.command == "update":
        if not args.target.exists():
            _error(f"Error: target directory does not exist: {args.target}")
            return 1
        return update_command(
            args.ai,
            args.target.resolve(),
            source,
            args.token,
            args.force,
            args.global_install,
            args.yes,
        )

    if args.command == "config":
        return config_command(
            args.target.resolve(),
            source,
            args.init,
            args.list_config,
            args.interactive,
            args.set,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
