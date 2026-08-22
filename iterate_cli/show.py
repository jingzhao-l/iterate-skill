"""Read-only config and personalization inspection (``iterate show``).

``iterate show`` renders the resolved/effective project state: onboarding
metadata, the parsed iterate.config.yaml, drift status, and the full
personalization detail (structured rules plus free-form notes/conventions
read back from ITERATE.md). It never writes files.

Two render modes are supported, matching ``status`` / ``doctor``:
- TUI output (default) for humans.
- ``--json`` for scripts and CI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from iterate_cli.fingerprint import DriftResult
from iterate_cli.personalize import load_existing_personalization
from iterate_cli.refresh import (
    check_onboarding_drift,
    is_onboarding_complete,
    load_onboarding_config,
)
from iterate_cli.tui import tui


def _drift_summary(drift: DriftResult | None) -> str:
    """Return a human/JSON-safe drift description.

    ``check_onboarding_drift`` already honours the ``drift_check`` switch
    internally, so the caller only needs to invoke it once and pass the result.
    """
    if drift is None:
        return "unknown"
    if drift.has_drift:
        return drift.summary()
    return "none"


def _drift_advice(drift: DriftResult | None) -> str | None:
    """Return actionable drift advice, or None when there is none to give.

    Only meaningful when drift is actually detected (parity with ``iterate
    status``, which surfaces ``DriftResult.advice()``).
    """
    if drift is None or not drift.has_drift:
        return None
    return drift.advice()


def collect_show_data(project_root: Path) -> dict[str, Any]:
    """Gather the full resolved project state as a structured dict.

    Args:
        project_root: Project root directory.

    Returns:
        A dict with ``project``, ``onboarded``, and (when onboarded)
        ``onboarding`` metadata, ``config``, ``drift`` and ``personalization``
        details. Sensitive-looking values are NOT extracted from the config:
        only the keys iterate knows about are surfaced.
    """
    data: dict[str, Any] = {"project": str(project_root)}

    if not is_onboarding_complete(project_root):
        data["onboarded"] = False
        return data

    data["onboarded"] = True

    config = load_onboarding_config(project_root) or {}

    onboarding = config.get("onboarding") or {}
    drift_enabled = onboarding.get("drift_check", True)
    raw_fingerprints = onboarding.get("fingerprints") or []
    data["onboarding"] = {
        "completed_at": onboarding.get("completed_at", "unknown"),
        "channel": onboarding.get("channel", "unknown"),
        "skill_version": onboarding.get("skill_version", "unknown"),
        "drift_check": drift_enabled,
        "fingerprint_count": (
            len(raw_fingerprints) if isinstance(raw_fingerprints, list) else 0
        ),
    }
    # Compute the drift result exactly once and derive both summary and advice
    # from it, avoiding a redundant scan + SHA-heavy recomputation.
    drift = check_onboarding_drift(project_root)
    data["drift"] = _drift_summary(drift)
    data["drift_advice"] = _drift_advice(drift)

    # Surface the resolved config sections iterate owns. Validation commands
    # are trusted config (created by onboarding / validate.py), so showing
    # them is the point of the inspection command.
    #
    # The effective config lives in nested sections (git/review/atomic/reviewer)
    # plus a few top-level keys, NOT inside ``onboarding`` (which only holds
    # onboarding metadata). Read each value from its canonical location so
    # ``iterate show`` actually reports the effective settings.
    git = config.get("git") if isinstance(config.get("git"), dict) else {}
    review = config.get("review") if isinstance(config.get("review"), dict) else {}
    atomic = config.get("atomic") if isinstance(config.get("atomic"), dict) else {}
    reviewer = config.get("reviewer") if isinstance(config.get("reviewer"), dict) else {}
    resolved: dict[str, Any] = {}
    # Top-level keys.
    for key in ("language", "goal", "max_rounds"):
        if key in config and config[key] is not None:
            resolved[key] = config[key]
    # Nested sections.
    nested: dict[str, tuple[str, Any]] = {
        "atomic_max_lines": ("atomic", "max_lines"),
        "atomic_max_adjacent_methods": ("atomic", "max_adjacent_methods"),
        "use_worktree": ("git", "use_worktree"),
        "auto_merge": ("git", "auto_merge"),
        "target_branch": ("git", "target_branch"),
        "push_per_round": ("git", "push_per_round"),
        "review_scope": ("review", "scope"),
        "output_schema_validation": ("reviewer", "output_schema_validation"),
        "coverage_validation": ("reviewer", "coverage_validation"),
        "scope_chunk_size": ("reviewer", "scope_chunk_size"),
    }
    sections = {
        "atomic": atomic,
        "git": git,
        "review": review,
        "reviewer": reviewer,
    }
    for flat_key, (section, nested_key) in nested.items():
        section_cfg = sections[section]
        if nested_key in section_cfg and section_cfg[nested_key] is not None:
            resolved[flat_key] = section_cfg[nested_key]

    validation = config.get("validation") or {}
    if isinstance(validation, dict):
        resolved["validation"] = validation

    dimensions_conf = config.get("dimensions")
    if dimensions_conf is not None:
        resolved["dimensions"] = dimensions_conf

    data["config"] = resolved
    data["personalization"] = _collect_personalization(project_root, config)
    return data


def _collect_personalization(project_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Collect personalization detail for the show report.

    Args:
        project_root: Project root directory.
        config: Parsed iterate.config.yaml content.

    Returns:
        A dict keyed by personalization category. When there is no
        personalization at all, returns an empty dict.
    """
    result: dict[str, Any] = {}
    # load_existing_personalization merges structured config (the
    # ``personalization`` section in iterate.config.yaml) with free-form
    # notes/conventions read back from ITERATE.md, so a single call covers
    # both sources. It is safe to pass an empty connection here even when
    # ``config`` carries no personalization section.
    data = load_existing_personalization(project_root, config)
    if data.is_empty():
        return {}

    result["protected_paths"] = list(data.protected_paths)
    result["risk_areas"] = [
        {"path": r.path, "reason": r.reason} for r in data.risk_areas
    ]
    result["known_intentional"] = [
        {"file": k.file, "line": k.line, "dimension": k.dimension, "reason": k.reason}
        for k in data.known_intentional
    ]
    result["dimension_focus"] = [
        {"dimension": d.dimension, "focus": d.focus} for d in data.dimension_focus
    ]
    result["fix_priority_order"] = list(data.fix_priority_order)
    result["forbidden_fixes"] = list(data.forbidden_fixes)
    result["iterate_notes"] = list(data.iterate_notes)
    result["code_conventions"] = list(data.code_conventions)
    result["extra_validation_commands"] = {
        module: list(cmds) for module, cmds in data.extra_validation_commands.items()
    }
    return result


