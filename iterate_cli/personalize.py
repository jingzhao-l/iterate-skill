"""Personalization configuration wizard.

This module captures user knowledge that AI scanning cannot discover:
protected files, risk areas, known intentional patterns, dimension focus
overrides, fix priority order, forbidden fixes, iterate notes, code
conventions, and extra validation commands.

The wizard provides a consistent add/remove/skip interface for each
category. Structured rules are stored in ``iterate.config.yaml`` under
the ``personalization`` key; free-form notes are written to the
user-owned section of ``ITERATE.md``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from iterate_cli.tui import tui
from iterate_cli.wizard import (
    ALL_DIMENSIONS,
    DIMENSION_LABELS,
    InputFunc,
    _ask_yes_no,
    _ensure_interactive,
)

# Personalization schema version. Increment when the personalization
# data model changes, so future migrations can detect old configs.
PERSONALIZATION_VERSION = "1.0"


class CorruptConfigError(RuntimeError):
    """Raised when iterate.config.yaml exists but cannot be parsed as YAML.

    Deliberately distinct from a missing file: refusing to act on an unparsable
    config prevents a save/clear from silently rewriting (and thereby wiping)
    a damaged user configuration.
    """


def load_config_strict(config_path: Path) -> dict[str, Any]:
    """Parse iterate.config.yaml, refusing to proceed on corrupted YAML.

    Returns an empty dict only when the file is missing/empty. When the file
    exists but is not valid YAML, raises :class:`CorruptConfigError` so callers
    do not merge into — or write over — a damaged configuration.

    Args:
        config_path: Path to iterate.config.yaml.

    Returns:
        Parsed config as a dict (``{}`` when the file is absent or empty).

    Raises:
        CorruptConfigError: If the file exists but is not valid YAML.
        OSError: If the file cannot be read.
    """
    if not config_path.is_file():
        return {}
    raw = config_path.read_text(encoding="utf-8")
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise CorruptConfigError(
            f"iterate.config.yaml 不是合法 YAML，已拒绝写入以免覆盖损坏配置：{exc}"
        ) from exc
    return parsed if isinstance(parsed, dict) else {}

# Module name pattern for extra_validation_commands keys.
# Only allow alphanumeric, dash, underscore, dot — prevents shell
# metacharacter injection via module key.
MODULE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")

# Allowed command prefixes for extra_validation_commands.
# These cover common test/lint/type-check/build tooling. Commands
# starting with one of these prefixes are accepted without warning.
# Anything else triggers a confirmation prompt to make the operator
# explicitly aware that an unusual command will be persisted into
# executable validation configuration.
KNOWN_SAFE_COMMAND_PREFIXES: tuple[str, ...] = (
    "pytest", "py.test", "unittest", "tox", "nox",
    "ruff", "flake8", "pylint", "mypy", "bandit",
    "black", "isort", "pyupgrade",
    "coverage", "pytest-cov", "pip-audit",
    "npm", "pnpm", "yarn", "npx",
    "tsc", "eslint", "prettier", "jest", "vitest", "ava", "mocha",
    "swift", "swiftc", "xcodebuild", "swift test",
    "cargo", "rustc",
    "go", "gofmt", "golangci-lint",
    "make", "cmake",
    "gradle", "mvn", "java",
    "dotnet",
    "shellcheck", "shfmt",
    "pre-commit",
)

# Characters that should not appear in validation commands at all.
# These are shell metacharacters that allow command chaining, which
# would let a "validation command" smuggle arbitrary side effects.
#
# This is the canonical set: it MUST stay identical to the metacharacter
# sets used by iterate_cli/doctor.py and scripts/validate.py so that a
# command accepted at personalization time is never later rejected as a
# whitelist violation, and vice-versa. Sync is enforced by
# tests/test_validate.py (test_metachar_sets_in_sync).
FORBIDDEN_COMMAND_CHARS: tuple[str, ...] = (
    ";", "|", "&", "`", "$", ">", "<", "\n", "\r",
    "\\", "#", "*", "?", "~", '"', "'",
    "(", ")", "[", "]", "{", "}",
)

# Environment variable that lets the *operator* (system level) extend the
# known-safe command-prefix allowlist without editing source. This is
# intentionally NOT project-configurable: a project's iterate.config.yaml
# cannot set it, so a malicious or accidental project config cannot use it
# to smuggle arbitrary commands. Values are comma/whitespace-separated tool
# names, and each token is still rejected (fail-closed) if it contains any
# shell metacharacter. Only an operator able to set the process environment
# can widen the allowlist.
EXTRA_SAFE_PREFIXES_ENV: str = "ITERATE_EXTRA_SAFE_COMMAND_PREFIXES"


def _operator_extra_prefixes() -> tuple[str, ...]:
    """Return operator-approved extra safe prefixes from the environment.

    Reads ``ITERATE_EXTRA_SAFE_COMMAND_PREFIXES`` (comma/whitespace
    separated). Tokens containing shell metacharacters are dropped, so the
    result always remains fail-closed. This is a safe extension point for
    adding new tooling without editing source.
    """
    raw = os.environ.get(EXTRA_SAFE_PREFIXES_ENV, "")
    if not raw:
        return ()
    tokens = [tok.strip() for tok in re.split(r"[\s,]+", raw) if tok.strip()]
    # Keep only clean tool names: no shell metacharacters and starting with an
    # alphanumeric char. This drops both injection attempts ("safety;rm") and
    # incidental fragments ("-rf", "/", ".") that whitespace-splitting of a
    # malicious value could otherwise leave behind.
    safe = [
        tok
        for tok in tokens
        if not _has_forbidden_chars(tok) and tok[0].isalnum()
    ]
    return tuple(dict.fromkeys(safe))


def _is_known_safe_command(cmd: str) -> bool:
    """Return True if cmd starts with a known safe tool prefix."""
    stripped = cmd.strip()
    if not stripped:
        return False
    first_token = stripped.split(None, 1)[0]
    operator_prefixes = _operator_extra_prefixes()
    # Handle "python -m pytest" style invocations: accept if the
    # *effective* tool (after -m) is whitelisted.
    if first_token in ("python", "python3", "py"):
        rest = stripped.split(None, 1)
        # "python -m <tool> ..." — the tool after -m governs.
        if len(rest) > 1 and " -m " in stripped:
            inner = stripped.split(" -m ", 1)[1].strip().split(None, 1)[0]
            return inner in KNOWN_SAFE_COMMAND_PREFIXES or inner in operator_prefixes
        # "python <script>.py ..." — a plain script invocation is legitimate
        # (e.g. `python manage.py test`). Reject anything that is not a
        # simple script path so a bare `python` can't be persisted.
        if len(rest) > 1:
            script = rest[1].strip().split(None, 1)[0]
            return _is_plain_script_path(script)
        return False
    return first_token in KNOWN_SAFE_COMMAND_PREFIXES or first_token in operator_prefixes


def _is_plain_script_path(script: str) -> bool:
    """Return True for a safe script-path token (``path/to/x.py``).

    Rejects flags (``-x``), bare names with no ``.py`` suffix, and any token
    containing shell metacharacters or a path traversal escape.
    """
    if not script or script.startswith("-"):
        return False
    if not script.endswith(".py"):
        return False
    if "/" in script:
        # Reject absolute paths and parent-dir traversal; only allow
        # relative paths within the project.
        return not (script.startswith("/") or ".." in script)
    return not _has_forbidden_chars(script)


def _has_forbidden_chars(cmd: str) -> bool:
    """Return True if cmd contains shell-chaining metacharacters."""
    return any(ch in cmd for ch in FORBIDDEN_COMMAND_CHARS)


def validate_extra_command(cmd: str) -> tuple[bool, str]:
    """Validate a single extra validation command string.

    Returns (is_valid, reason). When is_valid is False the caller MUST
    refuse to persist the command. When is_valid is True the command
    passed both the blacklist (shell metacharacter) and whitelist
    (known-safe prefix) checks.

    v2.0.2: switched from "warn but accept with confirmation" to a
    **strict whitelist** — commands that do not start with a known-safe
    tool prefix are rejected outright. This eliminates the
    Context-Inappropriate Capability finding from the ClawHub audit
    by ensuring no arbitrary command can be persisted into executable
    validation configuration, even with user confirmation.
    """
    if not cmd or not cmd.strip():
        return False, "empty command"
    if _has_forbidden_chars(cmd):
        return False, (
            "command contains forbidden shell metacharacters "
            f"({FORBIDDEN_COMMAND_CHARS}); command chaining is not allowed "
            "in extra validation commands"
        )
    if _is_known_safe_command(cmd):
        return True, ""
    return False, (
        "command does not start with a known-safe tool prefix "
        f"({sorted(KNOWN_SAFE_COMMAND_PREFIXES)[:6]}...); only pre-approved "
        "test/lint/type-check/build tooling is allowed in extra validation "
        "commands. To add a new tool, extend KNOWN_SAFE_COMMAND_PREFIXES "
        "in iterate_cli/personalize.py, or set the operator-level "
        f"environment variable {EXTRA_SAFE_PREFIXES_ENV} "
        "(see README for details)"
    )

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class RiskArea:
    """A fragile file or directory that needs extra care."""

    path: str
    reason: str


@dataclass
class KnownIntentional:
    """A finding to suppress because the pattern is intentional.

    Matching granularity: file:line + dimension.  When ``line`` is 0
    the suppression applies to the entire file for that dimension.
    """

    file: str
    line: int
    dimension: str
    reason: str


@dataclass
class DimensionFocusOverride:
    """Extra focus text appended to a dimension's prompt."""

    dimension: str
    focus: str


