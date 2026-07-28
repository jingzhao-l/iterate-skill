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
    fingerprints_from_dict,
    fingerprints_to_dict,
)
from iterate_cli.generator import (
    OnboardingData,
    extract_user_owned_section,
    generate_config_yaml,
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
from iterate_cli.wizard import run_wizard

# Files managed by onboarding.
ITERATE_MD = "ITERATE.md"
CONFIG_YAML = "iterate.config.yaml"


def load_onboarding_config(project_root: Path) -> dict[str, Any] | None:
    """Load the project-level iterate.config.yaml if it exists.

    Args:
        project_root: The project root directory.

    Returns:
        Parsed config dict, or None if the file does not exist or cannot
        be parsed (errors are logged to stderr).
    """
    config_path = project_root / CONFIG_YAML
    if not config_path.is_file():
        return None
    try:
        return yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"⚠️  Failed to parse {config_path}: {exc}", file=sys.stderr)
        return None


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

    return check_drift(project_root, stored)


def incremental_refresh(project_root: Path) -> bool:
    """Perform an incremental refresh of ITERATE.md.

    Re-scans the project and regenerates the AI-maintained sections of
    ITERATE.md while preserving user-owned sections. Also updates the
    fingerprints in iterate.config.yaml.

    Args:
        project_root: The project root directory.

    Returns:
        True if refresh succeeded, False if ITERATE.md does not exist.
    """
    iterate_md_path = project_root / ITERATE_MD
    if not iterate_md_path.is_file():
        return False

    existing_md = iterate_md_path.read_text(encoding="utf-8")
    scan = scan_project(project_root)

    # Load existing config to preserve user-confirmed settings.
    existing_config = load_onboarding_config(project_root) or {}

    # Build refreshed data from existing config + fresh scan.
    data = _build_refresh_data(project_root, scan, existing_config, existing_md)

    # Generate refreshed ITERATE.md preserving user sections.
    refreshed_md = generate_refreshed_md(data, existing_md)
    iterate_md_path.write_text(refreshed_md, encoding="utf-8")

    # Update config with new fingerprints but keep other settings.
    _update_config_fingerprints(project_root, existing_config, data.fingerprints)

    return True


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
        True if re-onboarding completed, False if cancelled or no existing files.
    """
    iterate_md_path = project_root / ITERATE_MD
    config_path = project_root / CONFIG_YAML

    if not iterate_md_path.is_file() and not config_path.is_file():
        return False

    # Backup existing files.
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if iterate_md_path.is_file():
        shutil.copy2(iterate_md_path, project_root / f"{ITERATE_MD}.bak-{timestamp}")
    if config_path.is_file():
        shutil.copy2(config_path, project_root / f"{CONFIG_YAML}.bak-{timestamp}")

    # Run the full wizard.
    if input_func is not None:
        data = run_wizard(project_root, input_func=input_func)
    else:
        data = run_wizard(project_root)

    if data is None:
        return False

    write_onboarding_outputs(data, project_root)
    return True


def _build_refresh_data(
    project_root: Path,
    scan: ScanResult,
    existing_config: dict[str, Any],
    existing_md: str,
) -> OnboardingData:
    """Build OnboardingData for a refresh, preserving existing settings."""
    # Extract user-owned content to pass as conventions.
    user_content = extract_user_owned_section(existing_md)

    # Preserve existing dimensions, target_branch, etc.
    dimensions = existing_config.get("dimensions") or suggest_dimensions(scan)
    target_branch = (existing_config.get("git") or {}).get("target_branch", "main")
    review_scope = (existing_config.get("review") or {}).get("scope", "full")
    push_per_round = (existing_config.get("git") or {}).get("push_per_round", True)
    validation_commands = (existing_config.get("validation") or {}).get("commands") or {}
    command_whitelist = (existing_config.get("validation") or {}).get("command_whitelist") or []
    language = existing_config.get("language", "en")

    # Preserve existing personalization so refresh does not lose it.
    personalization = None
    if existing_config.get("personalization"):
        from iterate_cli.personalize import load_personalization_from_config

        personalization = load_personalization_from_config(existing_config)

    # Capture fresh fingerprints.
    fingerprints = capture_fingerprints(project_root)

    # Preserve channel from existing config or default to "cli".
    onboarding_section = existing_config.get("onboarding") or {}
    channel = onboarding_section.get("channel", "cli")

    return OnboardingData(
        project_root=project_root,
        channel=channel,
        scan=scan,
        dimensions=dimensions,
        target_branch=target_branch,
        review_scope=review_scope,
        push_per_round=push_per_round,
        validation_commands=validation_commands,
        command_whitelist=command_whitelist if command_whitelist else suggest_command_whitelist(scan),
        fingerprints=fingerprints,
        iterate_notes=user_content,
        language=language,
        personalization=personalization,
    )


def _update_config_fingerprints(
    project_root: Path,
    existing_config: dict[str, Any],
    new_fingerprints: list,
) -> None:
    """Update the fingerprints in iterate.config.yaml without changing other fields.

    Args:
        project_root: The project root directory.
        existing_config: The existing parsed config dict.
        new_fingerprints: Fresh FingerprintEntry list.
    """
    config = dict(existing_config)
    onboarding = dict(config.get("onboarding") or {})
    onboarding["fingerprints"] = fingerprints_to_dict(new_fingerprints)
    onboarding["completed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    config["onboarding"] = onboarding

    config_path = project_root / CONFIG_YAML
    config_path.write_text(
        yaml.safe_dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