def render_show(data: dict[str, Any], json_output: bool = False) -> int:
    """Render the collected show data.

    Args:
        data: Structured dict from collect_show_data.
        json_output: When True, emit JSON instead of TUI text.

    Returns:
        Exit code: 0 on success (inspection is always a valid operation).
    """
    if json_output:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return 0

    tui.intro("Iterate Skill — Show")

    if not data.get("onboarded"):
        tui.warning("Status: Not onboarded")
        tui.hint("Run 'iterate onboard' to initialize.", indent=2)
        return 0

    onboarding = data["onboarding"]
    tui.key_value("Completed", onboarding["completed_at"])
    tui.key_value("Channel", onboarding["channel"])
    tui.key_value("Skill version", onboarding["skill_version"])
    tui.key_value(
        "Drift check", "enabled" if onboarding["drift_check"] else "disabled"
    )
    tui.key_value("Fingerprints", f"{onboarding['fingerprint_count']} manifest(s)")
    drift = data["drift"]
    if drift == "none":
        tui.success("Drift: none", indent=2)
    elif drift == "unknown":
        tui.key_value("Drift", "unknown")
    else:
        tui.warning(f"Drift: {drift}", indent=2)
        advice = data.get("drift_advice")
        if advice:
            tui.hint(f"Suggested: {advice}", indent=4)

    _render_config(config=data.get("config") or {})

    personalization = data.get("personalization") or {}
    if personalization:
        _render_personalization(personalization)
    else:
        tui.empty_line()
        tui.key_value("Personalization", "none set")

    return 0


