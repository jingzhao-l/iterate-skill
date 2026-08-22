"""Tests for the drift-ignore feature and drift advice in status output.

Covers:
- scan_manifests / capture_fingerprints honouring ignore patterns.
- check_drift ignoring matching manifests end-to-end.
- incremental_refresh excluding ignored manifests from refreshed fingerprints.
- ``iterate status`` surfacing drift advice and the new summary fields.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

# Make iterate_cli importable.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from iterate_cli.cli import main as cli_main
from iterate_cli import __version__ as SKILL_VERSION
from iterate_cli.fingerprint import (
    capture_fingerprints,
    check_drift,
    fingerprints_to_dict,
    scan_manifests,
)
from iterate_cli.generator import OnboardingData, write_onboarding_outputs
from iterate_cli.refresh import (
    check_onboarding_drift,
    get_drift_ignore,
    incremental_refresh,
)
from iterate_cli.scan import (
    scan_project,
    suggest_command_whitelist,
    suggest_dimensions,
    suggest_validation_commands,
)


@pytest.fixture
def js_project(tmp_path: Path) -> Path:
    """A project with package.json + tsconfig.json (both are tracked manifests)."""
    project = tmp_path / "jsproj"
    project.mkdir()
    (project / "package.json").write_text('{"name": "jsproj"}', encoding="utf-8")
    (project / "tsconfig.json").write_text('{"compilerOptions": {}}', encoding="utf-8")
    return project


@pytest.fixture
def py_project(tmp_path: Path) -> Path:
    """A minimal Python project with a single manifest."""
    project = tmp_path / "pyproj"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "pyproj"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    return project


def _build_onboarding_data(project_root: Path) -> OnboardingData:
    """Build minimal OnboardingData (mirrors test_onboarding.py helper)."""
    scan = scan_project(project_root)
    return OnboardingData(
        project_root=project_root,
        channel="cli",
        scan=scan,
        project_description="Test project",
        code_conventions="4-space indent",
        dimensions=suggest_dimensions(scan),
        target_branch="main",
        review_scope="full",
        push_per_round=False,
        validation_commands=suggest_validation_commands(scan),
        command_whitelist=suggest_command_whitelist(scan),
        fingerprints=capture_fingerprints(project_root),
    )


def _write_config_with_drift(
    project_root: Path,
    drift_ignore: list[str] | None = None,
    drift_check: bool = True,
) -> dict[str, Any]:
    """Write an iterate.config.yaml with an onboarding section and drift settings."""
    onboarding: dict[str, Any] = {
        "version": "1.0",
        "drift_check": drift_check,
        "fingerprints": fingerprints_to_dict(capture_fingerprints(project_root)),
    }
    if drift_ignore is not None:
        onboarding["drift_ignore"] = drift_ignore
    config = {
        "goal": "Improve quality",
        "dimensions": ["correctness"],
        "onboarding": onboarding,
    }
    (project_root / "iterate.config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )
    return config


# ---------------------------------------------------------------------------
# scan / capture ignore patterns
# ---------------------------------------------------------------------------

class TestScanIgnore:
    def test_no_ignore_captures_all(self, js_project: Path) -> None:
        names = {p.name for p in scan_manifests(js_project)}
        assert names == {"package.json", "tsconfig.json"}

    def test_exact_name_ignored(self, js_project: Path) -> None:
        names = {p.name for p in scan_manifests(js_project, ["package.json"])}
        assert names == {"tsconfig.json"}

    def test_glob_pattern_ignored(self, js_project: Path) -> None:
        names = {p.name for p in scan_manifests(js_project, ["package*"])}
        assert names == {"tsconfig.json"}

    def test_empty_ignore_list_ignores_nothing(self, js_project: Path) -> None:
        names = {p.name for p in scan_manifests(js_project, [])}
        assert names == {"package.json", "tsconfig.json"}

    def test_none_ignore_list_ignores_nothing(self, js_project: Path) -> None:
        names = {p.name for p in scan_manifests(js_project, None)}
        assert names == {"package.json", "tsconfig.json"}

    def test_capture_fingerprints_excludes_ignored(self, js_project: Path) -> None:
        entries = capture_fingerprints(js_project, ["package.json"])
        paths = {e.path for e in entries}
        assert paths == {"tsconfig.json"}


# ---------------------------------------------------------------------------
# check_drift with ignore patterns
# ---------------------------------------------------------------------------

class TestCheckDriftIgnore:
    def test_ignored_change_is_not_drift(self, js_project: Path) -> None:
        stored = fingerprints_to_dict(capture_fingerprints(js_project))
        (js_project / "package.json").write_text('{"name": "changed"}', encoding="utf-8")
        result = check_drift(js_project, stored, ["package.json"])
        assert not result.has_drift

    def test_ignored_add_is_not_drift(self, js_project: Path) -> None:
        stored = fingerprints_to_dict(capture_fingerprints(js_project))
        (js_project / "package.json").unlink()
        result = check_drift(js_project, stored, ["package.json"])
        assert not result.has_drift

    def test_non_ignored_change_is_drift(self, js_project: Path) -> None:
        stored = fingerprints_to_dict(capture_fingerprints(js_project))
        (js_project / "tsconfig.json").write_text('{"compilerOptions": {"x": 1}}', encoding="utf-8")
        result = check_drift(js_project, stored, ["package.json"])
        assert result.has_drift
        assert "tsconfig.json" in result.changed


# ---------------------------------------------------------------------------
# check_onboarding_drift reads drift_ignore from config
# ---------------------------------------------------------------------------

class TestOnboardingDriftIgnore:
    def test_drift_ignore_from_config(self, js_project: Path) -> None:
        _write_config_with_drift(js_project, drift_ignore=["package.json"])
        (js_project / "package.json").write_text('{"name": "changed"}', encoding="utf-8")
        result = check_onboarding_drift(js_project)
        assert result is not None
        assert not result.has_drift

    def test_no_ignore_so_change_is_drift(self, js_project: Path) -> None:
        _write_config_with_drift(js_project)
        (js_project / "package.json").write_text('{"name": "changed"}', encoding="utf-8")
        result = check_onboarding_drift(js_project)
        assert result is not None
        assert result.has_drift

    def test_get_drift_ignore_robustness(self, tmp_path: Path) -> None:
        assert get_drift_ignore({}) == []
        assert get_drift_ignore({"onboarding": None}) == []
        assert get_drift_ignore({"onboarding": {"drift_ignore": "not-a-list"}}) == []
        assert get_drift_ignore({"onboarding": {"drift_ignore": ["a", 42, None]}}) == ["a"]


# ---------------------------------------------------------------------------
# incremental_refresh excludes ignored manifests from new fingerprints
# ---------------------------------------------------------------------------

class TestRefreshIgnore:
    def test_refresh_drops_ignored_manifest_from_fingerprints(self, js_project: Path) -> None:
        _write_config_with_drift(js_project, drift_ignore=["package.json"])
        (js_project / "ITERATE.md").write_text(
            "# ITERATE.md\n\n"
            "<!-- ITERATE:USER-OWNED:START -->\nuser\n<!-- ITERATE:USER-OWNED:END -->\n",
            encoding="utf-8",
        )
        assert incremental_refresh(js_project) is True
        config = yaml.safe_load((js_project / "iterate.config.yaml").read_text(encoding="utf-8"))
        stored = config["onboarding"]["fingerprints"]
        paths = {fp["path"] for fp in stored}
        assert paths == {"tsconfig.json"}

    def test_refresh_syncs_stale_skill_version(self, js_project: Path) -> None:
        # Reflects the "Run `iterate refresh` to update the recorded skill
        # version." advice from `iterate doctor`: a refresh must bring a stale
        # onboarding.skill_version into sync, not persist the stale record.
        setup = _write_config_with_drift(js_project)
        setup["onboarding"]["skill_version"] = "9.9.9"
        (js_project / "iterate.config.yaml").write_text(
            yaml.safe_dump(setup, sort_keys=False),
            encoding="utf-8",
        )
        (js_project / "ITERATE.md").write_text(
            "# ITERATE.md\n\n"
            "<!-- ITERATE:USER-OWNED:START -->\nuser\n<!-- ITERATE:USER-OWNED:END -->\n",
            encoding="utf-8",
        )
        assert incremental_refresh(js_project) is True
        config = yaml.safe_load((js_project / "iterate.config.yaml").read_text(encoding="utf-8"))
        assert config["onboarding"]["skill_version"] == SKILL_VERSION

    def test_refresh_preserves_in_sync_skill_version(self, js_project: Path) -> None:
        # Idempotency: when fingerprints and skill_version already match, a
        # refresh must stay a no-op and not restamp completed_at.
        setup = _write_config_with_drift(js_project)
        setup["onboarding"]["skill_version"] = SKILL_VERSION
        setup["onboarding"]["completed_at"] = "2020-01-01T00:00:00Z"
        (js_project / "iterate.config.yaml").write_text(
            yaml.safe_dump(setup, sort_keys=False),
            encoding="utf-8",
        )
        (js_project / "ITERATE.md").write_text(
            "# ITERATE.md\n\n"
            "<!-- ITERATE:USER-OWNED:START -->\nuser\n<!-- ITERATE:USER-OWNED:END -->\n",
            encoding="utf-8",
        )
        assert incremental_refresh(js_project) is True
        config = yaml.safe_load((js_project / "iterate.config.yaml").read_text(encoding="utf-8"))
        assert config["onboarding"]["completed_at"] == "2020-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# status output: advice + summary fields
# ---------------------------------------------------------------------------

class TestStatusAdvice:
    def test_status_shows_advice_on_drift(self, py_project: Path, capsys) -> None:
        write_onboarding_outputs(_build_onboarding_data(py_project), py_project)
        (py_project / "pyproject.toml").write_text(
            '[project]\nname = "pyproj"\nversion = "0.2.0"\n',
            encoding="utf-8",
        )
        assert cli_main(["status", "-p", str(py_project)]) == 0
        captured = capsys.readouterr()
        # advice() is surfaced: a changed-only drift recommends refresh.
        assert "refresh" in captured.out
        assert "Drift" in captured.out

    def test_status_shows_summary_fields(self, py_project: Path, capsys) -> None:
        write_onboarding_outputs(_build_onboarding_data(py_project), py_project)
        assert cli_main(["status", "-p", str(py_project)]) == 0
        captured = capsys.readouterr()
        assert "Skill version" in captured.out
        assert "Fingerprints" in captured.out
        assert "Drift check" in captured.out
        assert "No drift" in captured.out
