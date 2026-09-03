"""Non-interactive config inspection and editing (``iterate config``).

``iterate config`` fills the gap left by the interactive wizard: after
onboarding, users can read and modify individual config values without
hand-editing ``iterate.config.yaml`` or re-running the interactive wizard.

Commands:
- ``iterate config``            — print the resolved config (TUI).
- ``iterate config get [key]``  — print one resolved value (or all).
- ``iterate config set k v``    — validate and write a single value
                                  (with a timestamped backup).

Only the flat keys ``iterate show`` reports are settable; the complex
sections (``validation``, ``personalization``, ``onboarding``) are managed
through their dedicated flows and intentionally out of scope here.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from iterate_cli.doctor import (
    CANONICAL_DIMENSIONS,
    MAX_ROUNDS_MAX,
    MAX_ROUNDS_MIN,
    SUPPORTED_LANGUAGES,
    SUPPORTED_SCOPES,
)
from iterate_cli.generator import (
    REASONING_EFFORT_VALUES,
    atomic_write,
)
from iterate_cli.personalize import CorruptConfigError, load_config_strict
from iterate_cli.refresh import CONFIG_YAML, load_onboarding_config
from iterate_cli.tui import tui


class ConfigValueError(ValueError):
    """Raised when a ``config set`` value fails validation."""


@dataclass(frozen=True)
class ConfigKeySpec:
    """Schema for a settable flat config key.

    Attributes:
        name: The flat key name (matches ``iterate show`` output).
        validator: Parses + validates the raw CLI value; returns the parsed
            value or raises :class:`ConfigValueError`.
        path: Nested dict path to write to (``()`` = top-level key).
    """

    name: str
    validator: Callable[[str], Any]
    path: tuple[str, ...]


def _parse_non_empty_string(raw: str) -> str:
    """Validate a non-empty trimmed string."""
    value = raw.strip()
    if not value:
        raise ConfigValueError("value must be a non-empty string.")
    return value


def _parse_int(min_value: int, max_value: int | None) -> Callable[[str], int]:
    """Build a validator for an integer within ``[min_value, max_value]``."""

    def _validate(raw: str) -> int:
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise ConfigValueError(f"value must be an integer, got {raw!r}.") from exc
        if value < min_value:
            raise ConfigValueError(f"value must be >= {min_value}.")
        if max_value is not None and value > max_value:
            raise ConfigValueError(f"value must be <= {max_value}.")
        return value

    return _validate


def _parse_bool(raw: str) -> bool:
    """Validate a boolean-like value (true/false/yes/no/1/0)."""
    normalized = raw.strip().lower()
    if normalized in ("true", "yes", "1"):
        return True
    if normalized in ("false", "no", "0"):
        return False
    raise ConfigValueError(
        f"value must be a boolean (true/false/yes/no/1/0), got {raw!r}."
    )


def _parse_reasoning_effort(raw: str) -> str | None:
    """Validate reasoning_effort; empty/'default' maps to provider default."""
    normalized = raw.strip().lower()
    if not normalized or normalized == "default":
        return None
    if normalized in REASONING_EFFORT_VALUES:
        return normalized
    raise ConfigValueError(
        "value must be low, medium or high (or 'default' for provider default), "
        f"got {raw!r}."
    )


def _parse_dimensions(raw: str) -> list[str]:
    """Validate a comma-separated dimension list (non-empty, unique, canonical)."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise ConfigValueError("value must contain at least one dimension.")
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        if part not in CANONICAL_DIMENSIONS:
            raise ConfigValueError(
                f"unknown dimension {part!r}; valid: {', '.join(CANONICAL_DIMENSIONS)}."
            )
        if part not in seen:
            seen.add(part)
            result.append(part)
    return result


def _parse_enum(valid: frozenset[str]) -> Callable[[str], str]:
    """Build a validator for an enum of strings."""

    def _validate(raw: str) -> str:
        value = raw.strip().lower()
        if value not in valid:
            raise ConfigValueError(
                f"value must be one of {', '.join(sorted(valid))}, got {raw!r}."
            )
        return value

    return _validate


#: Flat keys settable via ``iterate config set``, mirroring ``iterate show``.
SETTABLE_KEYS: dict[str, ConfigKeySpec] = {
    "goal": ConfigKeySpec("goal", _parse_non_empty_string, ()),
    "max_rounds": ConfigKeySpec(
        "max_rounds", _parse_int(MAX_ROUNDS_MIN, MAX_ROUNDS_MAX), ()
    ),
    "reasoning_effort": ConfigKeySpec(
        "reasoning_effort", _parse_reasoning_effort, ()
    ),
    "language": ConfigKeySpec(
        "language", _parse_enum(frozenset(SUPPORTED_LANGUAGES)), ()
    ),
    "mode": ConfigKeySpec(
        "mode", _parse_enum(frozenset({"iterate", "defensive"})), ()
    ),
    "dimensions": ConfigKeySpec("dimensions", _parse_dimensions, ()),
    "atomic_max_lines": ConfigKeySpec(
        "atomic_max_lines", _parse_int(1, None), ("atomic", "max_lines")
    ),
    "atomic_max_adjacent_methods": ConfigKeySpec(
        "atomic_max_adjacent_methods",
        _parse_int(1, None),
        ("atomic", "max_adjacent_methods"),
    ),
    "use_worktree": ConfigKeySpec(
        "use_worktree", _parse_bool, ("git", "use_worktree")
    ),
    "auto_merge": ConfigKeySpec("auto_merge", _parse_bool, ("git", "auto_merge")),
    "target_branch": ConfigKeySpec(
        "target_branch", _parse_non_empty_string, ("git", "target_branch")
    ),
    "push_per_round": ConfigKeySpec(
        "push_per_round", _parse_bool, ("git", "push_per_round")
    ),
    "review_scope": ConfigKeySpec(
        "review_scope", _parse_enum(frozenset(SUPPORTED_SCOPES)), ("review", "scope")
    ),
    "output_schema_validation": ConfigKeySpec(
        "output_schema_validation",
        _parse_bool,
        ("reviewer", "output_schema_validation"),
    ),
    "evidence_validation": ConfigKeySpec(
        "evidence_validation", _parse_bool, ("reviewer", "evidence_validation")
    ),
    "coverage_validation": ConfigKeySpec(
        "coverage_validation", _parse_bool, ("reviewer", "coverage_validation")
    ),
    "scope_chunk_size": ConfigKeySpec(
        "scope_chunk_size", _parse_int(1, None), ("reviewer", "scope_chunk_size")
    ),
}


