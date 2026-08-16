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
    apply_safe_fixes,
    render_report,
    run_doctor,
    run_doctor_fix,
)
from iterate_cli.refresh import load_onboarding_config

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
            "skill_version": "2.3.14",
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
        assert data["skill_version"] == "2.3.14"
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

    def test_empty_dimensions_is_error(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["dimensions"] = []
        _write_config(project, config)
        report = run_doctor(project)
        assert report.has_errors()
        assert any(f.check == "dimensions" and f.severity == "error" for f in report.findings)

    def test_duplicate_dimensions_is_warning(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["dimensions"] = ["correctness", "correctness"]
        _write_config(project, config)
        report = run_doctor(project)
        assert not report.has_errors()
        assert any(f.check == "dimensions" and f.severity == "warn" for f in report.findings)

    def test_max_rounds_out_of_bounds_is_error(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["max_rounds"] = 51
        _write_config(project, config)
        report = run_doctor(project)
        assert report.has_errors()
        assert any(f.check == "max_rounds" and f.severity == "error" for f in report.findings)

    def test_max_rounds_valid_ok(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["max_rounds"] = 3
        _write_config(project, config)
        report = run_doctor(project)
        assert not report.has_errors()
        assert any(f.check == "max_rounds" and f.severity == "ok" for f in report.findings)

    def test_invalid_language_is_warning(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["language"] = "fr"
        _write_config(project, config)
        report = run_doctor(project)
        assert not report.has_errors()
        assert any(f.check == "language" and f.severity == "warn" for f in report.findings)

    def test_invalid_command_whitelist_is_warning(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["validation"] = {"command_whitelist": ["pytest", "pytest"]}
        _write_config(project, config)
        report = run_doctor(project)
        assert not report.has_errors()
        assert any(f.check == "validation.command_whitelist" and f.severity == "warn" for f in report.findings)

    def test_valid_command_whitelist_ok(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["validation"] = {"command_whitelist": ["pytest"]}
        _write_config(project, config)
        report = run_doctor(project)
        assert not report.has_errors()
        assert any(f.check == "validation.command_whitelist" and f.severity == "ok" for f in report.findings)


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
        assert data["skill_version"] == "2.3.14"
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


# ---------------------------------------------------------------------------
# apply_safe_fixes — non-destructive config repair
# ---------------------------------------------------------------------------


class TestApplySafeFixes:
    def test_clean_config_is_unchanged(self) -> None:
        config = _base_config()
        new_config, fixes = apply_safe_fixes(config)
        assert fixes == []
        assert new_config == config

    def test_duplicate_dimensions_deduped(self) -> None:
        config = _base_config()
        config["dimensions"] = ["correctness", "correctness", "security"]
        new_config, fixes = apply_safe_fixes(config)
        assert new_config["dimensions"] == ["correctness", "security"]
        assert any("duplicate" in f for f in fixes)

    def test_empty_dimensions_restored(self) -> None:
        config = _base_config()
        config["dimensions"] = []
        new_config, fixes = apply_safe_fixes(config)
        assert new_config["dimensions"] == list(CANONICAL_DIMENSIONS)
        assert any("defaults" in f for f in fixes)

    def test_invalid_language_reset(self) -> None:
        config = _base_config()
        config["language"] = "fr"
        new_config, fixes = apply_safe_fixes(config)
        assert new_config["language"] == "en"
        assert any("language" in f for f in fixes)

    def test_max_rounds_clamped(self) -> None:
        config = _base_config()
        config["max_rounds"] = 999
        new_config, fixes = apply_safe_fixes(config)
        assert new_config["max_rounds"] == 50
        assert any("clamped" in f for f in fixes)

    def test_max_rounds_non_integer_removed(self) -> None:
        config = _base_config()
        config["max_rounds"] = "lots"
        new_config, fixes = apply_safe_fixes(config)
        assert "max_rounds" not in new_config
        assert any("non-integer" in f for f in fixes)

    def test_empty_target_branch_reset(self) -> None:
        config = _base_config()
        config["git"] = {"target_branch": "   "}
        new_config, fixes = apply_safe_fixes(config)
        assert new_config["git"]["target_branch"] == "main"
        assert any("target_branch" in f for f in fixes)

    def test_skill_version_synced(self) -> None:
        config = _base_config()
        config["onboarding"]["skill_version"] = "9.9.9"
        new_config, fixes = apply_safe_fixes(config)
        assert new_config["onboarding"]["skill_version"] == "2.3.14"
        assert any("skill_version" in f for f in fixes)


# ---------------------------------------------------------------------------
# run_doctor_fix — writes fixed config with a backup
# ---------------------------------------------------------------------------


class TestRunDoctorFix:
    def test_repairs_and_writes_backup(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["dimensions"] = ["correctness", "correctness"]
        _write_config(project, config)

        ok, fixes = run_doctor_fix(project)
        assert ok
        assert fixes

        # Backup file created.
        backups = list(project.glob(f"{CONFIG_YAML}.doctorfix-*"))
        assert len(backups) == 1

        # Config now deduplicated.
        fixed = load_onboarding_config(project)
        assert fixed["dimensions"] == ["correctness"]

        # Re-running doctor reports no dimensions warning.
        report = run_doctor(project)
        assert not any(f.check == "dimensions" and f.severity == "warn" for f in report.findings)

    def test_noop_when_clean(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        ok, fixes = run_doctor_fix(project)
        assert ok
        assert fixes == []
        assert list(project.glob(f"{CONFIG_YAML}.doctorfix-*")) == []

    def test_missing_config_returns_false(self, tmp_path) -> None:
        # _make_project creates ITERATE.md but not iterate.config.yaml.
        project = _make_project(tmp_path)
        ok, fixes = run_doctor_fix(project)
        assert not ok
        assert fixes == []

    def test_cli_fix_flag_applies(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["language"] = "fr"
        _write_config(project, config)
        code = cli_main(["doctor", "-p", str(project), "--fix"])
        assert code == 0


# ---------------------------------------------------------------------------
# config.schema — full JSON Schema validation (config.schema check)
# ---------------------------------------------------------------------------


class TestDoctorConfigSchema:
    def test_valid_config_matches_schema(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        report = run_doctor(project)
        assert any(
            f.check == "config.schema" and f.severity == "ok" for f in report.findings
        )

    def test_unknown_key_is_schema_violation(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        # additionalProperties:false → any unknown top-level key is a violation.
        config["bogus_top_level_key"] = "not in schema"
        _write_config(project, config)
        report = run_doctor(project)
        assert any(
            f.check == "config.schema" and f.severity == "warn" for f in report.findings
        )

    def test_wrong_type_is_schema_violation(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        # dimensions must be an array of strings.
        config["dimensions"] = "not-a-list"
        _write_config(project, config)
        report = run_doctor(project)
        assert any(
            f.check == "config.schema" and f.severity == "warn" for f in report.findings
        )


# ---------------------------------------------------------------------------
# validation.whitelist — command whitelist compliance
# ---------------------------------------------------------------------------


class TestDoctorWhitelistCompliance:
    def _config_with_commands(self, commands, whitelist) -> dict:
        config = _base_config()
        config["validation"] = {
            "commands": {"python": commands},
            "command_whitelist": whitelist,
        }
        return config

    def test_all_commands_whitelisted_ok(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, self._config_with_commands(["pytest tests/ -q"], ["pytest"]))
        report = run_doctor(project)
        assert any(
            f.check == "validation.whitelist" and f.severity == "ok"
            for f in report.findings
        )

    def test_non_whitelisted_command_warns(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(
            project,
            self._config_with_commands(["pytest tests/ -q", "custom-tool run"], ["pytest"]),
        )
        report = run_doctor(project)
        assert any(
            f.check == "validation.whitelist" and f.severity == "warn"
            for f in report.findings
        )

    def test_unsafe_whitelist_entry_warns(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        # Semicolon is a shell metacharacter and must be rejected.
        _write_config(
            project,
            self._config_with_commands(["pytest tests/ -q"], ["pytest; rm -rf"]),
        )
        report = run_doctor(project)
        assert any(
            f.check == "validation.whitelist" and f.severity == "warn"
            for f in report.findings
        )


# ---------------------------------------------------------------------------
# personalization.consistency — dimension references must be enabled
# ---------------------------------------------------------------------------


class TestDoctorPersonalizationConsistency:
    def test_consistent_references_ok(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["personalization"] = {
            "version": "1.0",
            "fix_priority_order": ["correctness", "security"],
        }
        _write_config(project, config)
        report = run_doctor(project)
        assert any(
            f.check == "personalization.consistency" and f.severity == "ok"
            for f in report.findings
        )

    def test_disabled_dimension_reference_warns(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        # dimensions only enable correctness + security; performance is disabled.
        config["personalization"] = {
            "version": "1.0",
            "fix_priority_order": ["correctness", "performance"],
        }
        _write_config(project, config)
        report = run_doctor(project)
        assert any(
            f.check == "personalization.consistency" and f.severity == "warn"
            for f in report.findings
        )