@dataclass
class PersonalizationData:
    """All personalization categories collected by the wizard.

    ``iterate_notes`` and ``code_conventions`` are free-form text
    destined for the ITERATE.md user-owned section.  All other fields
    are structured rules stored in iterate.config.yaml.
    """

    protected_paths: list[str] = field(default_factory=list)
    risk_areas: list[RiskArea] = field(default_factory=list)
    known_intentional: list[KnownIntentional] = field(default_factory=list)
    dimension_focus: list[DimensionFocusOverride] = field(default_factory=list)
    fix_priority_order: list[str] = field(default_factory=list)
    forbidden_fixes: list[str] = field(default_factory=list)
    iterate_notes: list[str] = field(default_factory=list)
    code_conventions: list[str] = field(default_factory=list)
    extra_validation_commands: dict[str, list[str]] = field(default_factory=dict)

    def is_empty(self) -> bool:
        """Return True if every category is empty."""
        return (
            not self.protected_paths
            and not self.risk_areas
            and not self.known_intentional
            and not self.dimension_focus
            and not self.fix_priority_order
            and not self.forbidden_fixes
            and not self.iterate_notes
            and not self.code_conventions
            and not self.extra_validation_commands
        )

    def to_config_dict(self) -> dict[str, Any]:
        """Serialise structured fields to a dict for iterate.config.yaml.

        Only structured rules are included; ``iterate_notes`` and
        ``code_conventions`` are handled separately (written to
        ITERATE.md user-owned section).

        ``extra_validation_commands`` is persisted here so that
        ``load_personalization_from_config`` can round-trip it; the
        merge step additionally copies these commands into
        ``validation.commands`` for the actual validation runner.
        """
        return {
            "version": PERSONALIZATION_VERSION,
            "protected_paths": list(self.protected_paths),
            "risk_areas": [
                {"path": r.path, "reason": r.reason} for r in self.risk_areas
            ],
            "known_intentional": [
                {
                    "file": k.file,
                    "line": k.line,
                    "dimension": k.dimension,
                    "reason": k.reason,
                }
                for k in self.known_intentional
            ],
            "dimension_focus": [
                {"dimension": d.dimension, "focus": d.focus}
                for d in self.dimension_focus
            ],
            "fix_priority_order": list(self.fix_priority_order),
            "forbidden_fixes": list(self.forbidden_fixes),
            "extra_validation_commands": {
                module: list(cmds)
                for module, cmds in self.extra_validation_commands.items()
            },
        }

    def to_user_md_sections(self) -> str:
        """Render iterate_notes and code_conventions as Markdown for ITERATE.md."""
        sections: list[str] = []

        if self.code_conventions:
            sections.append(f"{CONVENTIONS_SECTION_HEADER}\n")
            for conv in self.code_conventions:
                sections.append(f"- {conv}")
            sections.append("")

        if self.protected_paths or self.risk_areas:
            sections.append(f"{RESTRICTED_SECTION_HEADER}\n")
            if self.protected_paths:
                sections.append("### 禁区 / Protected (不可修改 / Do not modify)\n")
                for p in self.protected_paths:
                    sections.append(f"- `{p}`")
                sections.append("")
            if self.risk_areas:
                sections.append("### 风险区 / Risk Areas (改动需审批 / Changes need approval)\n")
                for r in self.risk_areas:
                    sections.append(f"- `{r.path}` — {r.reason}")
                sections.append("")

        if self.iterate_notes:
            sections.append(f"{NOTES_SECTION_HEADER}\n")
            for note in self.iterate_notes:
                sections.append(f"- {note}")
            sections.append("")

        if self.known_intentional:
            sections.append(f"{KNOWN_INTENTIONAL_SECTION_HEADER}\n")
            for k in self.known_intentional:
                loc = f"{k.file}:{k.line}" if k.line > 0 else k.file
                sections.append(f"- `{loc}` [{k.dimension}] — {k.reason}")
            sections.append("")

        if self.forbidden_fixes:
            sections.append(f"{FORBIDDEN_FIXES_SECTION_HEADER}\n")
            for f in self.forbidden_fixes:
                sections.append(f"- {f}")
            sections.append("")

        return "\n".join(sections)