def _resolved_config(project_root: Path) -> dict[str, Any] | None:
    """Load the project config, or None when unreadable/missing."""
    return load_onboarding_config(project_root)


def _format_value(value: Any) -> str:
    """Render a config value for display; None renders as 'default'."""
    if value is None:
        return "default"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def run_config_get(
    project_root: Path, key: str | None, json_output: bool = False
) -> int:
    """Print one resolved config value (or all) to stdout.

    Args:
        project_root: Project root directory.
        key: Flat key to print; when None, prints every settable key.
        json_output: When True, emit a structured JSON object (single ``{[key]:
            value}``, or all keys) instead of TUI-formatted lines — matching
            the ``iterate status/show/doctor --json`` contract for scripts/CI.

    Returns:
        Exit code: 0 on success, 1 when the config is missing or the key is
        unknown.
    """
    config = _resolved_config(project_root)
    if config is None:
        tui.error("iterate.config.yaml is missing or unreadable. Run 'iterate onboard' first.")
        return 1

    def _read(spec: ConfigKeySpec) -> Any:
        if not spec.path:
            return config.get(spec.name)
        section: Any = config
        for part in spec.path:
            if not isinstance(section, dict) or part not in section:
                return None
            section = section[part]
        return section

    if key is not None:
        spec = SETTABLE_KEYS.get(key)
        if spec is None:
            tui.error(f"Unknown config key {key!r}. Use `iterate config` to list keys.")
            return 1
        value = _read(spec)
        if json_output:
            print(json.dumps({key: value}, ensure_ascii=False))
        else:
            print(_format_value(value))
        return 0

    if json_output:
        print(
            json.dumps(
                {name: _read(spec) for name, spec in SETTABLE_KEYS.items()},
                ensure_ascii=False,
            )
        )
        return 0

    for name, spec in SETTABLE_KEYS.items():
        tui.key_value(name.replace("_", " ").title(), _format_value(_read(spec)))
    return 0


def run_config_set(
    project_root: Path, key: str, raw_value: str, json_output: bool = False
) -> int:
    """Validate and write a single config value (with a timestamped backup).

    Refuses to modify a corrupt/missing config so a damaged file is never
    silently overwritten.

    Args:
        project_root: Project root directory.
        key: Flat config key to set.
        raw_value: Raw CLI value to parse and validate.
        json_output: When True, emit a JSON confirmation object instead of TUI
            lines. Errors are still reported on stderr with a non-zero code.

    Returns:
        Exit code: 0 on success, 1 on unknown key / invalid value / write
        failure.
    """
    spec = SETTABLE_KEYS.get(key)
    if spec is None:
        tui.error(
            f"Unknown config key {key!r}. Settable keys: {', '.join(SETTABLE_KEYS)}."
        )
        return 1

    try:
        parsed = spec.validator(raw_value)
    except ConfigValueError as exc:
        tui.error(f"Invalid value for {key!r}: {exc}")
        return 1

    config_path = project_root / CONFIG_YAML
    if not config_path.is_file():
        tui.error("iterate.config.yaml not found. Run 'iterate onboard' first.")
        return 1
    try:
        config = load_config_strict(config_path)
    except (CorruptConfigError, OSError, UnicodeDecodeError) as exc:
        tui.error(f"Cannot read iterate.config.yaml: {exc}")
        return 1

    section: Any = config
    for part in spec.path[:-1]:
        if not isinstance(section.get(part), dict):
            section[part] = {}
        section = section[part]
    if spec.path:
        section[spec.path[-1]] = parsed
    else:
        config[spec.name] = parsed

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = config_path.with_name(f"{CONFIG_YAML}.configset-{timestamp}")
    try:
        shutil.copy2(config_path, backup_path)
        atomic_write(
            config_path,
            yaml.safe_dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False),
        )
    except OSError as exc:
        tui.error(f"Failed to write {CONFIG_YAML}: {exc}")
        return 1

    if json_output:
        # Keep stdout clean for scripts/CI: only the JSON confirmation object.
        print(json.dumps({"key": key, "value": parsed}, ensure_ascii=False))
        return 0
    tui.success(f"{key} set to {_format_value(parsed)}.")
    tui.hint(f"Backup written to {backup_path.name}.", indent=2)
    return 0
