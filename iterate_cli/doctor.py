"""Project health diagnostics for the iterate skill.

``iterate doctor`` checks a project's iterate.config.yaml, ITERATE.md and
onboarding state against the skill's own canonical definitions so that a
project drifting from the skill's expectations is surfaced early.

Checks performed:
- Onboarding completeness (ITERATE.md + iterate.config.yaml exist).
- Config loads as a YAML mapping and fully matches config/config.schema.json.
- ``dimensions`` reference only canonical dimension ids.
- ``review.scope`` is one of the supported values.
- ``git.target_branch`` is a non-empty string.
- ``validation.commands`` values are non-empty lists of strings.
- ``validation.command_whitelist`` entries are safe and every command is whitelisted.
- ``personalization`` dimension references point at enabled dimensions.
- Onboarding ``skill_version`` vs the installed skill version.
- Manifest drift (tech-stack changed since onboarding).

All checks can be run in a structured (``--json``) or human (TUI) mode.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from iterate_cli import __version__ as SKILL_VERSION
from iterate_cli.generator import REASONING_EFFORT_VALUES
from iterate_cli.personalize import FORBIDDEN_COMMAND_CHARS
from iterate_cli.refresh import (
    CONFIG_YAML,
    check_onboarding_drift,
    is_onboarding_complete,
    load_onboarding_config,
)
from iterate_cli.tui import tui

# Shell-chaining metacharacters that must never appear in a whitelist entry
# or a validation command. This is the SAME canonical set as personalize.py's
# FORBIDDEN_COMMAND_CHARS (kept in sync by tests/test_validate.py) so that a
# command accepted at personalization time is also accepted by doctor, and
# vice-versa.
COMMAND_METACHARS: frozenset[str] = frozenset(FORBIDDEN_COMMAND_CHARS)

# Canonical dimension ids declared in config/dimensions.yaml (the single
# source of truth for the skill). Kept in sync by tests/test_dimension_lock.py.
CANONICAL_DIMENSIONS: tuple[str, ...] = (
    "correctness",
    "security",
    "performance",
    "architecture",
    "style-tests",
    "tech-debt",
    "spec-compliance",
    "frontend-backend",
    "ui-ux",
)

# Supported review.scope values.
SUPPORTED_SCOPES: frozenset[str] = frozenset({"full", "changed-only"})

# Supported output languages (config/schema: language enum).
SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"zh", "en"})

# Bounds enforced by config/config.schema.json for max_rounds.
MAX_ROUNDS_MIN: int = 1
MAX_ROUNDS_MAX: int = 50

# Cap on schema-violation messages reported in a single doctor run, to avoid
# flooding output when a config has many malformed keys.
SCHEMA_MAX_ERRORS: int = 5

# Config schema location: prefer the bundled copy (shipped in the package via
# pyproject package-data), fall back to the repo-relative config/ so running
# from source still works — mirrors TEMPLATE_PATH in generator.py.
_BUNDLED_SCHEMA = Path(__file__).resolve().parent / "data" / "config.schema.json"
_REPO_SCHEMA = Path(__file__).resolve().parent.parent / "config" / "config.schema.json"
SCHEMA_PATH = _BUNDLED_SCHEMA if _BUNDLED_SCHEMA.exists() else _REPO_SCHEMA


@dataclass
class DoctorFinding:
    """A single diagnostic finding."""

    severity: str  # "ok" | "warn" | "error"
    check: str
    message: str
    detail: str = ""


@dataclass
class DoctorReport:
    """Aggregated doctor output for a project."""

    project: str
    findings: list[DoctorFinding] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)

    def has_errors(self) -> bool:
        return any(f.severity == "error" for f in self.findings)

    def has_warnings(self) -> bool:
        return any(f.severity == "warn" for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        """Structured representation for ``--json`` output."""
        return {
            "project": self.project,
            "skill_version": SKILL_VERSION,
            "healthy": not self.has_errors(),
            "fixes": list(self.fixes),
            "findings": [
                {
                    "severity": f.severity,
                    "check": f.check,
                    "message": f.message,
                    "detail": f.detail,
                }
                for f in self.findings
            ],
        }


def _ok(report: DoctorReport, check: str, message: str) -> None:
    report.findings.append(DoctorFinding("ok", check, message))


def _warn(report: DoctorReport, check: str, message: str, detail: str = "") -> None:
    report.findings.append(DoctorFinding("warn", check, message, detail))


def _err(report: DoctorReport, check: str, message: str, detail: str = "") -> None:
    report.findings.append(DoctorFinding("error", check, message, detail))


def _dimension_ids(config: dict[str, Any]) -> list[str]:
    """Return the declared dimensions.

    - ``dimensions`` absent → canonical defaults (schema makes it optional).
    - ``dimensions`` a list → its entries as strings.
    - ``dimensions`` present but NOT a list (e.g. a scalar string from a
      hand-edited config) → ``[]``, so ``_check_dimensions`` reports the
      malformed value as an error instead of silently treating it as "all
      canonical" and declaring the config healthy.
    """
    dims = config.get("dimensions")
    if dims is None:
        return list(CANONICAL_DIMENSIONS)
    if isinstance(dims, list):
        return [str(d) for d in dims]
    return []


def _load_config_schema() -> dict[str, Any] | None:
    """Load the canonical config JSON Schema, or None if unavailable.

    Uses the packaged copy (SCHEMA_PATH) so doctor works both from source
    and inside an installed package. Returns None when the schema file is
    missing or malformed, in which case schema validation is skipped.
    """
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return schema if isinstance(schema, dict) else None


def _schema_violations(config: dict[str, Any]) -> list[str] | None:
    """Validate ``config`` against the canonical JSON Schema.

    Returns a list of human-readable ``path: message`` violations (empty when
    the config is valid), or ``None`` when schema validation is **unavailable**
    (schema file missing/malformed or ``jsonschema`` not installed) so the
    caller can distinguish "fully matches" from "validation skipped" instead of
    reporting a false success. Mirrors the schema pass in scripts/validate.py.
    """
    schema = _load_config_schema()
    if schema is None:
        return None
    try:
        from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
    except ImportError:
        return None
    violations: list[str] = []
    try:
        validator = Draft202012Validator(schema)
    except ValueError:
        # Schema is structurally invalid (e.g. malformed ``$ref`` / type
        # constraint). Skipping schema validation is safer than crashing the
        # whole doctor run on a broken schema file.
        return None
    for error in validator.iter_errors(config):
        path = "/".join(str(part) for part in error.path) or "<root>"
        violations.append(f"{path}: {error.message}")
    return violations


def _command_is_whitelisted(command: Any, whitelist: Any) -> bool:
    """True when a command equals or is prefixed by a whitelisted entry.

    Mirrors scripts/validate.py::command_is_whitelisted: a command is allowed
    when it equals a whitelisted prefix, or starts with one followed by
    whitespace (so ``pytest tests/`` is ``pytest`` plus an argument). Also
    rejects shell-chaining metacharacters anywhere in the command body, so a
    whitelisted prefix cannot be abused to smuggle ``; rm -rf /`` style
    side effects past the check.
    """
    if not isinstance(command, str) or not isinstance(whitelist, list):
        return False
    stripped = command.strip()
    for ch in stripped:
        if ch in COMMAND_METACHARS:
            return False
    for prefix in whitelist:
        if not isinstance(prefix, str):
            continue
        if stripped == prefix:
            return True
        if (
            len(stripped) > len(prefix)
            and stripped.startswith(prefix)
            and stripped[len(prefix)].isspace()
        ):
            return True
    return False


def run_doctor(project_root: Path) -> DoctorReport:
    """Run all health checks against ``project_root``.

    Each check is factored into a single-purpose ``_check_*`` function so
    the orchestration stays readable and each check stays under the
    function-length / nesting budget. The two fatal checks (onboarding
    completeness, config parse) short-circuit the run: nothing downstream
    can be validated without a parsed config.

    Args:
        project_root: Project root directory.

    Returns:
        A DoctorReport aggregating every finding.
    """
    report = DoctorReport(str(project_root))

    if not _check_onboarding(report, project_root):
        return report
    config = _check_config_parse(report, project_root)
    if config is None:
        return report

    _check_config_schema(report, config)
    _check_dimensions(report, config)
    _check_max_rounds(report, config)
    _check_reasoning_effort(report, config)
    _check_language(report, config)
    _check_review_scope(report, config)
    _check_git_branch(report, config)
    _check_validation_commands(report, config)
    _check_validation_whitelist(report, config)
    _check_skill_version(report, config)
    _check_manifest_drift(report, project_root)
    _check_personalization(report, config)
    _check_dimension_sets(report, config)

    return report


def _check_onboarding(report: DoctorReport, project_root: Path) -> bool:
    """Check onboarding completeness; return False to stop the run."""
    if not is_onboarding_complete(project_root):
        _err(
            report,
            "onboarding",
            "Onboarding is not complete: ITERATE.md is missing.",
            "Run `iterate onboard` to initialize the project.",
        )
        return False
    _ok(report, "onboarding", "ITERATE.md present.")
    return True


def _check_config_parse(
    report: DoctorReport, project_root: Path
) -> dict[str, Any] | None:
    """Load the config as a YAML mapping; return None to stop the run."""
    config = load_onboarding_config(project_root)
    if config is None:
        _err(
            report,
            "config.parse",
            "iterate.config.yaml is missing, unreadable, or not a YAML mapping.",
        )
        return None
    _ok(report, "config.parse", "iterate.config.yaml parsed as a valid YAML mapping.")
    return config


def _check_config_schema(report: DoctorReport, config: dict[str, Any]) -> None:
    """Full config validation against the canonical JSON Schema.

    Surfaced as a warning (not an error) so valid-but-tuned configs that a
    targeted check already flags (e.g. unknown dimension) keep their warn
    severity.
    """
    schema_violations = _schema_violations(config)
    if schema_violations is None:
        # Validation itself is unavailable (missing schema/jsonschema). Report
        # a warning instead of a false "fully matches" success so the operator
        # knows the schema gate did not actually run.
        _warn(
            report,
            "config.schema",
            "Config schema validation could not run (schema file or jsonschema unavailable).",
        )
        return
    if not schema_violations:
        _ok(report, "config.schema", "iterate.config.yaml fully matches the config schema.")
        return
    shown = schema_violations[:SCHEMA_MAX_ERRORS]
    detail = "\n".join(f"  - {violation}" for violation in shown)
    if len(schema_violations) > SCHEMA_MAX_ERRORS:
        detail += f"\n  … and {len(schema_violations) - SCHEMA_MAX_ERRORS} more violation(s)."
    _warn(
        report,
        "config.schema",
        f"iterate.config.yaml does not fully match the schema ({len(schema_violations)} violation(s)).",
        detail,
    )


def _check_dimensions(report: DoctorReport, config: dict[str, Any]) -> None:
    """Dimensions must reference canonical ids, be non-empty and unique."""
    canonical_set = set(CANONICAL_DIMENSIONS)
    dims = _dimension_ids(config)

    raw = config.get("dimensions")
    if raw is not None and not isinstance(raw, list):
        # A scalar/non-list dimensions value (e.g. `dimensions: "correctness"`)
        # is malformed: report it as an error and stop — the per-entry checks
        # below would otherwise be meaningless (and a previous fallback to the
        # canonical list silently reported such configs as "healthy").
        _err(
            report,
            "dimensions",
            "dimensions must be a list of canonical dimension ids.",
            f"Got {type(raw).__name__} instead of a list.",
        )
        return

    # Empty list is a hard error: emit it first and return so we never
    # also report the verbose "all configured dimensions are canonical"
    # success line for the same check (which would contradict it).
    if not dims:
        _err(report, "dimensions", "dimensions must not be an empty list.", "Configure at least one dimension.")
        return

    unknown = [d for d in dims if d not in canonical_set]
    if unknown:
        _warn(
            report,
            "dimensions",
            f"Config references {len(unknown)} unknown dimension(s): {', '.join(sorted(unknown))}.",
            "Unknown dimensions are ignored by reviewers; check config/dimensions.yaml.",
        )
    else:
        _ok(report, "dimensions", f"All {len(dims)} configured dimension(s) are canonical.")

    seen: set[str] = set()
    dups: list[str] = []
    for d in dims:
        if d in seen:
            dups.append(d)
        else:
            seen.add(d)
    if dups:
        _warn(
            report,
            "dimensions",
            f"dimensions contains duplicate(s): {', '.join(sorted(set(dups)))}.",
            "Remove duplicate entries (schema requires uniqueItems).",
        )


def _check_max_rounds(report: DoctorReport, config: dict[str, Any]) -> None:
    """max_rounds must be an integer within [MAX_ROUNDS_MIN, MAX_ROUNDS_MAX]."""
    max_rounds = config.get("max_rounds")
    if max_rounds is None:
        return
    if (
        not isinstance(max_rounds, int)
        or isinstance(max_rounds, bool)
        or not (MAX_ROUNDS_MIN <= max_rounds <= MAX_ROUNDS_MAX)
    ):
        _err(
            report,
            "max_rounds",
            f"max_rounds must be an integer in [{MAX_ROUNDS_MIN}, {MAX_ROUNDS_MAX}], got {max_rounds!r}.",
        )
        return
    _ok(report, "max_rounds", f"max_rounds={max_rounds} is within bounds.")


def _check_reasoning_effort(report: DoctorReport, config: dict[str, Any]) -> None:
    """reasoning_effort must be one of the supported levels (or unset)."""
    reasoning_effort = config.get("reasoning_effort")
    if reasoning_effort is None:
        _ok(report, "reasoning_effort", "reasoning_effort not set (provider default).")
        return
    if reasoning_effort not in REASONING_EFFORT_VALUES:
        _err(
            report,
            "reasoning_effort",
            f"reasoning_effort {reasoning_effort!r} is not a supported level.",
            f"Supported: {', '.join(sorted(REASONING_EFFORT_VALUES))}.",
        )
        return
    _ok(
        report,
        "reasoning_effort",
        f"reasoning_effort={reasoning_effort!r} is a supported level.",
    )


def _check_language(report: DoctorReport, config: dict[str, Any]) -> None:
    """language must be one of the supported output languages."""
    language = config.get("language")
    if language is None:
        return
    if language not in SUPPORTED_LANGUAGES:
        _warn(
            report,
            "language",
            f"language {language!r} is not supported.",
            f"Supported: {', '.join(sorted(SUPPORTED_LANGUAGES))}.",
        )
        return
    _ok(report, "language", f"language {language!r} is supported.")


def _check_review_scope(report: DoctorReport, config: dict[str, Any]) -> None:
    """review.scope must be one of the supported values."""
    review = config.get("review") if isinstance(config.get("review"), dict) else None
    scope = review.get("scope") if review else None
    if scope is not None and scope not in SUPPORTED_SCOPES:
        _warn(
            report,
            "review.scope",
            f"review.scope {scope!r} is not a supported value.",
            f"Supported: {', '.join(sorted(SUPPORTED_SCOPES))}.",
        )
        return
    _ok(report, "review.scope", "review.scope is valid (or defaults to full).")


def _check_git_branch(report: DoctorReport, config: dict[str, Any]) -> None:
    """git.target_branch must be a non-empty string when configured."""
    git_cfg = config.get("git") if isinstance(config.get("git"), dict) else None
    branch = git_cfg.get("target_branch") if git_cfg else None
    if branch is not None and (not isinstance(branch, str) or not branch.strip()):
        _err(report, "git.target_branch", "git.target_branch must be a non-empty string.")
        return
    _ok(report, "git.target_branch", "git.target_branch is valid (or defaults to main).")


def _check_validation_commands(report: DoctorReport, config: dict[str, Any]) -> None:
    """validation.commands values must be non-empty lists of strings."""
    validation = config.get("validation") if isinstance(config.get("validation"), dict) else None
    commands = validation.get("commands") if validation else None
    if commands is None:
        _ok(report, "validation.commands", "no validation.commands configured (optional).")
        return
    if not isinstance(commands, dict):
        _err(
            report,
            "validation.commands",
            "validation.commands must be a mapping of module -> list of commands.",
        )
        return
    for module, cmds in commands.items():
        if isinstance(cmds, list) and cmds and all(isinstance(c, str) and c.strip() for c in cmds):
            continue
        _err(
            report,
            "validation.commands",
            f"validation.commands[{module!r}] must be a non-empty list of strings.",
        )
        return
    _ok(report, "validation.commands", "validation.commands module lists are valid.")


def _check_validation_whitelist(report: DoctorReport, config: dict[str, Any]) -> None:
    """command_whitelist structure (6b) and command compliance (6c).

    Even when no ``command_whitelist`` is configured, every validation
    command is still checked for shell metacharacters (6c safety net): a
    command like ``pytest; rm -rf /`` must never pass a health gate simply
    because the optional whitelist key is absent.
    """
    validation = config.get("validation") if isinstance(config.get("validation"), dict) else None
    whitelist = validation.get("command_whitelist") if validation else None
    commands = validation.get("commands") if validation else None

    if whitelist is None:
        # No whitelist constraint → structure check is not applicable, but the
        # command metacharacter check below still applies to every configured
        # command.
        if commands is not None:
            _check_commands_metachars(report, commands)
        _ok(
            report,
            "validation.command_whitelist",
            "no command_whitelist configured (optional); commands checked for shell metacharacters.",
        )
        return

    # 6b. command_whitelist must be a non-empty list of unique non-empty strings.
    invalid = not isinstance(whitelist, list) or not whitelist
    if not invalid:
        cleaned = [w for w in whitelist if isinstance(w, str) and w.strip()]
        invalid = len(cleaned) != len(whitelist) or len(set(cleaned)) != len(cleaned)
    if invalid:
        _warn(
            report,
            "validation.command_whitelist",
            "command_whitelist must be a non-empty list of unique non-empty strings.",
        )
    else:
        _ok(report, "validation.command_whitelist", "command_whitelist is a valid non-empty list.")

    # 6c. Compliance only applies when commands are also configured.
    if commands is not None:
        _check_whitelist_compliance(report, whitelist, commands)


def _check_commands_metachars(report: DoctorReport, commands: Any) -> None:
    """Every configured validation command must be free of shell metacharacters.

    This is the standalone safety net for configs without a
    ``command_whitelist``: metacharacters that allow command chaining
    (``;`` ``|`` ``&`` ``$`` ...) are rejected regardless of any whitelist,
    so a hand-edited config cannot smuggle side effects into the executable
    validation commands.
    """
    if not isinstance(commands, dict):
        return
    unsafe: list[str] = []
    for module, cmds in commands.items():
        if not isinstance(cmds, list):
            continue
        for idx, command in enumerate(cmds):
            if isinstance(command, str) and any(
                ch in COMMAND_METACHARS for ch in command
            ):
                unsafe.append(f"{module}[{idx}] {command!r}")
    if unsafe:
        _err(
            report,
            "validation.whitelist",
            "validation command(s) contain shell metacharacters (possible command chaining).",
            "; ".join(unsafe[:SCHEMA_MAX_ERRORS]),
        )


def _check_whitelist_compliance(
    report: DoctorReport, whitelist: Any, commands: Any
) -> None:
    """Every configured command must be prefixed by a whitelisted entry, and
    whitelist entries must not contain shell metacharacters."""
    # Structural problems (whitelist not a list, commands not a dict) are
    # reported by the caller/schema as a warning/error; skip to avoid a
    # TypeError/AttributeError crash on malformed-but-non-fatal config.
    if not isinstance(whitelist, list) or not isinstance(commands, dict):
        return
    safe_prefix = re.compile(r"^[A-Za-z0-9_. -]+$")
    bad_entries = [
        entry
        for entry in whitelist
        if not (isinstance(entry, str) and safe_prefix.match(entry))
    ]
    if bad_entries:
        _warn(
            report,
            "validation.whitelist",
            "command_whitelist contains entry(ies) with unsafe shell characters.",
            "Allowed in a whitelist entry: letters, digits, underscore, dash, dot and space.",
        )
        return
    non_whitelisted: list[str] = []
    unsafe: list[str] = []
    for module, cmds in commands.items():
        if not isinstance(cmds, list):
            continue
        for idx, command in enumerate(cmds):
            if not isinstance(command, str):
                continue
            # Shell metacharacters are a hard security error regardless of the
            # whitelist (matching the standalone safety net for configs without
            # a command_whitelist). Everything else falls back to prefix
            # compliance, which is a non-blocking warning.
            if any(ch in COMMAND_METACHARS for ch in command):
                unsafe.append(f"{module}[{idx}] {command!r}")
            elif not _command_is_whitelisted(command, whitelist):
                non_whitelisted.append(f"{module}[{idx}] {command!r}")
    if unsafe:
        _err(
            report,
            "validation.whitelist",
            "validation command(s) contain shell metacharacters (possible command chaining).",
            "; ".join(unsafe[:SCHEMA_MAX_ERRORS]),
        )
        return
    if non_whitelisted:
        _warn(
            report,
            "validation.whitelist",
            f"{len(non_whitelisted)} configured validation command(s) are not in command_whitelist.",
            "; ".join(non_whitelisted[:SCHEMA_MAX_ERRORS]),
        )
        return
    _ok(report, "validation.whitelist", "All configured validation commands are whitelisted.")


def _check_skill_version(report: DoctorReport, config: dict[str, Any]) -> None:
    """Onboarding skill_version vs the installed skill version."""
    onboarding = config.get("onboarding") if isinstance(config.get("onboarding"), dict) else None
    recorded_version = onboarding.get("skill_version") if onboarding else None
    if recorded_version is None:
        # No recorded version (e.g. a hand-written config without an onboarding
        # record): nothing to compare, and claiming "matches" would be false.
        _ok(
            report,
            "skill_version",
            "No recorded onboarding skill version; nothing to compare.",
        )
        return
    if recorded_version != SKILL_VERSION:
        _warn(
            report,
            "skill_version",
            f"Onboarded with skill {recorded_version!r}, but current skill is {SKILL_VERSION!r}.",
            "Run `iterate refresh` to update the recorded skill version.",
        )
        return
    _ok(report, "skill_version", f"Skill version {SKILL_VERSION!r} matches onboarding record.")


def _check_manifest_drift(report: DoctorReport, project_root: Path) -> None:
    """Manifest drift (tech-stack changed since onboarding)."""
    drift = check_onboarding_drift(project_root)
    if drift is None:
        _ok(
            report,
            "drift",
            "No drift check applicable (drift check disabled, no fingerprints recorded, or config unreadable).",
        )
        return
    if drift.has_drift:
        _warn(report, "drift", f"Manifest drift detected: {drift.summary()}", drift.advice())
        return
    _ok(report, "drift", "No manifest drift detected.")


def _check_personalization(report: DoctorReport, config: dict[str, Any]) -> None:
    """Personalization dimension references must point at enabled dimensions."""
    dims = _dimension_ids(config)
    personalization = config.get("personalization") if isinstance(config.get("personalization"), dict) else None
    if personalization is None or not dims:
        return
    enabled = set(dims)
    broken: list[str] = []
    # Guard against a hand-edited string: iterating it would flag each
    # character as a broken dimension (matching load_personalization_from_config).
    fix_priority = personalization.get("fix_priority_order")
    if isinstance(fix_priority, list):
        for idx, item in enumerate(fix_priority):
            if isinstance(item, str) and item not in enabled:
                broken.append(f"fix_priority_order[{idx}] {item!r}")
    for idx, item in enumerate(personalization.get("dimension_focus") or []):
        if not isinstance(item, dict):
            continue
        dimension = item.get("dimension")
        # Missing/empty dimension entries are skipped (matching
        # scripts/validate.py::validate_personalization_consistency) so a
        # hand-edited config with an incomplete entry is not misreported as
        # "points to disabled dimension None".
        if dimension and dimension not in enabled:
            broken.append(f"dimension_focus[{idx}] {dimension!r}")
    for idx, item in enumerate(personalization.get("known_intentional") or []):
        if not isinstance(item, dict):
            continue
        dimension = item.get("dimension")
        if dimension and dimension not in enabled:
            broken.append(f"known_intentional[{idx}] {dimension!r}")
    if broken:
        _warn(
            report,
            "personalization.consistency",
            f"{len(broken)} personalization reference(s) point to disabled dimensions.",
            "; ".join(broken[:SCHEMA_MAX_ERRORS]),
        )
        return
    _ok(report, "personalization.consistency", "personalization dimension references are consistent.")


def _check_dimension_sets(report: DoctorReport, config: dict[str, Any]) -> None:
    """dimension_sets must be well-formed and internally consistent.

    Each named set must carry a non-empty, unique ``dimensions`` list whose
    entries are canonical ids; ``focus`` overrides must only reference
    dimensions actually present in that set. Dimension sets are optional, so
    an absent ``dimension_sets`` is healthy.
    """
    raw = config.get("dimension_sets")
    if raw is None:
        _ok(report, "dimension_sets", "No dimension_sets configured (defaults to global dimensions).")
        return
    if not isinstance(raw, dict):
        _err(
            report,
            "dimension_sets",
            "dimension_sets must be a mapping of scope name to set spec.",
            f"Got {type(raw).__name__} instead.",
        )
        return

    canonical_set = set(CANONICAL_DIMENSIONS)
    name_re = re.compile(r"^[A-Za-z0-9_.-]+$")
    problems: list[str] = []
    for name, spec in raw.items():
        if not name_re.match(name):
            problems.append(f"set name {name!r} has invalid characters")
            continue
        if not isinstance(spec, dict):
            problems.append(f"{name}: spec is not a mapping")
            continue
        dims = spec.get("dimensions")
        if not isinstance(dims, list) or not dims:
            problems.append(f"{name}: dimensions must be a non-empty list")
            dims = []
        unknown = [d for d in dims if d not in canonical_set]
        if unknown:
            problems.append(f"{name}: unknown dimension(s): {', '.join(sorted(set(unknown)))}")
        seen: set[str] = set()
        for d in dims:
            if d in seen:
                problems.append(f"{name}: duplicate dimension {d!r}")
            seen.add(d)
        focus = spec.get("focus")
        if focus is not None:
            if not isinstance(focus, dict):
                problems.append(f"{name}: focus must be a mapping")
            else:
                for dim in focus:
                    if dim not in seen:
                        problems.append(f"{name}: focus[{dim!r}] not in this set's dimensions")

    if problems:
        _warn(
            report,
            "dimension_sets",
            f"{len(problems)} dimension_sets consistency issue(s).",
            "\n".join(f"  - {p}" for p in problems[:SCHEMA_MAX_ERRORS]),
        )
        return
    _ok(
        report,
        "dimension_sets",
        f"All {len(raw)} dimension_set(s) are well-formed and internally consistent.",
    )


def apply_safe_fixes(config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Apply safe, non-destructive fixes to a config dict.

    Only fixes deterministic, unambiguous problems that cannot lose user
    data. Every fix mirrors a ``doctor`` check, so a repaired config no
    longer triggers that warning/error.

    Args:
        config: The parsed iterate.config.yaml content.

    Returns:
        A tuple of (possibly-updated config, human-readable fix list).
        The fix list is empty when nothing needed fixing.
    """
    # Deep-copy so nested ``git``/``onboarding`` dicts below are never mutated
    # in the caller's original config object.
    new_config = copy.deepcopy(config)
    fixes: list[str] = []

    # dimensions: must be non-empty and unique (schema minItems/uniqueItems).
    dims = new_config.get("dimensions")
    if isinstance(dims, list):
        seen: set[str] = set()
        deduped: list[str] = []
        for d in dims:
            if d not in seen:
                deduped.append(d)
                seen.add(d)
        if len(deduped) != len(dims):
            fixes.append(f"dimensions: removed {len(dims) - len(deduped)} duplicate(s).")
        if not deduped:
            deduped = list(CANONICAL_DIMENSIONS)
            fixes.append("dimensions: empty, restored canonical defaults.")
        new_config["dimensions"] = deduped

    # language: must be one of zh/en.
    language = new_config.get("language")
    if language is not None and language not in SUPPORTED_LANGUAGES:
        new_config["language"] = "en"
        fixes.append(f"language: {language!r} invalid, reset to 'en'.")

    # reasoning_effort: must be one of low/medium/high (None = provider default).
    reasoning_effort = new_config.get("reasoning_effort")
    if reasoning_effort is not None and reasoning_effort not in REASONING_EFFORT_VALUES:
        new_config["reasoning_effort"] = None
        fixes.append(
            f"reasoning_effort: {reasoning_effort!r} invalid, reset to provider default (null)."
        )

    # max_rounds: must be an integer in [1, 50].
    max_rounds = new_config.get("max_rounds")
    if max_rounds is not None:
        if isinstance(max_rounds, bool) or not isinstance(max_rounds, int):
            new_config.pop("max_rounds", None)
            fixes.append("max_rounds: removed non-integer value.")
        elif not (MAX_ROUNDS_MIN <= max_rounds <= MAX_ROUNDS_MAX):
            clamped = max(MAX_ROUNDS_MIN, min(MAX_ROUNDS_MAX, max_rounds))
            new_config["max_rounds"] = clamped
            fixes.append(f"max_rounds: clamped to {clamped}.")

    # git.target_branch: must be a non-empty string.
    git_cfg = new_config.get("git")
    if isinstance(git_cfg, dict):
        branch = git_cfg.get("target_branch")
        if branch is not None and (not isinstance(branch, str) or not branch.strip()):
            git_cfg["target_branch"] = "main"
            fixes.append("git.target_branch: empty, reset to 'main'.")

    # onboarding.skill_version: must match the installed skill version.
    onboarding = new_config.get("onboarding")
    if isinstance(onboarding, dict):
        recorded = onboarding.get("skill_version")
        if recorded is not None and recorded != SKILL_VERSION:
            onboarding["skill_version"] = SKILL_VERSION
            fixes.append(f"onboarding.skill_version: updated {recorded!r} → {SKILL_VERSION!r}.")

    return new_config, fixes