# Headers that mark personalization-generated sections in ITERATE.md.
# Used by merge_user_sections to replace old personalization content
# while preserving user's manually written sections.
#
# The two free-form sections (notes / conventions) are additionally read back
# by load_personalization_from_iterate_md, which compares section titles
# against the SAME header constants — keep every literal in sync here.
CONVENTIONS_SECTION_HEADER = "## 自定义代码约定 / Custom Code Conventions"
RESTRICTED_SECTION_HEADER = "## 禁区与风险区 / Restricted & Risk Areas"
NOTES_SECTION_HEADER = "## Iterate 注意点 / Iterate Notes"
KNOWN_INTENTIONAL_SECTION_HEADER = (
    "## 已知意图 / Known Intentional (抑制误报 / Suppress false positives)"
)
FORBIDDEN_FIXES_SECTION_HEADER = "## 禁止的修复方式 / Forbidden Fixes"

PERSONALIZATION_SECTION_HEADERS: tuple[str, ...] = (
    CONVENTIONS_SECTION_HEADER,
    RESTRICTED_SECTION_HEADER,
    NOTES_SECTION_HEADER,
    KNOWN_INTENTIONAL_SECTION_HEADER,
    FORBIDDEN_FIXES_SECTION_HEADER,
)


def _is_personalization_header(line: str) -> bool:
    """Return True if line exactly matches a personalization section header.

    Uses exact match (not startswith) to avoid clobbering user-written
    sections whose titles happen to begin with a personalization header
    prefix (e.g. "## 自定义代码约定 / Custom Code Conventions — 后端组").
    """
    stripped = line.strip()
    return stripped in PERSONALIZATION_SECTION_HEADERS


def merge_user_sections(existing_content: str, new_personalization_md: str) -> str:
    """Merge personalization-generated sections into existing user content.

    Removes any old personalization-generated sections (identified by their
    headers in PERSONALIZATION_SECTION_HEADERS) from existing_content, then
    appends the new personalization sections. User's manually written
    sections (those not matching personalization headers) are preserved.

    Args:
        existing_content: Current user-owned section content from ITERATE.md.
        new_personalization_md: New personalization sections (from to_user_md_sections).

    Returns:
        Merged content with old personalization sections replaced by new ones.
    """
    lines = existing_content.split("\n")
    result_lines: list[str] = []
    skip_until_next_header = False

    for line in lines:
        if _is_personalization_header(line):
            skip_until_next_header = True
            continue

        if skip_until_next_header and line.strip().startswith("## "):
            # Hit a new section header: stop skipping.
            skip_until_next_header = False
            if _is_personalization_header(line):
                # Another personalization section to remove.
                skip_until_next_header = True
                continue
            result_lines.append(line)
            continue

        if skip_until_next_header:
            # Inside a section being removed.
            continue

        result_lines.append(line)

    # Clean up trailing whitespace from removed sections.
    cleaned = "\n".join(result_lines).rstrip()

    # Append new personalization sections.
    new_sections = new_personalization_md.strip()
    if not new_sections:
        return cleaned

    if cleaned:
        return f"{cleaned}\n\n{new_sections}\n"
    return f"{new_sections}\n"


# ---------------------------------------------------------------------------
# Load / save helpers
# ---------------------------------------------------------------------------


def _coerce_line_number(value: Any) -> int:
    """Parse a config-sourced line number defensively.

    Accepts integers and integer-like strings; anything else (including a
    float with a fractional part, which ``int()`` would silently truncate)
    falls back to 0 = whole-file suppression. Negative values are clamped to 0.

    Args:
        value: The raw ``line`` value from a hand-edited config.

    Returns:
        A non-negative integer line number (0 means whole file).
    """
    if isinstance(value, float):
        # int(1.5) silently truncates to 1; treat fractional values as
        # malformed rather than guessing a line.
        if not value.is_integer():
            return 0
        line = int(value)
    elif isinstance(value, bool):
        return 0
    elif isinstance(value, int):
        line = value
    else:
        try:
            line = int(str(value))
        except (TypeError, ValueError):
            return 0
    return max(line, 0)


def load_personalization_from_config(config: dict[str, Any]) -> PersonalizationData:
    """Parse the ``personalization`` section of a config dict.

    Args:
        config: Parsed iterate.config.yaml content (or a sub-dict).

    Returns:
        PersonalizationData with structured fields populated.
        Free-form notes are not stored in config.yaml and will be empty;
        they are loaded separately from ITERATE.md via
        ``load_personalization_from_iterate_md`` (or its combined wrapper
        ``load_existing_personalization``).
    """
    raw = config.get("personalization") or {}
    # A hand-edited config may set ``personalization`` to a non-mapping value
    # (e.g. a string). Treating it as data would crash on ``raw.get(...)``
    # below, so degrade to "no personalization" instead of surfacing a bare
    # traceback from refresh / personalization loading paths.
    if not isinstance(raw, dict):
        return PersonalizationData()

    # protected_paths must be a list of strings. A hand-edited config may hold
    # a scalar string (which would otherwise be iterated character-by-character
    # and persisted as a corrupt per-char list), so guard like every other list
    # field below.
    raw_protected = raw.get("protected_paths") or []
    if not isinstance(raw_protected, list):
        raw_protected = []
    protected = [str(p) for p in raw_protected]

    risk_areas: list[RiskArea] = []
    for item in raw.get("risk_areas") or []:
        if isinstance(item, dict) and "path" in item:
            risk_areas.append(
                RiskArea(
                    path=str(item["path"]),
                    reason=str(item.get("reason", "")),
                )
            )

    known: list[KnownIntentional] = []
    for item in raw.get("known_intentional") or []:
        if isinstance(item, dict) and "file" in item:
            # Defensive parse of line: YAML may contain non-integer strings
            # if manually edited. Fall back to 0 (whole-file suppression).
            line = _coerce_line_number(item.get("line"))
            known.append(
                KnownIntentional(
                    file=str(item["file"]),
                    line=line,
                    dimension=str(item.get("dimension", "")),
                    reason=str(item.get("reason", "")),
                )
            )

    dim_focus: list[DimensionFocusOverride] = []
    for item in raw.get("dimension_focus") or []:
        if isinstance(item, dict) and "dimension" in item:
            dim_focus.append(
                DimensionFocusOverride(
                    dimension=str(item["dimension"]),
                    focus=str(item.get("focus", "")),
                )
            )

    # fix_priority_order / forbidden_fixes must be lists of dimension ids.
    # Guard against a scalar string (which would otherwise be iterated
    # character-by-character) and non-list junk from a hand-edited config.
    raw_fix_order = raw.get("fix_priority_order") or []
    if not isinstance(raw_fix_order, list):
        raw_fix_order = []
    fix_order = [str(d) for d in raw_fix_order]

    raw_forbidden = raw.get("forbidden_fixes") or []
    if not isinstance(raw_forbidden, list):
        raw_forbidden = []
    forbidden = [str(f) for f in raw_forbidden]

    # Module name pattern: only allow alphanumeric, dash, underscore, dot.
    # Prevents shell metacharacter injection via module key.
    raw_extra_cmds = raw.get("extra_validation_commands") or {}
    if not isinstance(raw_extra_cmds, dict):
        raw_extra_cmds = {}
    extra_cmds: dict[str, list[str]] = {}
    for module, cmds in raw_extra_cmds.items():
        module_str = str(module)
        if not MODULE_NAME_PATTERN.match(module_str):
            # Skip entries with unsafe module names.
            continue
        if isinstance(cmds, list):
            valid: list[str] = []
            for c in cmds:
                if not isinstance(c, str) or not c.strip():
                    continue
                # Fail closed: revalidate every config-sourced command against
                # the strict whitelist before it can be persisted into
                # executable ``validation.commands``. A manually edited
                # iterate.config.yaml cannot smuggle an arbitrary command this
                # way, keeping the "strict whitelist" guarantee intact.
                ok, reason = validate_extra_command(c)
                if ok:
                    valid.append(c)
                else:
                    tui.warning(
                        f"跳过非法验证命令 [{module_str}] '{c}': {reason}",
                        indent=2,
                    )
            if valid:
                extra_cmds[module_str] = valid

    return PersonalizationData(
        protected_paths=protected,
        risk_areas=risk_areas,
        known_intentional=known,
        dimension_focus=dim_focus,
        fix_priority_order=fix_order,
        forbidden_fixes=forbidden,
        extra_validation_commands=extra_cmds,
    )


