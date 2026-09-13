"""Tests for the non-interactive ``iterate config`` subcommand.

Covers listing, reading (``get``) and validated writing (``set``) of
individual config values, including nested-section writes, backups,
invalid-value handling, corrupt-config protection, and CLI exit codes.
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

    def test_scalar_intermediate_section_errors(self, tmp_path) -> None:
        """A hand-edited scalar intermediate (e.g. ``git: legacy``) must be
        reported, not silently shown as 'default' (B2)."""
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text("git: legacy\n", encoding="utf-8")
        assert run_config_get(project, "git.use_worktree") == 1
        assert run_config_get(project, "use_worktree") == 1

    def test_scalar_intermediate_section_errors_all_keys(self, tmp_path) -> None:
        """The all-keys summary must refuse when any intermediate is malformed."""
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text("git: legacy\n", encoding="utf-8")
        assert run_config_get(project, None) == 1

    def test_scalar_intermediate_section_json_error(self, tmp_path, capsys) -> None:
        """JSON mode reports a structured error and exit 1 for a malformed
        intermediate section."""
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text("git: legacy\n", encoding="utf-8")
        assert run_config_get(project, "auto_merge", json_output=True) == 1
        captured = capsys.readouterr()
        payload = json.loads(captured.out.strip())
        assert "error" in payload


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


class TestConfigDottedAliases:
    """``iterate config set``/``get`` dotted-path aliases (B5)."""

    def _css(self):
        return {
            "dimensions": ["correctness", "security"],
            "onboarding": {
                "skill_version": SKILL_VERSION,
                "channel": "cli",
                "completed_at": "2026-08-15T00:00:00Z",
                "drift_check": False,
            },
        }

    def test_set_dotted_alias_writes_nested(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, self._css())
        assert run_config_set(project, "git.use_worktree", "true") == 0
        config = _read_config(project)
        assert config["git"]["use_worktree"] is True

    def test_set_dotted_alias_reviewer(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, self._css())
        assert run_config_set(project, "reviewer.coverage_validation", "false") == 0
        config = _read_config(project)
        assert config["reviewer"]["coverage_validation"] is False

    def test_get_dotted_alias_reads_value(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        config = self._css()
        config["git"] = {"use_worktree": True}
        _write_config(project, config)
        assert run_config_get(project, "git.use_worktree") == 0
        assert capsys.readouterr().out.strip() == "yes"


class TestConfigNonMappingProtection:
    """A top-level YAML that is not a mapping must never be clobbered."""

    def test_refuses_to_overwrite_list_config(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text("- just\n- a\n- list\n", encoding="utf-8")
        assert run_config_set(project, "goal", "x") == 1
        raw = (project / CONFIG_YAML).read_text(encoding="utf-8")
        assert raw == "- just\n- a\n- list\n"

    def test_refuses_to_overwrite_scalar_config(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text("just-a-string\n", encoding="utf-8")
        assert run_config_set(project, "goal", "x") == 1
        assert (project / CONFIG_YAML).read_text(encoding="utf-8") == "just-a-string\n"

    def test_refuses_to_clobber_intermediate_scalar(self, tmp_path) -> None:
        """A dotted set whose intermediate path segment is a hand-edited
        scalar (e.g. `git: legacy`) must refuse instead of replacing it with a
        mapping (which would silently destroy the scalar value)."""
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text(
            "git: legacy\nreview: full\n", encoding="utf-8"
        )
        assert run_config_set(project, "git.use_worktree", "true") == 1
        raw = (project / CONFIG_YAML).read_text(encoding="utf-8")
        assert "legacy" in raw
        assert "use_worktree" not in raw

    def test_serialisation_error_returns_error(self, tmp_path, monkeypatch) -> None:
        """A yaml.YAMLError raised while dumping (e.g. RepresenterError for an
        unserialisable hand-edited value) must be reported cleanly with exit 1
        instead of an uncaught traceback (B1)."""
        import iterate_cli.configcmd as configcmd_mod

        project = _make_project(tmp_path)
        _write_config(project, _base_config())

        def boom(*args, **kwargs):
            raise yaml.representer.RepresenterError("cannot represent")

        monkeypatch.setattr(configcmd_mod.yaml, "safe_dump", boom)
        assert run_config_set(project, "language", "en") == 1

    def test_backup_names_never_collide(self, tmp_path) -> None:
        """Two config edits within the same second must not overwrite each
        other's backup: the backup name carries a per-write salt."""
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        assert run_config_set(project, "language", "zh") == 0
        assert run_config_set(project, "language", "en") == 0
        backups = sorted(project.glob(f"{CONFIG_YAML}.configset-*"))
        assert len(backups) == 2
        first = yaml.safe_load(backups[0].read_text(encoding="utf-8"))
        second = yaml.safe_load(backups[1].read_text(encoding="utf-8"))
        # first backup captured the original base config; the second captured
        # the config after the first edit (language was set)
        assert first.get("language") != second.get("language") or first != second



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

    def test_cli_set_dotted_alias(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(
            ["config", "set", "git.use_worktree", "true", "-p", str(project), "--no-banner"]
        )
        assert code == 0
        assert _read_config(project)["git"]["use_worktree"] is True

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


class TestConfigJson:
    """``iterate config --json`` emits a clean, parseable JSON object."""

    def test_interactive_json_gate_reachable_inline(self, tmp_path, capsys) -> None:
        """`iterate onboard --json` must hit the friendly interactive-rejection
        gate (exit 2) instead of an argparse 'unrecognized arguments' error."""
        for cmd in ("onboard", "personalize", "reonboard"):
            capsys.readouterr()
            code = cli_main([cmd, "--json", "-p", str(tmp_path)])
            assert code == 2
            assert "--json is not supported" in capsys.readouterr().err

    def test_interactive_json_gate_reachable_global(self, tmp_path, capsys) -> None:
        """`iterate --json onboard` also hits the friendly gate."""
        code = cli_main(["--json", "onboard", "-p", str(tmp_path)])
        assert code == 2
        assert "--json is not supported" in capsys.readouterr().err

    def test_get_single_key_json(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["language"] = "en"
        config["max_rounds"] = 7
        _write_config(project, config)
        code = cli_main(
            ["config", "get", "max_rounds", "--json", "-p", str(project), "--no-banner"]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == {"max_rounds": 7}

    def test_get_all_keys_json(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(
            ["config", "--json", "-p", str(project), "--no-banner"]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload, dict)
        assert "max_rounds" in payload
        assert set(payload) <= set(SETTABLE_KEYS)

    def test_set_json_confirms_and_stdout_is_clean(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(
            ["config", "set", "max_rounds", "12", "--json", "-p", str(project), "--no-banner"]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == {"key": "max_rounds", "value": 12}
        assert _read_config(project)["max_rounds"] == 12

    def test_unknown_key_json_returns_error(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(
            ["config", "get", "nope", "--json", "-p", str(project), "--no-banner"]
        )
        assert code == 1

    def test_run_config_get_all_json(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        assert run_config_get(project, None, json_output=True) == 0
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload, dict) and "dimensions" in payload
