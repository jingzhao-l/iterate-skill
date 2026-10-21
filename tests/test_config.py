"""Tests for the non-interactive ``iterate config`` subcommand.

Covers listing, reading (``get``) and validated writing (``set``) of
individual config values, including nested-section writes, backups,
invalid-value handling, corrupt-config protection, and CLI exit codes.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import ClassVar

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
    run_config_unset,
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

    def test_missing_config_message_points_at_init(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        capsys.readouterr()

        assert run_config_get(project, "goal") == 1

        err = capsys.readouterr().err
        assert "missing" in err
        assert "iterate init --yes" in err
        assert "onboard" in err

    def test_corrupt_config_message_points_at_doctor(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text("goal: [unclosed\n", encoding="utf-8")
        capsys.readouterr()

        assert run_config_get(project, "goal") == 1

        err = capsys.readouterr().err
        assert "could not be parsed" in err
        assert "iterate doctor" in err
        # Onboarding refuses to overwrite a corrupt config; that advice was a
        # dead end.
        assert "onboard" not in err

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
        assert code == 2, "a missing VALUE is a usage error, not a failed operation"
        assert "Usage" in capsys.readouterr().err

    def test_cli_set_invalid_value(self, tmp_path) -> None:
        """A value that runs and is rejected stays exit 1 (operation failed).

        Paired with the missing-VALUE test above, which is exit 2: usage
        errors and operational failures must be distinguishable by code.
        """
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(
            ["config", "set", "max_rounds", "999", "-p", str(project), "--no-banner"]
        )
        assert code == 1


class TestConfigCliImplicitGet:
    """`iterate config KEY` is documented as `iterate config get KEY`.

    A `choices=["get","set","unset"]` on the action positional used to make
    argparse reject the key as an "invalid choice" before dispatch, so the
    documented implicit form was unreachable.
    """

    def test_implicit_get_flat_key(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["language"] = "en"
        _write_config(project, config)
        code = cli_main(["config", "language", "-p", str(project), "--no-banner"])
        assert code == 0
        assert capsys.readouterr().out.strip() == "en"

    def test_implicit_get_json(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["language"] = "en"
        _write_config(project, config)
        code = cli_main(
            ["config", "language", "--json", "-p", str(project), "--no-banner"]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == {"language": "en"}

    def test_implicit_get_unknown_key_is_operation_error(self, tmp_path, capsys) -> None:
        """An unknown KEY is an operational failure (exit 1), not a usage error."""
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(["config", "nope", "-p", str(project), "--no-banner"])
        assert code == 1
        assert "Unknown config key" in capsys.readouterr().err

    def test_typoed_action_is_named(self, tmp_path, capsys) -> None:
        """`config sett goal x` must say "did you mean set", not "get takes no VALUE"."""
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        capsys.readouterr()

        code = cli_main(
            ["config", "sett", "goal", "x", "-p", str(project), "--no-banner"]
        )

        err = capsys.readouterr().err
        assert code == 2
        assert "did you mean 'set'" in err
        assert "get takes no VALUE" not in err

    def test_implicit_get_with_stray_value_is_usage_error(
        self, tmp_path, capsys
    ) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["language"] = "en"
        _write_config(project, config)
        code = cli_main(
            ["config", "language", "stray", "-p", str(project), "--no-banner"]
        )
        assert code == 2
        assert "Usage" in capsys.readouterr().err


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

    def test_get_single_key_json_with_date_scalar(self, tmp_path, capsys) -> None:
        """An unquoted ISO date must serialize instead of raising TypeError.

        Regression: PyYAML resolves ``goal: 2024-06-01`` to a ``datetime.date``,
        which ``json.dumps`` cannot encode. ``--json`` promises a parseable
        object, so this crashed with a raw
        ``TypeError: Object of type date is not JSON serializable``.
        """
        project = _make_project(tmp_path)
        config = _base_config()
        config["goal"] = "ship the thing"
        _write_config(project, config)
        # Write the date form directly so PyYAML infers datetime.date.
        raw = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
        raw = raw.replace("goal: ship the thing", "goal: 2024-06-01")
        (project / CONFIG_YAML).write_text(raw, encoding="utf-8")

        code = cli_main(
            ["config", "get", "goal", "--json", "-p", str(project), "--no-banner"]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == {"goal": "2024-06-01"}

    def test_get_all_keys_json_with_date_scalar(self, tmp_path, capsys) -> None:
        """The all-keys summary must also survive a date-typed scalar."""
        project = _make_project(tmp_path)
        config = _base_config()
        config["goal"] = "ship the thing"
        _write_config(project, config)
        raw = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
        raw = raw.replace("goal: ship the thing", "goal: 2024-06-01")
        (project / CONFIG_YAML).write_text(raw, encoding="utf-8")

        code = cli_main(["config", "--json", "-p", str(project), "--no-banner"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["goal"] == "2024-06-01"

    def test_missing_config_json_emits_error_object(self, tmp_path, capsys) -> None:
        """`--json` means "stdout is JSON", including on precondition failure.

        Regression: a missing config printed a human error to stderr and left
        stdout *empty* (exit 1), while the malformed-section failure in the
        same function did emit {"error": ...} — one command, two contracts.
        """
        project = _make_project(tmp_path)  # no iterate.config.yaml written
        code = cli_main(["config", "--json", "-p", str(project), "--no-banner"])
        assert code == 1
        payload = json.loads(capsys.readouterr().out)
        assert "iterate.config.yaml is missing" in payload["error"]

    def test_missing_config_json_get_emits_error_object(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        code = cli_main(["config", "get", "goal", "--json", "-p", str(project), "--no-banner"])
        assert code == 1
        payload = json.loads(capsys.readouterr().out)
        assert "iterate.config.yaml is missing" in payload["error"]

    def test_unknown_key_json_emits_error_object(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(
            ["config", "get", "nope", "--json", "-p", str(project), "--no-banner"]
        )
        assert code == 1
        payload = json.loads(capsys.readouterr().out)
        assert "Unknown config key" in payload["error"]

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


# ---------------------------------------------------------------------------
# config set --json error contract (stdout must carry one JSON document even
# on failure, matching `config get`)
# ---------------------------------------------------------------------------


class TestConfigSetJsonErrorContract:
    def test_unknown_key_json_emits_error(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(
            ["config", "set", "nope", "x", "--json", "-p", str(project), "--no-banner"]
        )
        assert code == 1
        payload = json.loads(capsys.readouterr().out)
        assert "Unknown config key" in payload["error"]

    def test_invalid_value_json_emits_error(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(
            [
                "config", "set", "reasoning_effort", "turbo",
                "--json", "-p", str(project), "--no-banner",
            ]
        )
        assert code == 1
        payload = json.loads(capsys.readouterr().out)
        assert "Invalid value" in payload["error"]

    def test_missing_config_json_emits_error(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        code = cli_main(
            ["config", "set", "goal", "x", "--json", "-p", str(project), "--no-banner"]
        )
        assert code == 1
        payload = json.loads(capsys.readouterr().out)
        assert "not found" in payload["error"]

    def test_corrupt_yaml_json_emits_error(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text("a: [1, 2\nb: {\n", encoding="utf-8")
        code = cli_main(
            ["config", "set", "goal", "x", "--json", "-p", str(project), "--no-banner"]
        )
        assert code == 1
        payload = json.loads(capsys.readouterr().out)
        assert "not valid YAML" in payload["error"]

    def test_non_mapping_top_level_json_emits_error(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text("- just\n- a\n- list\n", encoding="utf-8")
        code = cli_main(
            ["config", "set", "goal", "x", "--json", "-p", str(project), "--no-banner"]
        )
        assert code == 1
        payload = json.loads(capsys.readouterr().out)
        assert "must be a mapping" in payload["error"]

    def test_scalar_intermediate_json_emits_error(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["git"] = "legacy"
        _write_config(project, config)
        code = cli_main(
            [
                "config", "set", "git.use_worktree", "true",
                "--json", "-p", str(project), "--no-banner",
            ]
        )
        assert code == 1
        payload = json.loads(capsys.readouterr().out)
        assert "intermediate field" in payload["error"]

    def test_json_stdout_is_exactly_one_document_on_failure(
        self, tmp_path, capsys
    ) -> None:
        """The whole --json promise: exactly one parsable JSON doc on stdout."""
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        cli_main(
            ["config", "set", "nope", "x", "--json", "-p", str(project), "--no-banner"]
        )
        out = capsys.readouterr().out
        # json.loads rejects trailing junk, so this proves there is exactly
        # one document and nothing else on stdout.
        json.loads(out)


class TestConfigCommentsWarn:
    def test_set_with_comments_emits_warning(self, tmp_path, capsys) -> None:
        """Hand-written YAML comments are lost on `config set` — say so."""
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text(
            "# review scope\nmax_rounds: 5\n", encoding="utf-8"
        )
        assert run_config_set(project, "max_rounds", "7") == 0
        captured = capsys.readouterr()
        assert "NOT preserved" in captured.out + captured.err
        assert _read_config(project)["max_rounds"] == 7

    def test_set_without_comments_no_warning(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        assert run_config_set(project, "max_rounds", "7") == 0
        captured = capsys.readouterr()
        assert "NOT preserved" not in captured.out + captured.err


# ---------------------------------------------------------------------------
# config unset
# ---------------------------------------------------------------------------


class TestConfigUnset:
    def test_unset_top_level_key_restores_default(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["max_rounds"] = 12
        _write_config(project, config)
        assert run_config_unset(project, "max_rounds") == 0
        assert "max_rounds" not in _read_config(project)

    def test_unset_nested_key_prunes_empty_section(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["git"] = {"use_worktree": True}
        _write_config(project, config)
        assert run_config_unset(project, "git.use_worktree") == 0
        result = _read_config(project)
        # Leaf removed AND the now-empty `git:` section pruned (no litter).
        assert "git" not in result

    def test_unset_nested_key_keeps_sibling(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["git"] = {"use_worktree": True, "auto_merge": True}
        _write_config(project, config)
        assert run_config_unset(project, "git.use_worktree") == 0
        result = _read_config(project)
        assert result["git"] == {"auto_merge": True}

    def test_unset_creates_backup(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["max_rounds"] = 12
        _write_config(project, config)
        assert run_config_unset(project, "max_rounds") == 0
        backups = list(project.glob(f"{CONFIG_YAML}.configunset-*"))
        assert len(backups) == 1

    def test_unset_absent_key_is_error(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        assert run_config_unset(project, "max_rounds") == 1

    def test_unset_unknown_key_is_error(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        assert run_config_unset(project, "nope") == 1

    def test_unset_missing_config_is_error(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        assert run_config_unset(project, "max_rounds") == 1

    def test_unset_corrupt_config_is_error(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text("a: [1, 2\n", encoding="utf-8")
        assert run_config_unset(project, "max_rounds") == 1

    def test_unset_scalar_intermediate_is_error(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["git"] = "legacy"
        _write_config(project, config)
        assert run_config_unset(project, "git.use_worktree") == 1

    def test_unset_json_success(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["max_rounds"] = 12
        _write_config(project, config)
        assert run_config_unset(project, "max_rounds", json_output=True) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["key"] == "max_rounds"
        assert payload["removed"] is True
        assert payload["previous_value"] == 12
        # `null` matches what `config get max_rounds --json` reports once the
        # key is absent (raw value), so scripts can compare the two documents.
        assert payload["value"] is None

    def test_unset_json_error(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        assert run_config_unset(project, "max_rounds", json_output=True) == 1
        payload = json.loads(capsys.readouterr().out)
        assert "nothing to unset" in payload["error"]

    def test_unset_cli_roundtrip(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["max_rounds"] = 12
        _write_config(project, config)
        code = cli_main(
            ["config", "unset", "max_rounds", "-p", str(project), "--no-banner"]
        )
        assert code == 0
        assert "max_rounds" not in _read_config(project)

    def test_unset_cli_missing_key_usage_error(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(["config", "unset", "-p", str(project), "--no-banner"])
        assert code == 2
        assert "Usage" in capsys.readouterr().err

    def test_unset_cli_stray_value_usage_error(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(
            ["config", "unset", "max_rounds", "stray", "-p", str(project), "--no-banner"]
        )
        assert code == 2
        assert "Usage" in capsys.readouterr().err

    def test_unset_cli_usage_error_json(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(
            ["config", "unset", "max_rounds", "stray", "--json",
             "-p", str(project), "--no-banner"]
        )
        assert code == 2
        payload = json.loads(capsys.readouterr().out)
        assert "Usage" in payload["error"]

    def test_unset_then_get_reports_default(self, tmp_path, capsys) -> None:
        """Round-trip: after unset, `config get` shows the documented default."""
        project = _make_project(tmp_path)
        config = _base_config()
        config["language"] = "en"
        _write_config(project, config)
        assert run_config_unset(project, "language") == 0
        capsys.readouterr()  # drain the unset confirmation lines
        assert run_config_get(project, "language", json_output=False) == 0
        assert capsys.readouterr().out.strip() == "default"

    def test_unset_dotted_and_flat_alias_agree(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["atomic"] = {"max_lines": 5}
        _write_config(project, config)
        # The flat alias resolves to the same path as the dotted form.
        assert run_config_unset(project, "atomic.max_lines") == 0
        assert "atomic" not in _read_config(project)


class TestConfigJsonStdoutStaysPureWithComments:
    """A commented config used to print the human "comments NOT preserved"
    warning to STDOUT before the JSON object, so
    `iterate config set ... --json | jq` died with a parse error."""

    def test_set_json_with_comments_is_lone_json(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text(
            "# review scope\nmax_rounds: 5\n", encoding="utf-8"
        )
        rc = run_config_set(project, "max_rounds", "7", json_output=True)
        captured = capsys.readouterr()
        assert rc == 0
        payload = json.loads(captured.out)  # must not raise
        assert payload["value"] == 7
        assert "NOT preserved" not in captured.out
        assert "NOT preserved" in captured.err

    def test_unset_json_with_comments_is_lone_json(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text(
            "# comment\nmax_rounds: 5\n", encoding="utf-8"
        )
        rc = run_config_unset(project, "max_rounds", json_output=True)
        captured = capsys.readouterr()
        assert rc == 0
        json.loads(captured.out)
        assert "\u26a0" not in captured.out


class TestConfigJsonKeyIsCanonical:
    def test_set_json_echoes_canonical_key_for_a_dotted_alias(
        self, tmp_path, capsys
    ) -> None:
        """`config set git.use_worktree` and `config get use_worktree` must
        agree on the key name, otherwise scripts cannot map one to the other."""
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        rc = run_config_set(project, "git.use_worktree", "true", json_output=True)
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["key"] == "use_worktree"

    def test_unset_json_echoes_canonical_key_for_a_dotted_alias(
        self, tmp_path, capsys
    ) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["git"] = {"use_worktree": True}
        _write_config(project, config)
        rc = run_config_unset(project, "git.use_worktree", json_output=True)
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["key"] == "use_worktree"


class TestConfigUnsetMissingSectionMessage:
    def test_absent_section_says_absent_not_wrong_type(self, tmp_path, capsys) -> None:
        """`config unset use_worktree` with no `git:` section used to report
        "intermediate field 'git' is not a mapping" — a type error that does
        not exist, sending the operator to hand-edit a healthy file."""
        project = _make_project(tmp_path)
        _write_config(project, _base_config())  # no `git` section
        rc = run_config_unset(project, "use_worktree")
        captured = capsys.readouterr()
        assert rc == 1
        combined = captured.out + captured.err
        assert "absent" in combined
        assert "is not a mapping" not in combined

    def test_scalar_section_still_reports_the_type_problem(
        self, tmp_path, capsys
    ) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["git"] = "legacy-scalar"
        _write_config(project, config)
        rc = run_config_unset(project, "use_worktree")
        captured = capsys.readouterr()
        assert rc == 1
        assert "is not a mapping" in captured.out + captured.err


class TestSettableKeysDocumentedInReadmes:
    """README's documented ``config set`` key list must match SETTABLE_KEYS.

    Finding: the README used to advertise ``validation.commands`` and
    ``invariants.*`` as settable, but ``_resolve_key`` only accepts the flat
    keys and their dotted-section forms below — a documented-but-broken CLI.
    Guard both prose languages against the same drift in either direction.
    """

    _EXPECTED_FLAT: ClassVar[set[str]] = {
        name for name, spec in SETTABLE_KEYS.items() if not spec.path
    }
    _EXPECTED_DOTTED: ClassVar[set[str]] = {
        ".".join(spec.path) for spec in SETTABLE_KEYS.values() if spec.path
    }

    def _parse_documented_keys(self, text: str) -> tuple[list[str], list[str]]:
        en = re.search(
            r"Supports flat keys \(([^)]*)\) and every nested key in its "
            r"dotted form \(([^)]*)\)",
            text,
        )
        zh = re.search(
            r"支持扁平键（([^）]*)）以及每个嵌套键的点分形式（([^）]*)）",
            text,
        )
        assert en or zh, "README is missing the config-set key list sentence"
        if en:
            return re.findall(r"`([^`]+)`", en.group(1)), re.findall(
                r"`([^`]+)`", en.group(2)
            )
        return re.findall(r"`([^`]+)`", zh.group(1)), re.findall(
            r"`([^`]+)`", zh.group(2)
        )

    def test_english_readme_matches_settable_keys(self) -> None:
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        flat, dotted = self._parse_documented_keys(text)
        assert set(flat) == self._EXPECTED_FLAT
        assert set(dotted) == self._EXPECTED_DOTTED
        # The unsupported values must be explicitly called out as unsupported,
        # not silently listed among the settable keys.
        assert "validation.commands" in text and "are **not** settable here" in text

    def test_chinese_readme_matches_settable_keys(self) -> None:
        text = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        flat, dotted = self._parse_documented_keys(text)
        assert set(flat) == self._EXPECTED_FLAT
        assert set(dotted) == self._EXPECTED_DOTTED
        assert "invariants.*" in text and "不支持" in text
