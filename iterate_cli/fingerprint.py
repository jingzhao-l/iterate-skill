"""Manifest fingerprinting for onboarding drift detection.

Records SHA-256 hashes of key manifest files (package.json, pyproject.toml, etc.)
so that subsequent ``/iterate`` invocations can detect whether the project's
tech stack has changed since the last onboarding.
"""

from __future__ import annotations

import fnmatch
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Manifest files tracked for drift detection.
# Only files that actually exist in the project root are fingerprinted.
MANIFEST_FILES: tuple[str, ...] = (
    "package.json",
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "Package.swift",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Gemfile",
    "composer.json",
    "mix.exs",
    "pubspec.yaml",
    "tsconfig.json",
)

# Current fingerprint schema version; bump when the format changes.
FINGERPRINT_VERSION = "1.0"


@dataclass
class FingerprintEntry:
    """A single manifest file fingerprint."""

    path: str
    sha256: str

    def to_dict(self) -> dict[str, str]:
        """Serialize to a plain dict for YAML storage."""
        return {"path": self.path, "sha256": self.sha256}


@dataclass
class DriftResult:
    """Result of comparing stored fingerprints against the current state."""

    unchanged: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        """True if any manifest was added, removed, or changed."""
        return bool(self.changed or self.added or self.removed)

    def summary(self) -> str:
        """Human-readable one-line drift summary."""
        if not self.has_drift:
            return "No drift detected."
        parts: list[str] = []
        if self.changed:
            parts.append(f"changed: {', '.join(sorted(self.changed))}")
        if self.added:
            parts.append(f"added: {', '.join(sorted(self.added))}")
        if self.removed:
            parts.append(f"removed: {', '.join(sorted(self.removed))}")
        return "; ".join(parts)

    def advice(self) -> str:
        """Return a concise, honest recommendation for the user.

        Drift is **non-blocking**: the iteration can always continue. The
        advice only tells the user *when a refresh is most worthwhile*:

        - added/removed manifests: the tech stack itself changed, so
          refreshing ITERATE.md is more likely to matter.
        - only changed manifests: dependencies/configuration were updated;
          continuing is fine unless the change is significant.
        """
        if not self.has_drift:
            return "No drift detected; no action needed."
        if self.added or self.removed:
            return (
                "技术栈发生增减，建议运行 `iterate refresh` 同步知识库（非阻塞）。"
                "Tech stack manifests added/removed; consider `iterate refresh` (non-blocking)."
            )
        return (
            "依赖/配置已更新；如无重大变化可继续迭代（非阻塞），需要时再 `iterate refresh`。"
            "Dependencies/config updated; safe to continue (non-blocking), refresh when needed."
        )


def _matches_ignore(name: str, ignore_patterns: list[str] | None) -> bool:
    """Return True if ``name`` matches any fnmatch ignore pattern.

    Args:
        name: The manifest file name (basename) to test.
        ignore_patterns: Optional glob patterns to ignore. Empty/None matches nothing.

    Returns:
        True if the name should be excluded from fingerprinting.
    """
    if not ignore_patterns:
        return False
    return any(fnmatch.fnmatch(name, pat) for pat in ignore_patterns)


