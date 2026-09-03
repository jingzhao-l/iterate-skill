"""Tests for iterate_cli.guard (defensive-programming guards and invariants).

Covers ``run_guard_precheck`` / ``run_guard_postcheck`` / ``run_invariant_check``
across normal, failure and boundary paths, plus ``render_guard_result`` JSON
output and the ``iterate guard`` / ``iterate invariant`` CLI exit codes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from iterate_cli.cli import main as cli_main
from iterate_cli.guard import (
    EXIT_FAIL,
    EXIT_PASS,
    render_guard_result,
    run_guard_postcheck,
    run_guard_precheck,
    run_invariant_check,
)

CONFIG_YAML = "iterate.config.yaml"


def _make_project(tmp_path: Path) -> Path:
    """Create a minimal project under tmp_path (no onboarding required)."""
    project = tmp_path / "proj"
    project.mkdir(parents=True)
    return project


def _write_config(project: Path, config: dict) -> None:
    (project / CONFIG_YAML).write_text(
        yaml.safe_dump(config, allow_unicode=True), encoding="utf-8"
    )


def _base_config() -> dict:
    return {
        "dimensions": ["correctness", "security"],
        "validation": {
            "commands": {
                "python": ["true"],
            }
        },
    }


# ---------------------------------------------------------------------------
# run_guard_precheck
# ---------------------------------------------------------------------------


class TestGuardPrecheck:
    def test_clean_project_passes(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        target = project / "a.txt"
        target.write_text("x", encoding="utf-8")
        # No config, no git repo: manifest/git checks degrade gracefully.
        result = run_guard_precheck(project, ["a.txt"])
        assert result.passed is True

    def test_no_paths_arguments_passes(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        result = run_guard_precheck(project, [])
        assert result.passed is True
        assert any(label == "targets exist" for label, ok, _ in result.items)

    def test_missing_target_fails(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        result = run_guard_precheck(project, ["nope.txt"])
        assert result.passed is False
        assert any(label == "targets exist" and not ok for label, ok, _ in result.items)

    def test_missing_manifest_fails(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())  # validation.commands.python configured
        result = run_guard_precheck(project, [])
        assert result.passed is False
        assert any(label == "manifest[python]" and not ok for label, ok, _ in result.items)

    def test_present_manifest_passes(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
        _write_config(project, _base_config())
        result = run_guard_precheck(project, [])
        assert result.passed is True
        assert any(label == "manifests ready" and ok for label, ok, _ in result.items)

    def test_dirty_worktree_fails(self, tmp_path, monkeypatch) -> None:
        project = _make_project(tmp_path)
        monkeypatch.setattr("iterate_cli.guard._git_root", lambda _root: project)
        monkeypatch.setattr(
            "iterate_cli.guard._git_worktree_is_clean",
            lambda _root: (False, "1 tracked change(s)"),
        )
        result = run_guard_precheck(project, [])
        assert result.passed is False
        assert any(label == "git clean" and not ok for label, ok, _ in result.items)

    def test_clean_worktree_passes(self, tmp_path, monkeypatch) -> None:
        project = _make_project(tmp_path)
        monkeypatch.setattr("iterate_cli.guard._git_root", lambda _root: project)
        monkeypatch.setattr(
            "iterate_cli.guard._git_worktree_is_clean", lambda _root: (True, "worktree clean")
        )
        result = run_guard_precheck(project, [])
        assert result.passed is True
        assert any(label == "git clean" and ok for label, ok, _ in result.items)

    def test_corrupt_config_fails(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text("{unclosed yaml", encoding="utf-8")
        result = run_guard_precheck(project, [])
        assert result.passed is False
        assert any(label == "config readable" and not ok for label, ok, _ in result.items)

    def test_unsafe_validation_command_fails(self, tmp_path) -> None:
        """A hand-edited config whose validation.commands contains shell-chaining
        metacharacters must fail pre-check (fail-closed, never a green light)."""
        project = _make_project(tmp_path)
        (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
        config = _base_config()
        config["validation"]["commands"] = {"python": ["true; rm -rf /tmp/x"]}
        _write_config(project, config)
        result = run_guard_precheck(project, [])
        assert result.passed is False
        assert any(label == "validation commands" and not ok for label, ok, _ in result.items)


# ---------------------------------------------------------------------------
# run_guard_postcheck
# ---------------------------------------------------------------------------


class TestGuardPostcheck:
    def test_passing_command_passes(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())  # python: ["true"]
        result = run_guard_postcheck(project, None)
        assert result.passed is True

    def test_failing_command_fails(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["validation"]["commands"] = {"python": ["exit 1"]}
        _write_config(project, config)
        result = run_guard_postcheck(project, None)
        assert result.passed is False

    def test_no_commands_configured_fails(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, {"dimensions": ["correctness"]})
        result = run_guard_postcheck(project, None)
        assert result.passed is False

    def test_module_filter_runs_only_selected(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["validation"]["commands"] = {
            "python": ["true"],
            "typescript": ["true"],
        }
        _write_config(project, config)
        result = run_guard_postcheck(project, ["typescript"])
        assert result.passed is True
        labels = [label for label, _, _ in result.items]
        assert "typescript" in labels
        assert "python" not in labels

    def test_dry_run_previews_without_executing(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        result = run_guard_postcheck(project, None, dry_run=True)
        assert result.passed is True
        assert any("would run" in detail for _, _, detail in result.items)

    def test_corrupt_config_fails(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text("{unclosed yaml", encoding="utf-8")
        result = run_guard_postcheck(project, None)
        assert result.passed is False

    def test_unsafe_command_refused_execution(self, tmp_path) -> None:
        """A command containing shell-chaining metacharacters must be REFUSED at
        execution time — never passed to subprocess.run(shell=True)."""
        project = _make_project(tmp_path)
        marker = project / "pwned_marker"
        config = _base_config()
        config["validation"]["commands"] = {
            "python": [f"true; touch {marker.name}"]
        }
        _write_config(project, config)
        result = run_guard_postcheck(project, None)
        assert result.passed is False
        assert any("refused: unsafe command" in detail for _, _, detail in result.items)
        # Fail-closed: the command was never executed, so no side effect.
        assert not marker.exists()

    def test_unsafe_command_refused_dry_run(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["validation"]["commands"] = {"python": ["true && echo pwned"]}
        _write_config(project, config)
        result = run_guard_postcheck(project, None, dry_run=True)
        assert result.passed is False
        assert any("refused: unsafe command" in detail for _, _, detail in result.items)

    def test_unconfigured_module_reported_as_failure(self, tmp_path) -> None:
        """Requesting a module that has no validation.commands entry must FAIL,
        never silently skip (a host AI must not believe it was validated)."""
        project = _make_project(tmp_path)
        _write_config(project, _base_config())  # only "python" configured
        result = run_guard_postcheck(project, ["rust"])
        assert result.passed is False
        assert any(
            label == "rust" and "requested but not configured" in detail
            for label, _, detail in result.items
        )


# ---------------------------------------------------------------------------
# run_invariant_check
# ---------------------------------------------------------------------------


class TestInvariantCheck:
    def test_ensure_and_commands_pass(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        (project / "README.md").write_text("# Demo\n", encoding="utf-8")
        config = _base_config()
        config["invariants"] = {
            "ensure": ["README.md"],
            "commands": {"python": ["true"]},
        }
        _write_config(project, config)
        result = run_invariant_check(project)
        assert result.passed is True
        assert any(label == "ensure:README.md" and ok for label, ok, _ in result.items)

    def test_missing_ensure_fails(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["invariants"] = {"ensure": ["README.md"], "commands": {}}
        _write_config(project, config)
        result = run_invariant_check(project)
        assert result.passed is False
        assert any(label == "ensure:README.md" and not ok for label, ok, _ in result.items)

    def test_failing_invariant_command_fails(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["invariants"] = {"commands": {"python": ["exit 1"]}}
        _write_config(project, config)
        result = run_invariant_check(project)
        assert result.passed is False

    def test_falls_back_to_validation_commands(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        # No invariants section -> degrades to validation.commands.
        _write_config(project, _base_config())
        result = run_invariant_check(project)
        assert result.passed is True
        assert any("fallback" in label for label, _, _ in result.items)

    def test_empty_project_passes(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        # No config at all: nothing to assert -> passes.
        result = run_invariant_check(project)
        assert result.passed is True

    def test_dry_run_previews_without_executing(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        result = run_invariant_check(project, dry_run=True)
        assert result.passed is True
        assert any("would run" in detail for _, _, detail in result.items)

    def test_corrupt_config_fails(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        (project / CONFIG_YAML).write_text("{unclosed yaml", encoding="utf-8")
        result = run_invariant_check(project)
        assert result.passed is False

    def test_unsafe_invariant_command_refused(self, tmp_path) -> None:
        """invariants.commands with shell-chaining metacharacters must be refused
        at execution time, never run through the shell."""
        project = _make_project(tmp_path)
        config = _base_config()
        config["invariants"] = {"commands": {"python": ["true; echo pwned"]}}
        _write_config(project, config)
        result = run_invariant_check(project)
        assert result.passed is False
        assert any("refused: unsafe command" in detail for _, _, detail in result.items)


# ---------------------------------------------------------------------------
# render_guard_result — JSON output + exit codes
# ---------------------------------------------------------------------------


class TestRenderGuardResult:
    def test_json_output_valid_and_exit_code(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        result = run_guard_precheck(project, [])
        code = render_guard_result(result, json_output=True)
        data = json.loads(capsys.readouterr().out)
        assert data["check"] == result.name
        assert data["passed"] == result.passed
        assert data["dry_run"] is False
        assert code == (EXIT_PASS if result.passed else EXIT_FAIL)

    def test_failed_result_exits_nonzero_json(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        result = run_guard_precheck(project, ["missing.txt"])
        code = render_guard_result(result, json_output=True)
        assert code == EXIT_FAIL
        data = json.loads(capsys.readouterr().out)
        assert data["passed"] is False


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestGuardCLI:
    def test_guard_precheck_cli_json(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        (project / "a.txt").write_text("x", encoding="utf-8")
        code = cli_main(["guard", "pre-check", "a.txt", "-p", str(project), "--json"])
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert data["check"] == "guard-pre"
        assert data["passed"] is True

    def test_guard_precheck_missing_target_exit(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        code = cli_main(["guard", "pre-check", "nope.txt", "-p", str(project)])
        assert code == EXIT_FAIL

    def test_guard_postcheck_cli_json(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(["guard", "post-check", "-p", str(project), "--json"])
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert data["check"] == "guard-post"

    def test_invariant_cli_json(self, tmp_path, capsys) -> None:
        project = _make_project(tmp_path)
        _write_config(project, _base_config())
        code = cli_main(["invariant", "-p", str(project), "--json"])
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert data["check"] == "invariant"

    def test_invariant_cli_fail_exit(self, tmp_path) -> None:
        project = _make_project(tmp_path)
        config = _base_config()
        config["invariants"] = {"ensure": ["README.md"], "commands": {}}
        _write_config(project, config)
        code = cli_main(["invariant", "-p", str(project)])
        assert code == EXIT_FAIL
