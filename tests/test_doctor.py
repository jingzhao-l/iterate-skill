"""Tests for iterate_cli.doctor (project health diagnostics).

Covers the doctor checks across normal, warning, and error paths, plus
the ``--json`` structured output and CLI exit codes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from iterate_cli.cli import main as cli_main
from iterate_cli.doctor import (
    CANONICAL_DIMENSIONS,
    DoctorReport,
    render_report,
    run_doctor,
)

ITERATE_MD = "ITERATE.md"
CONFIG_YAML = "iterate.config.yaml"


def _make_project(tmp_path: Path, *, complete: bool = True) -> Path:
    """Create a minimal onboarded project under tmp_path."""
    project = tmp_path / "proj"
    project.mkdir(parents=True)
    if complete:
        (project / ITERATE_MD).write_text("# Project\n", encoding="utf-8")
    return project


def _write_config(project: Path, config: dict) -> None:
    (project / CONFIG_YAML).write_text(
        yaml.safe_dump(config, allow_unicode=True), encoding="utf-8"
    )


def _base_config() -> dict:
    return {
        "dimensions": ["correctness", "security"],
        "onboarding": {
            "skill_version": "2.3.10",
            "channel": "cli",
            "completed_at": "2026-08-15T00:00:00Z",
            "drift_check": False,
        },
    }


# ---------------------------------------------------------------------------
# run_doctor — normal / error paths
# ---------------------------------------------------------------------------


class TestDoctorReport:
    def test_has_errors_and_warnings(self) -> None:
        report = DoctorReport("x")
        report.findings.clear()
        assert not report.has_errors()
        assert not report.has_warnings()

    def test_to_dict_shape(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        report = run_doctor(project)
        data = report.to_dict()
        assert data["project"] == str(project)
        assert data["skill_version"] == "2.3.10"
        assert isinstance(data["healthy"], bool)
        assert isinstance(data["findings"], list)


class TestDoctorOnboarding:
    def test_missing_onboarding_is_error(self, tmp_path) -> None:
        project = _make_project(tmp_path, complete=False)
        report = run_doctor(project)
        assert report.has_errors()
        assert any(f.check == "onboarding" and f.severity == "error" for f in report.findings)

    def test_complete_onboarding_passes(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        report = run_doctor(project)
        assert not report.has_errors()
        assert any(f.check == "onboarding" and f.severity == "ok" for f in report.findings)


class TestDoctorConfig:
    def test_invalid_config_is_error(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text(
            "dimensions: [unclosed bracket", encoding="utf-8"
        )
        report = run_doctor(project)
        assert report.has_errors()
        assert any(f.check == "config.parse" and f.severity == "error" for f in report.findings)

    def test_unknown_dimension_is_warning(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["dimensions"] = ["correctness", "not_a_real_dim"]
        _write_config(project, config)
        report = run_doctor(project)
        assert not report.has_errors()
        assert any(f.check == "dimensions" and f.severity == "warn" for f in report.findings)

    def test_invalid_scope_is_warning(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["review"] = {"scope": "everything"}
        _write_config(project, config)
        report = run_doctor(project)
        assert any(f.check == "review.scope" and f.severity == "warn" for f in report.findings)

    def test_invalid_target_branch_is_error(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["git"] = {"target_branch": "   "}
        _write_config(project, config)
        report = run_doctor(project)
        assert report.has_errors()
        assert any(f.check == "git.target_branch" and f.severity == "error" for f in report.findings)

    def test_invalid_validation_commands_is_error(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["validation"] = {"commands": {"python": []}}
        _write_config(project, config)
        report = run_doctor(project)
        assert report.has_errors()
        assert any(f.check == "validation.commands" and f.severity == "error" for f in report.findings)

    def test_valid_validation_commands_ok(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["validation"] = {"commands": {"python": ["pytest tests/ -q"]}}
        _write_config(project, config)
        report = run_doctor(project)
        assert not report.has_errors()
        assert any(f.check == "validation.commands" and f.severity == "ok" for f in report.findings)


class TestDoctorSkillVersion:
    def test_version_mismatch_is_warning(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["onboarding"]["skill_version"] = "9.9.9"
        _write_config(project, config)
        report = run_doctor(project)
        assert not report.has_errors()
        assert any(f.check == "skill_version" and f.severity == "warn" for f in report.findings)


# ---------------------------------------------------------------------------
# render_report — json output and exit codes
# ---------------------------------------------------------------------------


class TestRenderReport:
    def test_json_output_is_valid_json(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        report = run_doctor(project)
        code = render_report(report, json_output=True)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["skill_version"] == "2.3.10"
        assert code == 0

    def test_error_report_returns_nonzero(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path, complete=False)
        report = run_doctor(project)
        code = render_report(report, json_output=True)
        assert code == 1
        data = json.loads(capsys.readouterr().out)
        assert data["healthy"] is False


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestDoctorCLI:
    def test_doctor_cli_json(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(["doctor", "-p", str(project), "--json"])
        assert code == 0

    def test_doctor_cli_error_exit(self, tmp_path) -> None:
        project = _make_project(tmp_path, complete=False)
        code = cli_main(["doctor", "-p", str(project)])
        assert code == 1

    def test_status_cli_json(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(["status", "-p", str(project), "--json"])
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert data["onboarded"] is True

    def test_global_json_flag_before_subcommand(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(["--json", "status", "-p", str(project)])
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert data["onboarded"] is True