def compute_sha256(path: Path) -> str:
    """Compute the SHA-256 hash of a file's content.

    Args:
        path: Path to the file to hash.

    Returns:
        Hexadecimal SHA-256 digest string.

    Raises:
        FileNotFoundError: If the file does not exist.
        OSError: If the file cannot be read.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan_manifests(project_root: Path, ignore_patterns: list[str] | None = None) -> list[Path]:
    """Detect manifest files that exist in the project root.

    Only checks the project root directory (not subdirectories), because
    manifest files at the root are the authoritative tech-stack indicators.

    Args:
        project_root: The project root directory to scan.
        ignore_patterns: Optional fnmatch patterns of manifest names to skip
            (e.g. ``package-lock.json``). Empty/None ignores nothing.

    Returns:
        List of paths to existing manifest files, sorted by name.
    """
    found: list[Path] = []
    for name in MANIFEST_FILES:
        if _matches_ignore(name, ignore_patterns):
            continue
        candidate = project_root / name
        if candidate.is_file():
            found.append(candidate)
    found.sort(key=lambda p: p.name)
    return found


def capture_fingerprints(
    project_root: Path, ignore_patterns: list[str] | None = None
) -> list[FingerprintEntry]:
    """Capture fingerprints for all existing manifest files.

    Args:
        project_root: The project root directory to scan.
        ignore_patterns: Optional fnmatch patterns of manifest names to skip.

    Returns:
        List of FingerprintEntry objects, one per manifest file found.
    """
    entries: list[FingerprintEntry] = []
    for manifest in scan_manifests(project_root, ignore_patterns):
        entries.append(
            FingerprintEntry(
                path=manifest.name,
                sha256=compute_sha256(manifest),
            )
        )
    return entries


def fingerprints_to_dict(entries: list[FingerprintEntry]) -> list[dict[str, str]]:
    """Convert a list of FingerprintEntry to serializable dicts."""
    return [e.to_dict() for e in entries]


def fingerprints_from_dict(data: list[dict[str, Any]]) -> list[FingerprintEntry]:
    """Reconstruct FingerprintEntry list from loaded YAML/JSON data.

    Args:
        data: List of dicts with ``path`` and ``sha256`` keys.

    Returns:
        List of FingerprintEntry objects.

    Raises:
        ValueError: If any entry is missing required keys.
        TypeError: If any entry is not a dict.
    """
    entries: list[FingerprintEntry] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise TypeError(f"Fingerprint entry {i} is not a dict")
        path = item.get("path")
        sha = item.get("sha256")
        if not isinstance(path, str) or not path:
            raise ValueError(f"Fingerprint entry {i} missing 'path'")
        if not isinstance(sha, str) or not sha:
            raise ValueError(f"Fingerprint entry {i} missing 'sha256'")
        entries.append(FingerprintEntry(path=path, sha256=sha))
    return entries


def compare_fingerprints(
    stored: list[dict[str, str]],
    current: list[dict[str, str]],
) -> DriftResult:
    """Compare stored fingerprints against the current state.

    Args:
        stored: Fingerprints loaded from ``iterate.config.yaml``.
        current: Fingerprints freshly captured from the project root.

    Returns:
        DriftResult describing what changed.
    """
    stored_map = {e["path"]: e["sha256"] for e in stored}
    current_map = {e["path"]: e["sha256"] for e in current}

    result = DriftResult()
    for path, sha in current_map.items():
        if path not in stored_map:
            result.added.append(path)
        elif stored_map[path] != sha:
            result.changed.append(path)
        else:
            result.unchanged.append(path)
    for path in stored_map:
        if path not in current_map:
            result.removed.append(path)
    return result


def check_drift(
    project_root: Path,
    stored_fingerprints: list[dict[str, str]],
    ignore_patterns: list[str] | None = None,
) -> DriftResult:
    """Convenience: capture current fingerprints and compare against stored.

    Ignored manifests are excluded from **both** sides of the comparison: the
    freshly captured set (via ``capture_fingerprints``) and the stored set.
    This prevents a previously-fingerprinted manifest that is now ignored
    (e.g. a lock file the user no longer wants tracked) from reporting a
    spurious ``removed`` drift before the next refresh.

    Args:
        project_root: The project root directory.
        stored_fingerprints: Fingerprints from the existing config.
        ignore_patterns: Optional fnmatch patterns of manifest names to skip.

    Returns:
        DriftResult describing what changed since last onboarding.
    """
    current = fingerprints_to_dict(
        capture_fingerprints(project_root, ignore_patterns)
    )
    if ignore_patterns:
        stored_fingerprints = [
            entry
            for entry in stored_fingerprints
            if not _matches_ignore(str(entry.get("path", "")), ignore_patterns)
        ]
    return compare_fingerprints(stored_fingerprints, current)
