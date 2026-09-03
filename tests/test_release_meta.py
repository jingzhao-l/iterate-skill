"""Tests that keep the four release version sources in sync.

The iterate-skill version is duplicated across four files that ship to
different platforms (PyPI-style metadata, the CLI, the skill manifest, and the
npm installer). A post-patch bump (e.g. 3.0.0 -> 3.0.1) that touches only one
of them lets ``iterate doctor``/``refresh`` skill_version drift from the
installer's ``--version``. These tests fail the build when the sources diverge.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    """Read ``[project].version`` from pyproject.toml (3.11+ stdlib, else tomli)."""
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
        import tomli as tomllib  # type: ignore[no-redef]
    with open(REPO_ROOT / "pyproject.toml", "rb") as handle:
        data = tomllib.load(handle)
    return data["project"]["version"]


def _cli_version() -> str:
    """Read ``__version__`` from iterate_cli/__init__.py."""
    source = (REPO_ROOT / "iterate_cli" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', source)
    assert match, "iterate_cli/__init__.py missing __version__ literal"
    return match.group(1)


def _skill_version() -> str:
    """Read the ``version`` field from SKILL.md frontmatter."""
    text = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---"), "SKILL.md must start with a YAML frontmatter block"
    _, frontmatter, _rest = text.split("---", 2)
    data = yaml.safe_load(frontmatter)
    return str(data["version"])


def _npm_version() -> str:
    """Read the ``version`` field from npm-installer/package.json."""
    data = json.loads((REPO_ROOT / "npm-installer" / "package.json").read_text(encoding="utf-8"))
    return str(data["version"])


def test_four_version_sources_agree() -> None:
    """pyproject.toml / CLI / SKILL.md / npm installer must all say the same version."""
    versions = {
        "pyproject.toml": _pyproject_version(),
        "iterate_cli/__init__.py": _cli_version(),
        "SKILL.md frontmatter": _skill_version(),
        "npm-installer/package.json": _npm_version(),
    }
    unique = set(versions.values())
    assert len(unique) == 1, f"version sources drifted: {versions}"


def test_version_is_three_part_semver() -> None:
    """The shared version must be a valid X.Y.Z semantic version."""
    version = _pyproject_version()
    pattern = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
    assert pattern.match(version), f"version {version!r} is not X.Y.Z semver"