def load_personalization_from_iterate_md(
    project_root: Path,
) -> tuple[list[str], list[str]]:
    """Load free-form ``iterate_notes`` and ``code_conventions`` from ITERATE.md.

    These two categories are written to the user-owned section of
    ITERATE.md (not to iterate.config.yaml), so they must be read back
    from ITERATE.md whenever existing personalization is loaded for
    editing. Without this, re-running ``iterate personalize`` (or
    re-personalizing during ``iterate onboard``) would start with empty
    notes/conventions and ``merge_user_sections`` would silently wipe
    the sections the user had previously entered.

    Args:
        project_root: Project root directory containing ITERATE.md.

    Returns:
        A ``(iterate_notes, code_conventions)`` tuple of bullet items.
        Empty lists are returned if ITERATE.md is missing or unreadable.
    """
    from iterate_cli.generator import extract_user_owned_section

    iterate_md_path = project_root / "ITERATE.md"
    if not iterate_md_path.is_file():
        return [], []
    try:
        content = iterate_md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], []

    user_content = extract_user_owned_section(content)

    notes: list[str] = []
    conventions: list[str] = []
    current_section: str | None = None

    for line in user_content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            current_section = stripped
            continue
        if stripped.startswith("- ") and len(stripped) > 2:
            item = stripped[2:].strip()
            if current_section == NOTES_SECTION_HEADER:
                notes.append(item)
            elif current_section == CONVENTIONS_SECTION_HEADER:
                conventions.append(item)

    return notes, conventions


def load_existing_personalization(
    project_root: Path,
    config: dict[str, Any],
) -> PersonalizationData:
    """Load the full existing personalization for editing.

    Structured rules come from iterate.config.yaml (``personalization``
    section); free-form ``iterate_notes`` and ``code_conventions`` are
    read back from the ITERATE.md user-owned section. Merging both
    ensures re-running the wizard preserves previously entered content
    instead of silently dropping it.

    Args:
        project_root: Project root directory containing ITERATE.md.
        config: Parsed iterate.config.yaml content.

    Returns:
        A PersonalizationData populated from both sources.
    """
    data = load_personalization_from_config(config)
    notes, conventions = load_personalization_from_iterate_md(project_root)
    data.iterate_notes = notes
    data.code_conventions = conventions
    return data


def merge_personalization_into_config(
    config: dict[str, Any],
    data: PersonalizationData,
) -> dict[str, Any]:
    """Write personalization structured fields into a config dict.

    Also synchronises ``extra_validation_commands`` into
    ``validation.commands``: previously personalization-owned commands that
    the user removed are deleted from ``validation.commands`` (per-command and
    per-module), new commands are appended (deduplicated, fail-closed
    validated), and new command prefixes are auto-added to
    ``validation.command_whitelist`` so that schema validation does not fail.

    Non-personalization commands that were already configured for a module
    (e.g. base-config defaults or manual edits) are always preserved: only the
    subset previously owned by ``personalization.extra_validation_commands``
    is ever removed.

    Args:
        config: The existing parsed config dict (will be copied, not mutated).
        data: PersonalizationData to write.

    Returns:
        New config dict with personalization section updated.
    """
    result = dict(config)
    result["personalization"] = data.to_config_dict()

    # Commands previously owned by personalization, captured from the OLD
    # config before it is overwritten above. These are the only commands that
    # may be removed from validation.commands, so base-config commands and
    # manual edits for the same module survive.
    personalization_old = config.get("personalization")
    personalization_old = personalization_old if isinstance(personalization_old, dict) else {}
    raw_extra_old = personalization_old.get("extra_validation_commands") or {}
    raw_extra_old = raw_extra_old if isinstance(raw_extra_old, dict) else {}
    old_extra: dict[str, list[str]] = {
        str(module): list(cmds) if isinstance(cmds, list) else []
        for module, cmds in raw_extra_old.items()
    }
    new_extra = data.extra_validation_commands

    # No personalization commands before or after → validation section is
    # untouched (nothing to add, nothing to remove).
    if not old_extra and not new_extra:
        return result

    validation = dict(result.get("validation") or {})
    commands = {
        str(module): list(cmds) if isinstance(cmds, list) else []
        for module, cmds in (validation.get("commands") or {}).items()
    }
    whitelist = list(validation.get("command_whitelist") or [])

    def _owned_strings(module: str) -> set[str]:
        """Return the previously personalization-owned strings for a module."""
        return {c for c in old_extra.get(module, []) if isinstance(c, str)}

    # 1) Remove modules personalization no longer owns at all, dropping only the
    #    commands that were personalization-owned (base commands survive).
    for module in old_extra:
        if module in new_extra:
            continue
        if module in commands:
            removed = _owned_strings(module)
            commands[module] = [c for c in commands[module] if c not in removed]
            if not commands[module]:
                # No commands left → drop the empty module so schema validation
                # (minItems) cannot fail on an empty list.
                commands.pop(module, None)

    # 2) For modules personalization still owns: drop the old personalization
    #    owned commands (so deleted ones do not linger), then re-add the
    #    validated current set.
    for module, cmds in new_extra.items():
        base = list(commands.get(module) or [])
        if module in old_extra:
            removed = _owned_strings(module)
            base = [c for c in base if c not in removed]
        for cmd in cmds:
            # Skip empty/whitespace-only commands to keep generated
            # config compliant with schema (minLength: 1).
            if not cmd or not cmd.strip():
                continue
            # Fail closed: revalidate before merging so a config-sourced or
            # manually-crafted command cannot expand the executable surface
            # or auto-extend the whitelist. Only commands that pass the
            # strict whitelist may be merged and whitelisted.
            ok, reason = validate_extra_command(cmd)
            if not ok:
                tui.warning(
                    f"跳过非法验证命令 [{module}] '{cmd}': {reason}",
                    indent=2,
                )
                continue
            if cmd not in base:
                base.append(cmd)
            # Auto-add command prefix to whitelist if not present.
            # Only reached for commands that passed strict validation,
            # so the prefix is always a known-safe tool.
            parts = cmd.strip().split(None, 1)
            prefix = parts[0] if parts else ""
            if prefix and prefix not in whitelist:
                whitelist.append(prefix)
        if base:
            commands[module] = base
        else:
            commands.pop(module, None)

    validation["commands"] = commands
    # Only persist command_whitelist when it is non-empty: an explicit empty
    # list would trip doctor's "must be a non-empty list" check, while an
    # absent key means "no whitelist constraint" (doctor skips it). When the
    # user cleared every command, dropping the key keeps the config clean.
    if whitelist:
        validation["command_whitelist"] = whitelist
    else:
        validation.pop("command_whitelist", None)
    result["validation"] = validation

    return result


