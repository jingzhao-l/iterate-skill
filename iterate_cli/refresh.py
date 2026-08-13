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
    generate_refreshed_md,
    write_onboarding_outputs,
)
from iterate_cli.scan import (
    ScanResult,
    scan_project,
    suggest_command_whitelist,
    suggest_dimensions,
)
from iterate_cli.wizard import run_wizard

# Files managed by onboarding.
ITERATE_MD = "ITERATE.md"
CONFIG_YAML = "iterate.config.yaml"


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

    Re-scans the project and regenerates the AI-maintained sections of
    ITERATE.md while preserving user-owned sections. Also updates the
    fingerprints in iterate.config.yaml.

    Best-effort rollback is attempted on write failure: if either file
    write fails, the other is rolled back to its pre-refresh state.
    If rollback itself fails, files may be in an inconsistent state
    (the rollback failure is logged to stderr).

    Args:
        project_root: The project root directory.

    Returns:
        True if refresh succeeded, False if ITERATE.md does not exist,
        cannot be read, or a write failure occurred.
    """
    iterate_md_path = project_root / ITERATE_MD
    if not iterate_md_path.is_file():
        return False

    # Read existing ITERATE.md defensively (file may have been removed
    # between is_file() and read_text(), or contain non-UTF-8 bytes).
    try:
        existing_md = iterate_md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"⚠️  Failed to read {iterate_md_path}: {exc}", file=sys.stderr)
        return False

    scan = scan_project(project_root)

    # Load existing config to preserve user-confirmed settings.
    existing_config = load_onboarding_config(project_root) or {}

    # Build refreshed data from existing config + fresh scan.
    data = _build_refresh_data(project_root, scan, existing_config)

    # Generate refreshed ITERATE.md preserving user sections.
    refreshed_md = generate_refreshed_md(data, existing_md)

    # Prepare new config content (do not write yet).
    new_config = _build_refreshed_config(existing_config, data.fingerprints)

    # Atomic commit: write both files, rollback on failure.
    config_path = project_root / CONFIG_YAML
    # existing_md is the pre-refresh ITERATE.md content (already read
    # above) — reuse it as the rollback target.
    backup_md = existing_md
    backup_config: str | None = None

    try:
        # Back up current config content so we can rollback on failure.
        try:
            backup_config = config_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            backup_config = None  # File may not exist yet.

        iterate_md_path.write_text(refreshed_md, encoding="utf-8")
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
        # Rollback both files to their pre-refresh state.
        print(f"⚠️  Failed to write refresh outputs: {exc}", file=sys.stderr)
        if backup_md is not None:
            try:
                iterate_md_path.write_text(backup_md, encoding="utf-8")
            except OSError as rollback_exc:
                print(
                    f"⚠️  Rollback failed for {iterate_md_path}: {rollback_exc}",
                    file=sys.stderr,
                )
        if backup_config is not None:
            try:
                config_path.write_text(backup_config, encoding="utf-8")
            except OSError as rollback_exc:
                print(
                    f"⚠️  Rollback failed for {config_path}: {rollback_exc}",
                    file=sys.stderr,
                )
        return False

    return True


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
    onboarding["fingerprints"] = fingerprints_to_dict(new_fingerprints)
    onboarding["completed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    config["onboarding"] = onboarding
    return config


def full_reonboard(
    project_root: Path,
    input_func=None,
) -> bool:
    """Perform a full re-onboarding, backing up old files first.

    Backs up existing ITERATE.md and iterate.config.yaml, then runs the
    full onboarding wizard. If input_func is None, uses the default input().

    Args:
        project_root: The project root directory.
        input_func: Optional input callable for testing.

    Returns:
        True if re-onboarding completed, False if cancelled, no existing
        files, or backup/write failed (errors are logged to stderr).
    """
    iterate_md_path = project_root / ITERATE_MD
    config_path = project_root / CONFIG_YAML

    if not iterate_md_path.is_file() and not config_path.is_file():
        return False

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
        return False

    # Run the full wizard.
    if input_func is not None:
        data = run_wizard(project_root, input_func=input_func)
    else:
        data = run_wizard(project_root)

    if data is None:
        return False

    try:
        write_onboarding_outputs(data, project_root)
    except OSError as exc:
        print(f"⚠️  Failed to write onboarding outputs: {exc}", file=sys.stderr)
        return False

    return True


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
    validation_commands = (existing_config.get("validation") or {}).get("commands") or {}
    command_whitelist = (existing_config.get("validation") or {}).get("command_whitelist") or []
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
        command_whitelist=command_whitelist if command_whitelist else suggest_command_whitelist(scan),
        fingerprints=fingerprints,
        language=language,
        personalization=personalization,
    )