def _render_config(config: dict[str, Any]) -> None:
    """Render the resolved config sections."""
    tui.empty_line()
    tui.section("Resolved Config")
    for key in (
        "language", "goal", "max_rounds", "atomic_max_lines",
        "atomic_max_adjacent_methods", "use_worktree", "auto_merge",
        "output_schema_validation", "target_branch", "review_scope",
        "push_per_round",
    ):
        if key in config:
            label = key.replace("_", " ").title()
            value = config[key]
            if isinstance(value, bool):
                value = "yes" if value else "no"
            tui.key_value(label, str(value))

    validation = config.get("validation")
    if isinstance(validation, dict):
        commands = validation.get("commands")
        whitelist = validation.get("command_whitelist")
        if isinstance(commands, dict) and commands:
            tui.key_value("Validation commands", f"{len(commands)} module(s)")
            for module, cmds in commands.items():
                if isinstance(cmds, list):
                    tui.bullet(module, indent=4)
                    for cmd in cmds:
                        tui.info(f"- {cmd}", indent=6)
        if isinstance(whitelist, list) and whitelist:
            tui.key_value("Command whitelist", ", ".join(str(w) for w in whitelist))

    dimensions = config.get("dimensions")
    if isinstance(dimensions, list) and dimensions:
        tui.key_value("Dimensions", ", ".join(str(d) for d in dimensions))


def _render_personalization(personalization: dict[str, Any]) -> None:
    """Render the full personalization detail."""
    tui.empty_line()
    tui.section("Personalization")

    protected = personalization.get("protected_paths") or []
    if protected:
        tui.key_value("Protected", f"{len(protected)} path(s)")
        for p in protected:
            tui.bullet(p, indent=4)

    risk = personalization.get("risk_areas") or []
    if risk:
        tui.key_value("Risk areas", f"{len(risk)} area(s)")
        for item in risk:
            tui.bullet(f"{item['path']} — {item['reason']}", indent=4)

    known = personalization.get("known_intentional") or []
    if known:
        tui.key_value("Known intentional", f"{len(known)} entry(ies)")
        for item in known:
            loc = f"{item['file']}:{item['line']}" if item.get("line") else item["file"]
            tui.bullet(f"{loc} [{item['dimension']}] — {item['reason']}", indent=4)

    focus = personalization.get("dimension_focus") or []
    if focus:
        tui.key_value("Dim focus", f"{len(focus)} override(s)")
        for item in focus:
            tui.bullet(f"[{item['dimension']}] {item['focus']}", indent=4)

    prio = personalization.get("fix_priority_order") or []
    if prio:
        tui.key_value("Fix priority", ", ".join(str(p) for p in prio))

    forbidden = personalization.get("forbidden_fixes") or []
    if forbidden:
        tui.key_value("Forbidden fixes", f"{len(forbidden)} approach(es)")
        for f in forbidden:
            tui.bullet(f, indent=4)

    notes = personalization.get("iterate_notes") or []
    if notes:
        tui.key_value("Iterate notes", f"{len(notes)} note(s)")
        for n in notes:
            tui.bullet(n, indent=4)

    conventions = personalization.get("code_conventions") or []
    if conventions:
        tui.key_value("Code conventions", f"{len(conventions)} convention(s)")
        for c in conventions:
            tui.bullet(c, indent=4)

    extra = personalization.get("extra_validation_commands") or {}
    if extra:
        tui.key_value("Extra validation commands", f"{len(extra)} module(s)")
        for module, cmds in extra.items():
            if isinstance(cmds, list):
                tui.bullet(module, indent=4)
                for cmd in cmds:
                    tui.info(f"- {cmd}", indent=6)


def run_show(project_root: Path, json_output: bool = False) -> int:
    """Collect and render the project state for ``iterate show``.

    Args:
        project_root: Project root directory.
        json_output: When True, emit structured JSON to stdout.

    Returns:
        Exit code: 0 on success.
    """
    data = collect_show_data(project_root)
    return render_show(data, json_output=json_output)