def save_personalization_to_config(
    project_root: Path,
    data: PersonalizationData,
) -> Path:
    """Update the personalization section of iterate.config.yaml in-place.

    Reads the existing config, merges personalization, and writes back
    atomically (temp file + ``os.replace``) so a crash mid-write can never
    leave a truncated config file. Preserves all other config fields.

    Note: this only updates iterate.config.yaml. The companion
    ``save_personalization`` additionally writes the free-form notes /
    conventions to ITERATE.md and rolls back config on ITERATE.md failure.

    Args:
        project_root: Project root directory containing iterate.config.yaml.
        data: PersonalizationData to save.

    Returns:
        Path to the written config file.

    Raises:
        FileNotFoundError: If iterate.config.yaml does not exist.
    """
    from iterate_cli.generator import atomic_write

    config_path = project_root / "iterate.config.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    existing = load_config_strict(config_path)
    updated = merge_personalization_into_config(existing, data)

    atomic_write(
        config_path,
        yaml.safe_dump(updated, default_flow_style=False, allow_unicode=True, sort_keys=False),
    )
    return config_path


def build_updated_iterate_md(
    project_root: Path,
    data: PersonalizationData,
) -> str | None:
    """Build updated ITERATE.md content with personalization merged into the
    user-owned section. Pure (no disk writes).

    Returns ``None`` when no update is possible: ITERATE.md is absent,
    unreadable, or lacks the user-owned markers. The transactional save treats
    ``None`` as "skip ITERATE.md" rather than failing.

    Args:
        project_root: Project root directory containing ITERATE.md.
        data: PersonalizationData whose notes/conventions should be merged.

    Returns:
        Updated ITERATE.md content, or None if no update is possible.
    """
    from iterate_cli.generator import (
        USER_END_MARKER,
        USER_START_MARKER,
        extract_user_owned_section,
    )

    iterate_md_path = project_root / "ITERATE.md"
    if not iterate_md_path.is_file():
        return None
    try:
        content = iterate_md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        tui.warning(f"Could not read existing ITERATE.md: {exc}")
        return None

    start_idx = content.find(USER_START_MARKER)
    end_idx = content.find(USER_END_MARKER)
    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        return None

    new_personalization_md = data.to_user_md_sections()
    existing_user_content = extract_user_owned_section(content)
    merged = merge_user_sections(existing_user_content, new_personalization_md)
    before = content[: start_idx + len(USER_START_MARKER)]
    after = content[end_idx:]
    return f"{before}\n{merged}\n{after}"


def save_personalization(
    project_root: Path,
    data: PersonalizationData,
) -> tuple[Path, Path]:
    """Persist personalization to both iterate.config.yaml and ITERATE.md.

    This is the transactional save used by ``iterate personalize``. Both files
    are written atomically (temp file + ``os.replace``); if the second write
    fails, the first is rolled back to its prior content so the two files never
    diverge. If a rollback itself fails, the inconsistency is surfaced to stderr
    instead of being silently swallowed.

    Args:
        project_root: Project root directory containing both files.
        data: PersonalizationData to persist.

    Returns:
        Tuple of ``(config_path, iterate_md_path)``.

    Raises:
        FileNotFoundError: If iterate.config.yaml does not exist.
        OSError: If a write (or a rollback) fails.
    """
    from iterate_cli.generator import atomic_write

    config_path = project_root / "iterate.config.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    # Build config content.
    existing = load_config_strict(config_path)
    updated = merge_personalization_into_config(existing, data)
    config_yaml = yaml.safe_dump(
        updated, default_flow_style=False, allow_unicode=True, sort_keys=False
    )

    # Build ITERATE.md content (None means "skip"; e.g. file absent).
    iterate_md_content = build_updated_iterate_md(project_root, data)

    # Snapshot prior config content for rollback (config is written first, so
    # a failure while writing ITERATE.md rolls config back to this snapshot).
    old_config = config_path.read_text(encoding="utf-8")
    iterate_md_path = project_root / "ITERATE.md"

    atomic_write(config_path, config_yaml)
    if iterate_md_content is not None:
        try:
            atomic_write(iterate_md_path, iterate_md_content)
        except OSError:
            # Roll back config so the two files stay consistent.
            try:
                atomic_write(config_path, old_config)
            except OSError as rollback_exc:
                tui.error(
                    f"Failed to roll back {config_path} after ITERATE.md write "
                    f"error: {rollback_exc}. Two files may be inconsistent.",
                    indent=2,
                )
            raise
    return config_path, iterate_md_path


# ---------------------------------------------------------------------------
# Clear personalization
# ---------------------------------------------------------------------------


def has_personalization(project_root: Path, config: dict[str, Any]) -> bool:
    """Return True if any personalization content exists.

    Presence is judged by actual personalization content — structured rules in
    iterate.config.yaml or free-form bullet items in the ITERATE.md user-owned
    section — rather than section headers alone (a freshly onboarded project's
    template user-owned section already contains personalization-style headers
    with no entries).

    Args:
        project_root: Project root directory containing ITERATE.md.
        config: Parsed iterate.config.yaml content.

    Returns:
        True if there is any personalization to clear.
    """
    data = load_existing_personalization(project_root, config)
    return not data.is_empty()


def remove_personalization_from_config(config: dict[str, Any]) -> dict[str, Any]:
    """Strip the ``personalization`` section and its owned validation commands.

    Also removes personalization-owned commands from ``validation.commands``
    (dropping modules that become empty) so the resulting config stays
    schema-valid. The ``command_whitelist`` is left untouched: it is a
    harmless allowlist and its prefixes may be shared with pre-existing
    (base-config or manually added) validation commands.

    Args:
        config: Parsed iterate.config.yaml content (not mutated).

    Returns:
        New config dict without the personalization section and without the
        validation commands that personalization owned.
    """
    result = dict(config)

    personalization = config.get("personalization")
    old_extra: dict[str, list[str]] = {}
    if isinstance(personalization, dict):
        raw_extra = personalization.get("extra_validation_commands") or {}
        raw_extra = raw_extra if isinstance(raw_extra, dict) else {}
        old_extra = {
            str(module): list(cmds) if isinstance(cmds, list) else []
            for module, cmds in raw_extra.items()
        }
    result.pop("personalization", None)

    if not old_extra:
        return result

    validation = dict(result.get("validation") or {})
    commands = {
        str(module): list(cmds) if isinstance(cmds, list) else []
        for module, cmds in (validation.get("commands") or {}).items()
    }
    for module, owned in old_extra.items():
        if module not in commands:
            continue
        owned_set = {c for c in owned if isinstance(c, str)}
        commands[module] = [c for c in commands[module] if c not in owned_set]
        if not commands[module]:
            # Drop the empty module so schema validation (minItems) does not
            # fail on an empty list.
            commands.pop(module, None)
    validation["commands"] = commands
    result["validation"] = validation

    return result


