"""Tests for ``iterate next`` — the guided next-action plan.

``status``/``show``/``doctor`` report state; ``next`` is the first command that
turns that state into an ordered answer to "what do I run now?". These tests
cover every state transition (fresh project, half-onboarded, corrupt config,
drift, failing checks, warnings, healthy) plus the ``--json`` contract.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from iterate_cli.cli import main as cli_main
from iterate_cli.nextcmd import (
    STATE_CONFIG_CORRUPT,
    STATE_CONFIG_MISSING,
    STATE_DRIFT,
    STATE_HEALTHY,
    STATE_NOT_ONBOARDED,
    STATE_UNHEALTHY,
    STATE_WARNINGS,
    plan_next,
)

_PACKAGE_JSON = {
    "name": "demo",
    "version": "1.0.0",
    "scripts": {"test": "echo ok", "build": "echo build", "lint": "echo lint"},
}


def _init_project(tmp_path: Path) -> Path:
    """Create a project that ``iterate init --yes`` can onboard cleanly."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "package.json").write_text(
        json.dumps(_PACKAGE_JSON) + "\n", encoding="utf-8"
    )
    (project / "src").mkdir()
    (project / "src" / "a.py").write_text("print(1)\n", encoding="utf-8")
    code = cli_main(["init", "--yes", "--json", "-p", str(project)])
    assert code == 0
    return project


def _run_next(project: Path, *args: str) -> tuple[int, str, str]:
    import contextlib
    import io

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_main(["next", "--no-banner", "-p", str(project), *args])
    return code, out.getvalue(), err.getvalue()


def _rewrite_config(project: Path, mutate) -> None:
    path = project / "iterate.config.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(config)
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


class TestPlanStates:
    def test_empty_project_plans_init(self, tmp_path: Path) -> None:
        plan = plan_next(tmp_path)
        assert plan["state"] == STATE_NOT_ONBOARDED
        assert plan["blocking"] is True
        assert plan["onboarded"] is False
        assert plan["next"]["command"] == "iterate init --yes"
        assert "no iterate.config.yaml" in plan["next"]["reason"].lower()
        assert any("Not a git repository" in note for note in plan["notes"])

    def test_initialized_project_is_healthy(self, tmp_path: Path) -> None:
        project = _init_project(tmp_path)
        plan = plan_next(project)
        assert plan["state"] == STATE_HEALTHY
        assert plan["blocking"] is False
        assert plan["drift"] is False
        assert plan["doctor"] == {"errors": 0, "warnings": 0}
        assert plan["next"]["command"].startswith("/iterate")
        assert plan["steps"][1]["command"] == "iterate personalize"

    def test_corrupt_config_plans_doctor_fix(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        (project / "iterate.config.yaml").write_text(
            "dimensions: [unclosed\n", encoding="utf-8"
        )
        plan = plan_next(project)
        assert plan["state"] == STATE_CONFIG_CORRUPT
        assert plan["blocking"] is True
        assert plan["config_ok"] is False
        assert plan["next"]["command"] == "iterate doctor --fix"
        assert any("backup" in note.lower() for note in plan["notes"])

    def test_config_without_iterate_md_plans_onboard(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        (project / "iterate.config.yaml").write_text(
            "dimensions:\n  - correctness\n", encoding="utf-8"
        )
        plan = plan_next(project)
        assert plan["state"] == STATE_NOT_ONBOARDED
        assert plan["next"]["command"] == "iterate onboard"

    def test_iterate_md_without_config_plans_init(self, tmp_path: Path) -> None:
        project = _init_project(tmp_path)
        (project / "iterate.config.yaml").unlink()
        plan = plan_next(project)
        assert plan["state"] == STATE_CONFIG_MISSING
        assert plan["next"]["command"] == "iterate init --yes"
        assert "preserves the USER-OWNED" in plan["next"]["reason"]

    def test_drift_plans_refresh_diff_then_refresh(self, tmp_path: Path) -> None:
        project = _init_project(tmp_path)
        changed = dict(_PACKAGE_JSON)
        changed["dependencies"] = {"left-pad": "1.0.0"}
        (project / "package.json").write_text(
            json.dumps(changed) + "\n", encoding="utf-8"
        )
        plan = plan_next(project)
        assert plan["state"] == STATE_DRIFT
        assert plan["drift"] is True
        assert plan["blocking"] is True
        assert plan["next"]["command"] == "iterate refresh --diff"
        assert "package.json" in plan["next"]["detail"]
        assert plan["steps"][1]["command"] == "iterate refresh"

    def test_unhealthy_plans_doctor_fix(self, tmp_path: Path) -> None:
        project = _init_project(tmp_path)
        _rewrite_config(project, lambda cfg: cfg.__setitem__("max_rounds", 0))
        plan = plan_next(project)
        assert plan["state"] == STATE_UNHEALTHY
        assert plan["blocking"] is True
        assert plan["next"]["command"] == "iterate doctor --fix"
        assert plan["doctor"]["errors"] >= 1

    def test_warnings_do_not_block(self, tmp_path: Path) -> None:
        project = _init_project(tmp_path)

        def _stale_version(cfg: dict) -> None:
            cfg.setdefault("onboarding", {})["skill_version"] = "0.0.1"

        _rewrite_config(project, _stale_version)
        plan = plan_next(project)
        assert plan["state"] == STATE_WARNINGS
        assert plan["blocking"] is False
        assert plan["next"]["command"] == "iterate doctor"
        assert plan["doctor"]["warnings"] >= 1


class TestCli:
    def test_json_is_one_document_and_exits_zero(self, tmp_path: Path) -> None:
        code, out, err = _run_next(tmp_path, "--json")
        assert code == 0, err
        payload = json.loads(out)  # exactly one document
        assert payload["command"] == "next"
        assert payload["state"] == STATE_NOT_ONBOARDED
        # Stable keys are present in every payload.
        for key in (
            "project",
            "state",
            "blocking",
            "onboarded",
            "config_exists",
            "config_ok",
            "drift",
            "drift_reason",
            "doctor",
            "next",
            "steps",
            "notes",
        ):
            assert key in payload

    def test_human_output_shows_command_and_reason(self, tmp_path: Path) -> None:
        code, out, _ = _run_next(tmp_path)
        assert code == 0
        assert "Next step" in out
        assert "iterate init --yes" in out
        assert "No iterate.config.yaml" in out

    def test_healthy_json_plans_iterate_goal(self, tmp_path: Path) -> None:
        project = _init_project(tmp_path)
        code, out, err = _run_next(project, "--json")
        assert code == 0, err
        payload = json.loads(out)
        assert payload["state"] == STATE_HEALTHY
        assert payload["blocking"] is False
        assert payload["next"]["command"].startswith("/iterate")

    def test_help_lists_next(self) -> None:
        import contextlib
        import io

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli_main(["help", "next"])
        assert code == 0
        assert "usage: iterate next" in out.getvalue()

    def test_top_level_help_lists_next(self) -> None:
        import contextlib
        import io

        import pytest

        out = io.StringIO()
        with contextlib.redirect_stdout(out), pytest.raises(SystemExit) as excinfo:
            cli_main(["--help"])
        assert excinfo.value.code == 0
        assert "next" in out.getvalue()
