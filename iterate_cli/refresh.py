"""Onboarding refresh logic.

Handles two refresh modes:
- Incremental refresh: re-scan manifests, regenerate AI-maintained sections
  of ITERATE.md while preserving user-owned sections.
- Full re-onboarding: backup old files and run the full onboarding flow again.
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from iterate_cli.fingerprint import (
    DriftResult,
    capture_fingerprints,
    check_drift,
    fingerprints_to_dict,
)
from iterate_cli.generator import (
    OnboardingData,
    atomic_write,
    generate_refreshed_md,
    write_onboarding_outputs,
)
from iterate_cli.scan import (
    ScanResult,
    scan_project,
    suggest_command_whitelist,
    suggest_dimensions,
    suggest_validation_commands,
)
from iterate_cli.wizard import NO_CHANGES_NEEDED, run_wizard

# Files managed by onboarding.
ITERATE_MD = "ITERATE.md"
CONFIG_YAML = "iterate.config.yaml"

# Outcomes of full_reonboard (returned as strings so callers can render
# accurate user-facing messages instead of conflating every success path).
REONBOARD_COMPLETED = "completed"
REONBOARD_NO_CHANGES = "no-changes"
REONBOARD_CANCELLED = "cancelled"
REONBOARD_FAILED = "failed"


def load_onboarding_config(project_root: Path) -> dict[str, Any] | None:
    """Load the project-level iterate.config.yaml if it exists.

    Args:
        project_root: The project root directory.

    Returns:
        Parsed config dict, or None if the file does not exist, cannot
        be parsed, or is not a YAML mapping (errors are logged to stderr).
        Returning None for non-mapping content prevents AttributeError
        crashes in callers that call ``.get()`` on the result.
    """
    config_path = project_root / CONFIG_YAML
    if not config_path.is_file():
        return None
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"⚠️  Failed to parse {config_path}: {exc}", file=sys.stderr)
        return None
    except (OSError, UnicodeDecodeError) as exc:
        # OSError: permission denied, file removed between is_file() and
        #   read_text(), filesystem errors, etc.
        # UnicodeDecodeError: file contains non-UTF-8 bytes (inherits
        #   ValueError, not OSError, so listed explicitly).
        # Either way: log and return None so callers fall back to defaults.
        print(f"⚠️  Failed to read {config_path}: {exc}", file=sys.stderr)
        return None

    # yaml.safe_load returns None for an empty file (handled by ``or {}``
    # in callers) but a list/scalar for malformed content like ``- item``
    # or ``just a string``. Such non-dict results would crash callers
    # that call ``.get()``, so reject them here.
    if config is not None and not isinstance(config, dict):
        print(
            f"⚠️  {config_path} is not a YAML mapping (got {type(config).__name__})",
            file=sys.stderr,
        )
        return None
    return config


def _load_refresh_config(project_root: Path) -> dict[str, Any] | None:
    """Load the project config for a refresh, distinguishing "absent" from "corrupt".

    A refresh regenerates the AI-maintained sections of ITERATE.md and updates
    ``onboarding.fingerprints`` inside ``iterate.config.yaml``. It must preserve
    every other user-customised field (dimensions, validation, personalization,
    …). If the config file exists but cannot be parsed (corrupt YAML, non-mapping,
    unreadable), refresh must **refuse to run** rather than silently rewriting the
    file with empty defaults — which would destroy the user's configuration.

    Returns:
        The parsed config dict, or ``{}`` when ``iterate.config.yaml`` does not
        exist (a legitimate first-refresh case). Returns ``None`` only when the
        file exists but cannot be parsed or read, signalling that refresh should
        abort.
    """
    config_path = project_root / CONFIG_YAML
    if not config_path.is_file():
        return {}
    config = load_onboarding_config(project_root)
    if config is None:
        # File exists, but load_onboarding_config logged the specific reason
        # (YAMLError / OSError / non-mapping) and returned None.
        return None
    return config


def get_stored_fingerprints(config: dict[str, Any]) -> list[dict[str, str]]:
    """Extract stored fingerprints from a loaded config dict.

    Args:
        config: Parsed iterate.config.yaml content.

    Returns:
        List of fingerprint dicts, or empty list if not present.
    """
    onboarding = config.get("onboarding") or {}
    raw = onboarding.get("fingerprints") or []
    if not isinstance(raw, list):
        return []
    result: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict) and "path" in item and "sha256" in item:
            result.append({"path": str(item["path"]), "sha256": str(item["sha256"])})
    return result


def get_drift_ignore(config: dict[str, Any]) -> list[str]:
    """Extract drift-ignore glob patterns from the onboarding section.

    Patterns are matched against manifest basenames via fnmatch. Non-string
    or non-list values are discarded so malformed manual edits degrade to
    "ignore nothing" instead of crashing drift detection.

    Args:
        config: Parsed iterate.config.yaml content.

    Returns:
        List of fnmatch patterns, or empty list if not present.
    """
    onboarding = config.get("onboarding") or {}
    raw = onboarding.get("drift_ignore") or []
    if not isinstance(raw, list):
        return []
    return [str(p) for p in raw if isinstance(p, str)]


def is_onboarding_complete(project_root: Path) -> bool:
    """Check whether onboarding has been completed for this project.

    Onboarding is considered complete if ITERATE.md exists in the project root.

    Args:
        project_root: The project root directory.

    Returns:
        True if ITERATE.md exists.
    """
    return (project_root / ITERATE_MD).is_file()


def check_onboarding_drift(project_root: Path) -> DriftResult | None:
    """Check for drift since the last onboarding.

    Args:
        project_root: The project root directory.

    Returns:
        DriftResult if onboarding was completed and drift check is enabled,
        None if onboarding was never completed or drift check is disabled.
    """
    config = load_onboarding_config(project_root)
    if config is None:
        return None

    onboarding = config.get("onboarding") or {}
    if not onboarding.get("drift_check", True):
        return None

    stored = get_stored_fingerprints(config)
    if not stored:
        return None

    return check_drift(project_root, stored, get_drift_ignore(config))


def incremental_refresh(project_root: Path) -> bool:
    """Perform an incremental refresh of ITERATE.md.

    Re-scans the project, regenerates the AI-maintained sections of
    ITERATE.md while preserving user-owned sections, and updates the
    fingerprints in iterate.config.yaml. Both files are written atomically;
    on failure the previous state is restored where possible.

    Args:
        project_root: The project root directory.

    Returns:
        True if refresh succeeded, False if ITERATE.md does not exist,
        cannot be read, or a write failure occurred.
    """
    ok, refreshed_md, config_yaml, error = _build_refresh_outputs(project_root)
    if not ok:
        print(f"⚠️  {error}", file=sys.stderr)
        return False
    return _write_refresh_outputs(project_root, refreshed_md, config_yaml)


def preview_refresh(project_root: Path) -> dict[str, Any]:
    """Compute a dry-run preview of what ``incremental_refresh`` would change.

    No files are written. Intended for ``iterate refresh --dry-run`` so a
    user can review the impact before committing to a refresh.

    Args:
        project_root: The project root directory.

    Returns:
        A dict:
        - ``ok``: bool — whether a preview could be computed.
        - ``error``: str — human-readable reason when ``ok`` is False.
        - ``changed``: bool — whether ITERATE.md or config would change.
        - ``config_changed``: bool — whether iterate.config.yaml would change.
        - ``md_changed_lines``: int — total added+removed lines in ITERATE.md.
        - ``stats``: dict with added/removed/changed line counts.
    """
    empty = {
        "ok": False,
        "error": "",
        "changed": False,
        "config_changed": False,
        "md_changed_lines": 0,
        "stats": {},
    }
    ok, refreshed_md, config_yaml, error = _build_refresh_outputs(project_root)
    if not ok:
        empty["error"] = error
        return empty

    try:
        current_md = (project_root / ITERATE_MD).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        empty["error"] = f"Failed to read {ITERATE_MD}: {exc}"
        return empty

    current_config = ""
    try:
        current_config = (project_root / CONFIG_YAML).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # The config was already parsed by _build_refresh_outputs, so reaching
        # this point with an unreadable file is a genuine read failure. Treating
        # it as an empty string would falsely flag config_changed and misguide
        # the preview (which claims to refuse to overwrite an unparseable
        # config).
        empty["error"] = f"Failed to read {CONFIG_YAML}: {exc}"
        return empty

    md_changed = refreshed_md != current_md
    config_changed = config_yaml != current_config
    stats = _diff_stats(current_md, refreshed_md)
    return {
        "ok": True,
        "error": "",
        "changed": md_changed or config_changed,
        "config_changed": config_changed,
        "md_changed_lines": stats["changed"],
        "stats": stats,
    }


def _build_refresh_outputs(project_root: Path) -> tuple[bool, str, str, str]:
    """Build the refreshed ITERATE.md and config YAML without writing.

    Args:
        project_root: The project root directory.

    Returns:
        ``(ok, refreshed_md, config_yaml, error)``. When ``ok`` is False,
        the two content strings are empty and ``error`` explains why.
    """
    iterate_md_path = project_root / ITERATE_MD
    if not iterate_md_path.is_file():
        return False, "", "", f"{ITERATE_MD} does not exist."
    try:
        existing_md = iterate_md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return False, "", "", f"Failed to read {iterate_md_path}: {exc}"

    scan = scan_project(project_root)
    existing_config = _load_refresh_config(project_root)
    if existing_config is None:
        return False, "", "", f"{CONFIG_YAML} exists but could not be parsed; refusing to overwrite with defaults."
    data = _build_refresh_data(project_root, scan, existing_config)
    try:
        refreshed_md = generate_refreshed_md(data, existing_md)
    except ValueError as exc:
        # Refusing to overwrite an ITERATE.md without the USER-OWNED markers
        # (it may be hand-edited); surface the reason instead of destroying it.
        return False, "", "", str(exc)
    new_config = _build_refreshed_config(existing_config, data.fingerprints)
    config_yaml = yaml.safe_dump(
        new_config,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    return True, refreshed_md, config_yaml, ""


def _write_refresh_outputs(project_root: Path, refreshed_md: str, config_yaml: str) -> bool:
    """Atomically write refreshed ITERATE.md and config, rolling back on failure.

    Both files are written with ``_atomic_write`` (temp file + ``os.replace``).
    If either write fails, the other is rolled back to its pre-refresh state.
    If rollback itself fails, files may be inconsistent (logged to stderr).

    Args:
        project_root: The project root directory.
        refreshed_md: New ITERATE.md content.
        config_yaml: New iterate.config.yaml YAML content.

    Returns:
        True on success, False if a write or rollback failed.
    """
    iterate_md_path = project_root / ITERATE_MD
    config_path = project_root / CONFIG_YAML

    backup_md: str | None = None
    backup_config: str | None = None
    try:
        try:
            backup_md = iterate_md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            backup_md = None
        try:
            backup_config = config_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            backup_config = None

        atomic_write(iterate_md_path, refreshed_md)
        atomic_write(config_path, config_yaml)
    except OSError as exc:
        print(f"⚠️  Failed to write refresh outputs: {exc}", file=sys.stderr)
        if backup_md is not None:
            try:
                atomic_write(iterate_md_path, backup_md)
            except OSError as rollback_exc:
                print(
                    f"⚠️  Rollback failed for {iterate_md_path}: {rollback_exc}",
                    file=sys.stderr,
                )
        if backup_config is not None:
            try:
                atomic_write(config_path, backup_config)
            except OSError as rollback_exc:
                print(
                    f"⚠️  Rollback failed for {config_path}: {rollback_exc}",
                    file=sys.stderr,
                )
        return False
    return True


def _diff_stats(before: str, after: str) -> dict[str, int]:
    """Count added/removed lines between two text blobs.

    Args:
        before: Original text.
        after: New text.

    Returns:
        A dict with ``added``, ``removed`` and ``changed`` (added + removed)
        line counts.
    """
    import difflib

    added = 0
    removed = 0
    for line in difflib.unified_diff(
        before.splitlines(), after.splitlines(), lineterm=""
    ):
        # Skip the "--- old"/"+++ new" file header rows; only actual diff
        # lines count toward the changed-line total.
        if line.startswith(("--- ", "+++ ")):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return {"added": added, "removed": removed, "changed": added + removed}


def _build_refreshed_config(
    existing_config: dict[str, Any],
    new_fingerprints: list,
) -> dict[str, Any]:
    """Build a refreshed config dict with updated fingerprints.

    Does not write to disk; the caller is responsible for writing
    (typically as part of an atomic refresh).

    Args:
        existing_config: The existing parsed config dict.
        new_fingerprints: Fresh FingerprintEntry list.

    Returns:
        New config dict with fingerprints and completed_at updated.
    """
    config = dict(existing_config)
    onboarding = dict(config.get("onboarding") or {})
    new_fp = fingerprints_to_dict(new_fingerprints)
    # Idempotent refresh: only restamp ``completed_at`` when the manifest
    # fingerprints actually changed. This keeps ``iterate refresh`` a no-op
    # when nothing drifted, so ``--dry-run`` reports "no changes needed"
    # instead of always showing a diff due to a fresh timestamp.
    if onboarding.get("fingerprints") != new_fp:
        onboarding["completed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    onboarding["fingerprints"] = new_fp
    config["onboarding"] = onboarding
    return config


def full_reonboard(
    project_root: Path,
    input_func=None,
) -> str:
    """Perform a full re-onboarding, backing up old files first.

    Backs up existing ITERATE.md and iterate.config.yaml, then runs the
    full onboarding wizard. If input_func is None, uses the default input().

    Args:
        project_root: The project root directory.
        input_func: Optional input callable for testing.

    Returns:
        One of the REONBOARD_* status strings:
        - ``REONBOARD_COMPLETED`` — wizard produced data and outputs were written.
        - ``REONBOARD_NO_CHANGES`` — returning user declined all updates;
          nothing was written (old files remain intact).
        - ``REONBOARD_CANCELLED`` — wizard was cancelled before any write.
        - ``REONBOARD_FAILED`` — no existing files, or backup/write failed
          (errors are logged to stderr).
    """
    iterate_md_path = project_root / ITERATE_MD
    config_path = project_root / CONFIG_YAML

    if not iterate_md_path.is_file() and not config_path.is_file():
        return REONBOARD_FAILED

    # Backup existing files.
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        if iterate_md_path.is_file():
            shutil.copy2(
                iterate_md_path, project_root / f"{ITERATE_MD}.bak-{timestamp}"
            )
        if config_path.is_file():
            shutil.copy2(
                config_path, project_root / f"{CONFIG_YAML}.bak-{timestamp}"
            )
    except OSError as exc:
        print(f"⚠️  Backup failed, aborting re-onboarding: {exc}", file=sys.stderr)
        return REONBOARD_FAILED

    # Run the full wizard.
    if input_func is not None:
        data = run_wizard(project_root, input_func=input_func)
    else:
        data = run_wizard(project_root)

    if data is None:
        return REONBOARD_CANCELLED
    if data is NO_CHANGES_NEEDED:
        # Returning user declined all updates; nothing to write. The old
        # files remain intact and the .bak-<timestamp> copies are harmless.
        return REONBOARD_NO_CHANGES

    try:
        # Preserve the user-owned ITERATE.md section (manual edits +
        # personalization content) across a full re-onboard, keeping behaviour
        # consistent with ``onboard`` on an existing project. The .bak copy
        # already saved above remains as a safety net.
        existing_md: str | None = None
        if iterate_md_path.is_file():
            try:
                existing_md = iterate_md_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                print(
                    f"⚠️  Failed to read {iterate_md_path} for user-owner preservation: {exc}",
                    file=sys.stderr,
                )
                existing_md = None
        write_onboarding_outputs(data, project_root, existing_md)
    except OSError as exc:
        print(f"⚠️  Failed to write onboarding outputs: {exc}", file=sys.stderr)
        return REONBOARD_FAILED

    return REONBOARD_COMPLETED


def _reconcile_validation_suggestions(
    validation_commands: dict[str, list[str]],
    effective_whitelist: list[str],
    scan: ScanResult,
    reconcile_whitelist: bool = True,
) -> tuple[dict[str, list[str]], list[str]]:
    """Additively reconcile validation tooling with a newly-detected stack.

    When a language has been added to the project since the last onboarding,
    its suggested validation commands and command-whitelist prefixes are
    appended so the refreshed config actually validates it. Existing
    (possibly customised) configuration is preserved and never removed —
    only missing entries for newly-detected languages are added.

    Args:
        validation_commands: Existing ``validation.commands`` mapping.
        effective_whitelist: The currently effective command whitelist.
        scan: Fresh ScanResult used to derive per-language suggestions.
        reconcile_whitelist: Whether to augment the whitelist. Disable when
            the operator has deliberately configured an empty whitelist
            ("run no commands") so their intent is preserved.

    Returns:
        Updated (validation_commands, effective_whitelist).
    """
    suggested_commands = suggest_validation_commands(scan)
    commands = dict(validation_commands)
    for module, cmds in suggested_commands.items():
        if module not in commands:
            commands[module] = list(cmds)

    if not reconcile_whitelist:
        return commands, effective_whitelist

    suggested_prefixes = suggest_command_whitelist(scan)
    seen = set(effective_whitelist)
    whitelist = list(effective_whitelist)
    for prefix in suggested_prefixes:
        if prefix not in seen:
            seen.add(prefix)
            whitelist.append(prefix)
    return commands, whitelist


def _build_refresh_data(
    project_root: Path,
    scan: ScanResult,
    existing_config: dict[str, Any],
) -> OnboardingData:
    """Build OnboardingData for a refresh, preserving existing settings."""
    # Preserve existing dimensions, target_branch, etc.
    dimensions = existing_config.get("dimensions") or suggest_dimensions(scan)
    target_branch = (existing_config.get("git") or {}).get("target_branch", "main")
    review_scope = (existing_config.get("review") or {}).get("scope", "full")
    # Secure-by-default: push_per_round must default to False, matching
    # OnboardingData (generator.py) and the documented default.
    push_per_round = (existing_config.get("git") or {}).get("push_per_round", False)
    validation_existing = existing_config.get("validation") or {}
    validation_commands = validation_existing.get("commands") or {}
    # Distinguish an explicit empty whitelist (the operator deliberately
    # configured "run no commands") from an absent key (fall back to a scan
    # suggestion so a fresh config still gets a usable whitelist).
    has_whitelist_key = isinstance(validation_existing, dict) and "command_whitelist" in validation_existing
    command_whitelist = validation_existing.get("command_whitelist")
    if command_whitelist is None:
        command_whitelist = [] if has_whitelist_key else None
    # Resolve the effective whitelist (existing, or scan suggestion when the
    # key is absent) and additively reconcile validation tooling with the
    # newly-detected tech stack: a language added since the last onboarding
    # gets its suggested commands + whitelist prefixes appended, while
    # existing (possibly customised) configuration is never removed.
    effective_whitelist = (
        command_whitelist
        if command_whitelist is not None
        else suggest_command_whitelist(scan)
    )
    # An operator who deliberately configured an empty whitelist ("run no
    # commands") should not get tool prefixes re-added on refresh; every other
    # case is augmented additively so newly-detected languages are validated.
    reconcile_whitelist = not (has_whitelist_key and command_whitelist == [])
    validation_commands, effective_whitelist = _reconcile_validation_suggestions(
        validation_commands, effective_whitelist, scan, reconcile_whitelist
    )
    language = existing_config.get("language", "en")

    # Preserve existing personalization so refresh does not lose it.
    personalization = None
    if existing_config.get("personalization"):
        from iterate_cli.personalize import load_personalization_from_config

        personalization = load_personalization_from_config(existing_config)

    # Capture fresh fingerprints, honouring drift-ignore patterns.
    ignore_patterns = get_drift_ignore(existing_config)
    fingerprints = capture_fingerprints(project_root, ignore_patterns)

    # Preserve channel and user-entered text from existing config.
    onboarding_section = existing_config.get("onboarding") or {}
    channel = onboarding_section.get("channel", "cli")
    project_description = str(onboarding_section.get("project_description") or "")
    code_conventions = str(onboarding_section.get("code_conventions") or "")

    return OnboardingData(
        project_root=project_root,
        channel=channel,
        scan=scan,
        project_description=project_description,
        code_conventions=code_conventions,
        dimensions=dimensions,
        target_branch=target_branch,
        review_scope=review_scope,
        push_per_round=push_per_round,
        validation_commands=validation_commands,
        command_whitelist=effective_whitelist,
        fingerprints=fingerprints,
        language=language,
        drift_ignore=get_drift_ignore(existing_config),
        personalization=personalization,
    )