def clear_personalization(project_root: Path) -> tuple[Path, Path]:
    """Remove all personalization from iterate.config.yaml and ITERATE.md.

    This is the transactional clear used by ``iterate personalize --clear``.
    Both files are written atomically (temp file + ``os.replace``); if the
    second write fails, the first is rolled back to its prior content so the
    two files never diverge.

    Structured rules are stripped from config.yaml and personalization-owned
    commands are removed from ``validation.commands``; free-form sections
    (notes / conventions / restricted areas / known intentional / forbidden
    fixes) are removed from the ITERATE.md user-owned section while preserving
    any manually written content.

    Args:
        project_root: Project root directory containing both files.

    Returns:
        Tuple of ``(config_path, iterate_md_path)``.

    Raises:
        FileNotFoundError: If iterate.config.yaml does not exist.
        OSError: If a write (or a rollback) fails.
    """
    from iterate_cli.generator import atomic_write

    config_path = project_root / "iterate.config.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    existing = load_config_strict(config_path)
    updated = remove_personalization_from_config(existing)
    config_yaml = yaml.safe_dump(
        updated, default_flow_style=False, allow_unicode=True, sort_keys=False
    )

    # Build ITERATE.md content with personalization sections removed. An empty
    # PersonalizationData renders no sections, and merge_user_sections strips
    # any existing personalization headers while keeping manual content.
    iterate_md_content = build_updated_iterate_md(project_root, PersonalizationData())

    old_config = config_path.read_text(encoding="utf-8")
    iterate_md_path = project_root / "ITERATE.md"

    atomic_write(config_path, config_yaml)
    if iterate_md_content is not None:
        try:
            atomic_write(iterate_md_path, iterate_md_content)
        except OSError:
            # Roll back config so the two files stay consistent.
            try:
                atomic_write(config_path, old_config)
            except OSError as rollback_exc:
                tui.error(
                    f"Failed to roll back {config_path} after ITERATE.md write "
                    f"error: {rollback_exc}. Two files may be inconsistent.",
                    indent=2,
                )
            raise
    return config_path, iterate_md_path


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------


def run_personalize_wizard(
    project_root: Path,
    input_func: InputFunc = input,
    existing: PersonalizationData | None = None,
) -> PersonalizationData | None:
    """Run the 9-step personalization configuration wizard.

    Each step supports view / add / remove / skip.  The wizard loads
    existing personalization data (if provided) so users can incrementally
    add or modify entries.

    Args:
        project_root: Project root directory (for path validation context).
        input_func: Callable used to read user input.
        existing: Existing PersonalizationData to pre-populate (for editing).

    Returns:
        PersonalizationData if the user completes the wizard, None if cancelled
        or the wizard could not prompt (non-interactive stdin).
    """
    if not _ensure_interactive(input_func):
        return None

    data = existing or PersonalizationData()

    _print_personalize_welcome()

    if not _ask_yes_no("开始个性化配置? / Start personalization?", input_func):
        _print_cancelled()
        return None

    # Steps 1-4: protected paths, risk areas, known intentional, dimension focus.
    _run_personalize_steps_1_4(data, input_func)

    # Steps 5-9: fix priority, forbidden fixes, notes, conventions, extra commands.
    _run_personalize_steps_5_9(data, input_func)

    if not _confirm_personalization_summary(data, input_func):
        _print_cancelled()
        return None

    return data


def _run_personalize_steps_1_4(data: PersonalizationData, input_func: InputFunc) -> None:
    """Run wizard steps 1-4 (protected paths, risk areas, known intentional, focus)."""
    # Step 1: Protected paths
    data.protected_paths = _run_string_list_step(
        title="禁区 / Protected Files",
        description="iterate 不得修改的文件或目录（支持 glob）。\n"
        "Files/dirs iterate must never modify (glob patterns supported).",
        items=data.protected_paths,
        add_prompt="输入 glob 路径 / Enter glob pattern (e.g. legacy/**, vendor/**)",
        input_func=input_func,
    )

    # Step 2: Risk areas
    data.risk_areas = _run_typed_list_step(
        title="风险区 / Risk Areas",
        description="改动需架构审批的文件/目录。\n"
        "Files/dirs where changes require architectural approval.",
        items=data.risk_areas,
        formatter=lambda r: f"`{r.path}` — {r.reason}",
        add_func=_add_risk_area,
        input_func=input_func,
    )

    # Step 3: Known intentional (suppress false positives)
    data.known_intentional = _run_typed_list_step(
        title="已知意图 / Known Intentional",
        description="抑制特定 finding（文件:行号 + 维度）。\n"
        "Suppress specific findings (file:line + dimension).",
        items=data.known_intentional,
        formatter=lambda k: f"`{k.file}:{k.line}` [{k.dimension}] — {k.reason}",
        add_func=_add_known_intentional,
        input_func=input_func,
    )

    # Step 4: Dimension focus overrides
    data.dimension_focus = _run_typed_list_step(
        title="维度定制 / Dimension Focus Overrides",
        description="为特定维度追加 focus 内容。\n"
        "Append extra focus text to specific dimensions.",
        items=data.dimension_focus,
        formatter=lambda d: f"[{d.dimension}] {d.focus}",
        add_func=_add_dimension_focus,
        input_func=input_func,
    )


def _run_personalize_steps_5_9(data: PersonalizationData, input_func: InputFunc) -> None:
    """Run wizard steps 5-9 (priority, forbidden fixes, notes, conventions, commands)."""
    # Step 5: Fix priority order
    data.fix_priority_order = _run_fix_priority_step(data.fix_priority_order, input_func)

    # Step 6: Forbidden fixes
    data.forbidden_fixes = _run_string_list_step(
        title="禁止的修复方式 / Forbidden Fixes",
        description="iterate 不得使用的修复手法。\n"
        "Fix approaches iterate must never use.",
        items=data.forbidden_fixes,
        add_prompt="输入禁止方式 / Enter forbidden fix (e.g. 'try-catch 吞错', '# noqa')",
        input_func=input_func,
    )

    # Step 7: Iterate notes
    data.iterate_notes = _run_string_list_step(
        title="Iterate 注意点 / Iterate Notes",
        description="经验教训、已知陷阱、给 iterate 的提示。\n"
        "Lessons, pitfalls, tips for iterate.",
        items=data.iterate_notes,
        add_prompt="输入注意点 / Enter note",
        input_func=input_func,
    )

    # Step 8: Custom code conventions
    data.code_conventions = _run_string_list_step(
        title="自定义代码约定 / Custom Code Conventions",
        description="项目特有的代码规范。\n"
        "Project-specific code conventions.",
        items=data.code_conventions,
        add_prompt="输入约定 / Enter convention",
        input_func=input_func,
    )

    # Step 9: Extra validation commands
    data.extra_validation_commands = _run_validation_commands_step(
        data.extra_validation_commands, input_func
    )


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------


