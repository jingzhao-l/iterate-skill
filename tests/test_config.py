"""Tests for the non-interactive ``iterate config`` subcommand.

Covers listing, reading (``get``) and validated writing (``set``) of
individual config values, including nested-section writes, backups,
invalid-value handling, corrupt-config protection, and CLI exit codes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from iterate_cli.cli import main as cli_main
from iterate_cli.configcmd import (
    SETTABLE_KEYS,
    ConfigValueError,
    _parse_bool,
    _parse_dimensions,
    _parse_int,
    _parse_non_empty_string,
    _parse_reasoning_effort,
    run_config_get,
    run_config_set,
)
from iterate_cli.doctor import SKILL_VERSION
from iterate_cli.refresh import CONFIG_YAML

ITERATE_MD = "ITERATE.md"


def _make_project(tmp_path: Path) -> Path:
    """Create a minimal onboarded project under tmp_path."""
    project = tmp_path / "proj"
    project.mkdir(parents=True)
    (project / ITERATE_MD).write_text("# Project\n", encoding="utf-8")
    return project


def _write_config(project: Path, config: dict) -> None:
    (project / CONFIG_YAML).write_text(
        yaml.safe_dump(config, allow_unicode=True), encoding="utf-8"
    )


def _read_config(project: Path) -> dict:
    return yaml.safe_load((project / CONFIG_YAML).read_text(encoding="utf-8"))


def _base_config() -> dict:
    return {
        "dimensions": ["correctness", "security"],
        "onboarding": {
            "skill_version": SKILL_VERSION,
            "channel": "cli",
            "completed_at": "2026-08-15T00:00:00Z",
            "drift_check": False,
        },
    }


# ---------------------------------------------------------------------------
# Value parsers
# ---------------------------------------------------------------------------


class TestValueParsers:
    def test_non_empty_string(self) -> None:
        assert _parse_non_empty_string("  hello  ") == "hello"
        with pytest.raises(ConfigValueError):
            _parse_non_empty_string("   ")

    def test_int_bounds(self) -> None:
        validate = _parse_int(1, 50)
        assert validate("42") == 42
        with pytest.raises(ConfigValueError):
            validate("0")
        with pytest.raises(ConfigValueError):
            validate("51")
        with pytest.raises(ConfigValueError):
            validate("abc")

    def test_int_no_max(self) -> None:
        validate = _parse_int(1, None)
        assert validate("9999") == 9999

    def test_bool(self) -> None:
        for raw in ("true", "yes", "1", "TRUE"):
            assert _parse_bool(raw) is True
        for raw in ("false", "no", "0", "NO"):
            assert _parse_bool(raw) is False
        with pytest.raises(ConfigValueError):
            _parse_bool("maybe")

    def test_reasoning_effort(self) -> None:
        assert _parse_reasoning_effort("high") == "high"
        assert _parse_reasoning_effort("  medium ") == "medium"
        assert _parse_reasoning_effort("") is None
        assert _parse_reasoning_effort("default") is None
        with pytest.raises(ConfigValueError):
            _parse_reasoning_effort("turbo")

    def test_dimensions(self) -> None:
        assert _parse_dimensions("correctness, security") == ["correctness", "security"]
        assert _parse_dimensions("correctness, correctness") == ["correctness"]
        with pytest.raises(ConfigValueError):
            _parse_dimensions("")
        with pytest.raises(ConfigValueError):
            _parse_dimensions("bogus")


# ---------------------------------------------------------------------------
# run_config_get
# ---------------------------------------------------------------------------


class TestConfigGet:
    def test_unknown_key_returns_error(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        assert run_config_get(project, "nope") == 1

    def test_missing_config_returns_error(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        assert run_config_get(project, "goal") == 1

    def test_gets_flat_value(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["reasoning_effort"] = "high"
        _write_config(project, config)
        assert run_config_get(project, "reasoning_effort") == 0

    def test_gets_nested_value(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["git"] = {"auto_merge": True}
        _write_config(project, config)
        assert run_config_get(project, "auto_merge") == 0

    def test_missing_nested_section_returns_default(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        # atomic section absent -> resolves to None ('default'), no error.
        assert run_config_get(project, "atomic_max_lines") == 0

    def test_lists_all_keys(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        assert run_config_get(project, None) == 0
        captured = capsys.readouterr()
        for name in SETTABLE_KEYS:
            assert name.replace("_", " ").title() in captured.out


# ---------------------------------------------------------------------------
# run_config_set
# ---------------------------------------------------------------------------


class TestConfigSet:
    def test_sets_flat_value(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        assert run_config_set(project, "reasoning_effort", "high") == 0
        config = _read_config(project)
        assert config["reasoning_effort"] == "high"

    def test_sets_nested_value(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        assert run_config_set(project, "auto_merge", "yes") == 0
        config = _read_config(project)
        assert config["git"]["auto_merge"] is True

    def test_creates_missing_section(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        assert run_config_set(project, "atomic_max_lines", "5") == 0
        config = _read_config(project)
        assert config["atomic"]["max_lines"] == 5

    def test_backup_is_written(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        assert run_config_set(project, "language", "en") == 0
        backups = list(project.glob(f"{CONFIG_YAML}.configset-*"))
        assert len(backups) == 1
        # Backup preserves the pre-edit value.
        backup_config = yaml.safe_load(backups[0].read_text(encoding="utf-8"))
        assert "language" not in backup_config

    def test_unknown_key_returns_error(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        assert run_config_set(project, "nope", "x") == 1

    def test_invalid_value_returns_error(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        assert run_config_set(project, "reasoning_effort", "turbo") == 1
        # Config untouched.
        config = _read_config(project)
        assert "reasoning_effort" not in config

    def test_missing_config_returns_error(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        assert run_config_set(project, "goal", "x") == 1

    def test_corrupt_config_refuses_to_write(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text(": not: valid: [yaml\n", encoding="utf-8")
        assert run_config_set(project, "goal", "x") == 1
        # Corrupt file left untouched.
        raw = (project / CONFIG_YAML).read_text(encoding="utf-8")
        assert raw == ": not: valid: [yaml\n"


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------


class TestConfigCli:
    def test_cli_get(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["language"] = "en"
        _write_config(project, config)
        code = cli_main(["config", "get", "language", "-p", str(project), "--no-banner"])
        assert code == 0
        assert "en" in capsys.readouterr().out

    def test_cli_set(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(
            ["config", "set", "max_rounds", "12", "-p", str(project), "--no-banner"]
        )
        assert code == 0
        config = _read_config(project)
        assert config["max_rounds"] == 12

    def test_cli_set_missing_value(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(["config", "set", "goal", "-p", str(project), "--no-banner"])
        assert code == 1
        assert "Usage" in capsys.readouterr().err

    def test_cli_set_invalid_value(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(
            ["config", "set", "max_rounds", "999", "-p", str(project), "--no-banner"]
        )
        assert code == 1