def run_doctor_fix(project_root: Path) -> tuple[bool, list[str]]:
    """Apply safe fixes to iterate.config.yaml with a timestamped backup.

    A backup with a ``.doctorfix-<timestamp>`` suffix is written before any
    change so the original config is always recoverable. Returns
    ``(True, [])`` when nothing needed fixing.

    Args:
        project_root: Project root directory.

    Returns:
        A tuple of (success, list of applied fixes). On failure the fixes
        already detected are still returned so the caller can log them.
    """
    config_path = project_root / CONFIG_YAML
    if not config_path.is_file():
        return False, []

    config = load_onboarding_config(project_root)
    if config is None:
        return False, []

    new_config, fixes = apply_safe_fixes(config)
    if not fixes:
        return True, []

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = config_path.with_name(f"{CONFIG_YAML}.doctorfix-{timestamp}")
    try:
        shutil.copy2(config_path, backup_path)
        config_path.write_text(
            yaml.safe_dump(
                new_config,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        tui.error(f"Doctor --fix: failed to write fixed config: {exc}")
        return False, fixes
    return True, fixes


def export_report_json(report: DoctorReport, out_path: Path) -> None:
    """Write the structured DoctorReport to ``out_path`` as JSON.

    Args:
        report: The report to serialize.
        out_path: Destination file path (UTF-8, JSON with 2-space indent).

    Raises:
        OSError: When the file cannot be written.
    """
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(payload + "\n", encoding="utf-8")


def render_report(report: DoctorReport, json_output: bool = False) -> int:
    """Render a DoctorReport to the terminal.

    Args:
        report: The report to render.
        json_output: When True, print a structured JSON blob instead of TUI.

    Returns:
        Exit code: 0 when healthy (errors absent); 1 when errors are present.
        Warnings are non-blocking and do not change the exit code, but they
        are reported in the summary line (see ``_render_summary``).
    """
    if json_output:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 1 if report.has_errors() else 0

    tui.intro(f"Iterate Skill — Doctor / {report.project}")

    for finding in report.findings:
        if finding.severity == "ok":
            tui.success(f"[{finding.check}] {finding.message}", indent=2)
        elif finding.severity == "warn":
            tui.warning(f"[{finding.check}] {finding.message}", indent=2)
            if finding.detail:
                tui.hint(finding.detail, indent=4)
        else:
            tui.error(f"[{finding.check}] {finding.message}", indent=2)
            if finding.detail:
                tui.hint(finding.detail, indent=4)

    _render_next_actions(tui, report)

    _render_summary(tui, report)
    return 1 if report.has_errors() else 0


def _render_summary(tui: Any, report: DoctorReport) -> None:
    """Render the doctor end-of-run summary line.

    Distinguishes three outcomes so the summary never contradicts the
    findings shown above:
    - errors present → error summary, exit code already set to 1 by caller.
    - warnings only  → *not* reported as plain "healthy" (the checks
      surfaced warnings the operator should look at), but still non-blocking.
    - clean          → "healthy".
    """
    tui.empty_line()
    error_count = sum(1 for f in report.findings if f.severity == "error")
    warn_count = sum(1 for f in report.findings if f.severity == "warn")
    if error_count:
        tui.error(f"Doctor: {error_count} error(s) found.")
        return
    if warn_count:
        tui.warning(
            f"Doctor: healthy but with {warn_count} warning(s) — non-blocking."
        )
        return
    tui.success(f"Doctor: healthy ({len(report.findings)} checks passed).")


def _render_next_actions(tui: Any, report: DoctorReport) -> None:
    """Aggregate actionable next steps for a doctor run.

    Grep-friendly, forge a single ``Next action(s):`` block mapping the most
    common problems to the command that fixes them, so users are not left
    guessing what to do after seeing warnings/errors.
    """
    checks = {f.check for f in report.findings if f.severity in ("warn", "error")}
    if not checks:
        return

    actions: list[tuple[str, str]] = []
    if "config.parse" in checks:
        actions.append(("修复 iterate.config.yaml 的语法错误", "编辑配置后运行 `iterate doctor`"))
    if "config.schema" in checks:
        actions.append(
            ("配置字段不符合规范", "编辑 iterate.config.yaml 中所示字段，或运行 `iterate reonboard` 重新生成")
        )
    if "validation.commands" in checks:
        actions.append(("validation.commands 结构异常", "编辑配置使每个模块对应非空命令列表"))
    if (
        "validation.command_whitelist" in checks
        or "validation.whitelist" in checks
    ):
        actions.append(
            ("命令白名单/验证命令含非法字符", "运行 `iterate personalize` 重新配置验证命令，或在配置中修正白名单")
        )
    if "skill_version" in checks:
        actions.append(("录制的技能版本过旧", "运行 `iterate refresh` 更新录制版本"))
    if "dimensions" in checks or "review.scope" in checks:
        actions.append(("维度/范围配置异常", "在 iterate.config.yaml 中修正或运行 `iterate reonboard`"))
    if "drift" in checks:
        actions.append(("技术栈漂移", "运行 `iterate refresh` 同步知识库（非阻塞）"))
    if actions:
        tui.empty_line()
        tui.info("Next action(s): ", indent=2)
        for label, command in actions:
            tui.bullet(f"{label} → {command}", indent=4)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``iterate doctor`` (standalone, for tests)."""
    import argparse

    parser = argparse.ArgumentParser(prog="iterate doctor")
    parser.add_argument("-p", "--project", default=".", help="Project root directory.")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON.")
    args = parser.parse_args(argv)

    report = run_doctor(Path(args.project).resolve())
    return render_report(report, json_output=args.json)


if __name__ == "__main__":
    sys.exit(main())