def _run_string_list_step(
    title: str,
    description: str,
    items: list[str],
    add_prompt: str,
    input_func: InputFunc,
) -> list[str]:
    """Run a step that manages a simple list of strings.

    Shows current items, allows add/remove/skip in a loop.
    """
    current = list(items)
    while True:
        tui.empty_line()
        tui.section(title)
        tui.info(description)
        tui.empty_line()
        _print_numbered_list(current)
        tui.empty_line()
        choice = input_func("  └ [a]dd / [r]emove / [s]kip: ").strip().lower()
        if choice in ("s", ""):
            return current
        if choice == "a":
            value = input_func(f"  └ {add_prompt}: ").strip()
            if value:
                current.append(value)
                tui.success("已添加 / Added", indent=2)
            else:
                tui.hint("空输入，跳过 / Empty, skipped", indent=2)
        elif choice == "r" and current:
            idx = _read_index(current, input_func)
            if idx is not None:
                current.pop(idx)
                tui.success("已删除 / Removed", indent=2)
        else:
            _print_invalid_choice()


def _run_typed_list_step(
    title: str,
    description: str,
    items: list[Any],
    formatter: Callable[[Any], str],
    add_func: Callable[[InputFunc], Any | None],
    input_func: InputFunc,
) -> list[Any]:
    """Run a step that manages a list of typed objects.

    ``add_func`` is called with ``input_func`` and must return a new
    object or None if the user cancels input.  ``formatter`` renders
    each item for display.
    """
    current = list(items)
    while True:
        tui.empty_line()
        tui.section(title)
        tui.info(description)
        tui.empty_line()
        _print_numbered_list([formatter(item) for item in current])
        tui.empty_line()
        choice = input_func("  └ [a]dd / [r]emove / [s]kip: ").strip().lower()
        if choice in ("s", ""):
            return current
        if choice == "a":
            new_item = add_func(input_func)
            if new_item is not None:
                current.append(new_item)
                tui.success("已添加 / Added", indent=2)
        elif choice == "r" and current:
            idx = _read_index(current, input_func)
            if idx is not None:
                current.pop(idx)
                tui.success("已删除 / Removed", indent=2)
        else:
            _print_invalid_choice()


def _run_fix_priority_step(
    current_order: list[str],
    input_func: InputFunc,
) -> list[str]:
    """Run the fix priority ordering step.

    Lets the user specify which dimensions to fix first.
    """
    tui.empty_line()
    tui.section("优先修复顺序 / Fix Priority Order")
    tui.info("指定维度修复优先级（从高到低）。留空跳过保持默认。")
    tui.hint("Specify dimension fix priority (high to low). Leave empty to skip.", indent=2)
    tui.empty_line()
    if current_order:
        tui.info("当前顺序 / Current order:")
        for i, dim in enumerate(current_order, 1):
            tui.info(f"{i}. {dim}", indent=4)
        tui.empty_line()
    tui.info("可用维度 / Available dimensions:")
    for i, dim in enumerate(ALL_DIMENSIONS, 1):
        tui.info(f"{i}. {DIMENSION_LABELS[dim]}", indent=4)
    tui.empty_line()

    tui.question("输入维度编号（逗号分隔，按优先级从高到低）/ Enter numbers (high to low priority):")
    raw = input_func("  └ ").strip()
    if not raw:
        return list(current_order)

    selected = _parse_dimension_numbers(raw)
    if not selected:
        tui.warning("无效输入，保持原顺序 / Invalid input, keeping current order.", indent=4)
        return list(current_order)

    tui.empty_line()
    tui.info("新顺序 / New order:")
    for i, dim in enumerate(selected, 1):
        tui.info(f"{i}. {dim}", indent=4)
    tui.empty_line()
    if _ask_yes_no("确认? / Confirm?", input_func, default=True):
        return selected
    return list(current_order)


def _run_validation_commands_step(
    current: dict[str, list[str]],
    input_func: InputFunc,
) -> dict[str, list[str]]:
    """Run the extra validation commands step."""
    result = {k: list(v) for k, v in current.items()}
    while True:
        tui.empty_line()
        tui.section("补充验证命令 / Extra Validation Commands")
        tui.info("项目特有的验证命令，会合并到 validation.commands。")
        tui.hint("Project-specific validation commands, merged into validation.commands.", indent=2)
        tui.info("命令前缀会自动加入 command_whitelist。")
        tui.hint("Command prefixes are auto-added to command_whitelist.", indent=2)
        tui.empty_line()
        if result:
            for module, cmds in result.items():
                tui.bullet(f"[{module}]", indent=4)
                for cmd in cmds:
                    tui.info(f"- {cmd}", indent=6)
        else:
            tui.hint("(空 / empty)", indent=4)
        tui.empty_line()
        choice = input_func("  └ [a]dd / [r]emove / [s]kip: ").strip().lower()
        if choice in ("s", ""):
            return result
        if choice == "a":
            module = input_func("  └ 模块名 / Module name (e.g. python, swift): ").strip()
            if not module:
                tui.hint("空模块名，跳过 / Empty module, skipped", indent=2)
                continue
            if not MODULE_NAME_PATTERN.match(module):
                tui.warning("无效模块名（仅允许字母、数字、._-）/ Invalid module name", indent=2)
                continue
            cmd = input_func(f"  └ {module} 命令 / command: ").strip()
            if not cmd:
                tui.hint("空命令，跳过 / Empty command, skipped", indent=2)
                continue

            # v2.0.2: strict whitelist — rejects shell-chaining
            # metacharacters AND unknown command prefixes. No
            # confirmation bypass; only pre-approved tooling is allowed.
            is_valid, reason = validate_extra_command(cmd)
            if not is_valid:
                tui.error(f"拒绝 / Rejected: {reason}", indent=2)
                continue

            existing = result.get(module, [])
            if cmd not in existing:
                existing.append(cmd)
                result[module] = existing
                tui.success("已添加 / Added", indent=2)
            else:
                tui.hint("命令已存在 / Command already exists", indent=2)
        elif choice == "r" and result:
            modules = list(result.keys())
            tui.info("选择模块 / Select module:", indent=2)
            for i, m in enumerate(modules, 1):
                tui.info(f"{i}. {m}", indent=4)
            idx = _read_index(modules, input_func, prompt="模块编号 / Module number")
            if idx is not None:
                result.pop(modules[idx])
                tui.success("已删除 / Removed", indent=2)
        else:
            _print_invalid_choice()


# ---------------------------------------------------------------------------
# Typed add helpers
# ---------------------------------------------------------------------------


def _add_risk_area(input_func: InputFunc) -> RiskArea | None:
    """Collect a single RiskArea from the user."""
    path = input_func("  └ 路径 / Path (e.g. src/auth/): ").strip()
    if not path:
        return None
    reason = input_func("  └ 原因 / Reason: ").strip()
    if not reason:
        reason = "(未说明 / unspecified)"
    return RiskArea(path=path, reason=reason)


def _read_dimension_number(input_func: InputFunc, prompt: str) -> str | None:
    """Read a 1-based dimension selection, returning the dimension key.

    Returns None if the input is invalid/out of range or the user cancels,
    in which case the caller aborts the current add step.

    Args:
        input_func: Input callable.
        prompt: Input prompt text.

    Returns:
        The selected dimension key, or None on invalid/cancelled input.
    """
    tui.info("选择维度 / Select dimension:", indent=2)
    for i, dim in enumerate(ALL_DIMENSIONS, 1):
        tui.info(f"{i}. {DIMENSION_LABELS[dim]}", indent=4)
    dim_str = input_func(f"  └ {prompt}: ").strip()
    try:
        dim_idx = int(dim_str) - 1
        if not (0 <= dim_idx < len(ALL_DIMENSIONS)):
            tui.warning("无效维度编号，已取消 / Invalid dimension number, cancelled", indent=2)
            return None
        return ALL_DIMENSIONS[dim_idx]
    except ValueError:
        tui.warning("无效输入，已取消 / Invalid input, cancelled", indent=2)
        return None


def _add_known_intentional(input_func: InputFunc) -> KnownIntentional | None:
    """Collect a single KnownIntentional entry from the user.

    Returns None if the user cancels at any step or enters an invalid
    dimension (rather than silently using an empty dimension string).
    """
    file_path = input_func("  └ 文件路径 / File path (e.g. db/queries.py): ").strip()
    if not file_path:
        return None
    line_str = input_func("  └ 行号 / Line number (0 或留空表示整个文件 / 0 or empty for whole file): ").strip()
    try:
        line = int(line_str) if line_str else 0
    except ValueError:
        line = 0
    # Negative line numbers have no whole-file meaning and would be
    # mis-rendered (see to_user_md_sections: line > 0 renders a specific
    # line, else "whole file"). Normalise stray negatives to whole-file
    # rather than persisting a corrupt entry.
    line = max(line, 0)
    dimension = _read_dimension_number(input_func, "维度编号 / Dimension number")
    if dimension is None:
        return None
    reason = input_func("  └ 原因 / Reason: ").strip()
    if not reason:
        reason = "(未说明 / unspecified)"
    return KnownIntentional(file=file_path, line=line, dimension=dimension, reason=reason)


def _add_dimension_focus(input_func: InputFunc) -> DimensionFocusOverride | None:
    """Collect a single DimensionFocusOverride from the user."""
    dimension = _read_dimension_number(input_func, "维度编号 / Dimension number")
    if dimension is None:
        return None
    focus = input_func(f"  └ 追加 focus 内容 / Extra focus text for [{dimension}]: ").strip()
    if not focus:
        return None
    return DimensionFocusOverride(dimension=dimension, focus=focus)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _print_personalize_welcome() -> None:
    """Print the personalization wizard welcome banner."""
    tui.intro(
        "Iterate Skill — 个性化配置 / Personalization",
        "捕获 AI 扫描不到的项目专属约束和经验 / Capture project-specific constraints AI scanning misses",
    )
    tui.info("本向导收集 9 类个性化配置：")
    tui.hint("This wizard collects 9 categories of personalization:", indent=2)
    tui.numbered_list([
        "禁区/保护文件 — iterate 不得修改",
        "风险区 — 改动需架构审批",
        "已知意图 — 抑制误报",
        "维度定制 — 追加 focus",
        "优先修复顺序 — 修复优先级",
        "禁止的修复方式 — 不可使用的修复手法",
        "Iterate 注意点 — 经验教训",
        "自定义代码约定 — 项目特有规范",
        "补充验证命令 — 合并到 validation.commands",
    ], indent=4)
    tui.empty_line()
    tui.hint("每步可跳过。结构化规则写入 iterate.config.yaml，自由文本写入 ITERATE.md 用户区。")


def _print_numbered_list(items: list[Any]) -> None:
    """Print a numbered list or empty placeholder."""
    if not items:
        tui.hint("(空 / empty)", indent=2)
        return
    for i, item in enumerate(items, 1):
        tui.info(f"{i}. {item}", indent=4)


def _read_index(
    items: list[Any],
    input_func: InputFunc,
    prompt: str = "删除编号 / Remove number",
) -> int | None:
    """Read a 1-based index from user input and convert to 0-based.

    Returns None if the input is invalid or out of range.
    """
    raw = input_func(f"  └ {prompt} (1-{len(items)}): ").strip()
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(items):
            return idx
        tui.warning(f"超出范围 / Out of range (1-{len(items)})", indent=2)
        return None
    except ValueError:
        tui.warning("无效输入 / Invalid input", indent=2)
        return None


def _parse_dimension_numbers(raw: str) -> list[str]:
    """Parse comma-separated dimension numbers into a list of dimension keys."""
    result: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            num = int(part)
        except ValueError:
            return []
        if num < 1 or num > len(ALL_DIMENSIONS):
            return []
        dim = ALL_DIMENSIONS[num - 1]
        if dim not in result:
            result.append(dim)
    return result


def _confirm_personalization_summary(
    data: PersonalizationData,
    input_func: InputFunc,
) -> bool:
    """Show a summary of personalization data and ask for confirmation."""
    tui.section("确认个性化配置 / Confirm Personalization")
    tui.key_value("禁区 / Protected", str(len(data.protected_paths)))
    tui.key_value("风险区 / Risk areas", str(len(data.risk_areas)))
    tui.key_value("已知意图 / Intentional", str(len(data.known_intentional)))
    tui.key_value("维度定制 / Dim focus", str(len(data.dimension_focus)))
    tui.key_value("优先顺序 / Fix priority", str(len(data.fix_priority_order)))
    tui.key_value("禁止方式 / Forbidden", str(len(data.forbidden_fixes)))
    tui.key_value("注意点 / Notes", str(len(data.iterate_notes)))
    tui.key_value("代码约定 / Conventions", str(len(data.code_conventions)))
    tui.key_value("验证命令 / Extra cmds", str(sum(len(v) for v in data.extra_validation_commands.values())))
    tui.empty_line()
    if data.is_empty():
        tui.warning("所有类别为空 / All categories empty", indent=2)
        tui.empty_line()
    return _ask_yes_no("确认保存? / Confirm and save?", input_func)


def _print_cancelled() -> None:
    """Print cancellation message."""
    tui.cancel()


def _print_invalid_choice() -> None:
    """Print invalid choice message."""
    tui.warning("请输入 a / r / s / Please enter a / r / s", indent=2)
