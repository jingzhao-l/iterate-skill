"""Tests for ``iterate report`` — the aggregated Markdown/JSON document.

The command exists so a project's iterate state can leave the terminal: paste
a report into a PR/issue, upload it as a CI artifact, or gate on it. The tests
pin the contract that makes that safe:

* stdout is a clean document (no banner/TUI noise) and ``--json`` prints
  exactly one parseable document;
* exit codes mirror ``doctor`` (errors block, ``--strict`` adds warnings);
* ``--out`` writes atomically and never overwrites iterate's own state;
* every project state (not onboarded, corrupt config, drift) renders instead
  of crashing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iterate_cli.cli import main as cli_main
from iterate_cli.report import build_report, render_markdown

CONFIG = "iterate.config.yaml"
MD = "ITERATE.md"


def _make_python_project(root: Path) -> Path:
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (root / "src" / "api").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / ".github" / "workflows").mkdir(parents=True)
    return root


def _initialized(tmp_path: Path, capsys) -> Path:
    _make_python_project(tmp_path)
    capsys.readouterr()
    assert cli_main(["init", "-p", str(tmp_path), "--yes"]) == 0
    capsys.readouterr()
    return tmp_path


def _report(root: Path, *extra: str, capsys=None) -> tuple[int, str, str]:
    code = cli_main(["report", "-p", str(root), "--no-banner", *extra])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class TestMarkdownOutput:
    def test_healthy_project_renders_a_pasteable_document(
        self, tmp_path: Path, capsys
    ) -> None:
        _initialized(tmp_path, capsys)

        code, out, _ = _report(tmp_path, capsys=capsys)

        assert code == 0
        assert out.startswith("# Iterate Project Report\n")
        assert "| Item | Value |" in out
        assert "| Languages | Python |" in out
        assert "| Dimension sets |" in out
        assert "| Health checks |" not in out
        assert "## Health checks" in out
        assert "healthy" in out
        assert "No drift detected" in out
        assert "## Next steps" in out
        assert str(tmp_path) in out
        assert "<" not in out.splitlines()[0]  # no ANSI TUI markup on the title

    def test_output_uses_project_language(self, tmp_path: Path, capsys) -> None:
        _initialized(tmp_path, capsys)
        config = tmp_path / CONFIG
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                "language: en", "language: zh"
            ),
            encoding="utf-8",
        )
        capsys.readouterr()

        code, out, _ = _report(tmp_path, capsys=capsys)

        assert code == 0
        assert "# Iterate 项目报告" in out
        assert "## 技术栈" in out
        assert "## 下一步" in out

    def test_corrupt_config_is_reported_not_raised(
        self, tmp_path: Path, capsys
    ) -> None:
        _initialized(tmp_path, capsys)
        (tmp_path / CONFIG).write_text("goal: [unterminated\n", encoding="utf-8")
        capsys.readouterr()

        code, out, _ = _report(tmp_path, capsys=capsys)

        assert code == 1
        assert "needs attention" in out
        assert "config.parse" in out

    def test_not_onboarded_project_is_rendered(self, tmp_path: Path, capsys) -> None:
        _make_python_project(tmp_path)
        capsys.readouterr()

        code, out, _ = _report(tmp_path, capsys=capsys)

        assert code == 1  # doctor: onboarding is missing (an error)
        assert "not initialized" in out
        assert "iterate init --yes" in out

    def test_drift_is_surfaced_with_a_fix_command(
        self, tmp_path: Path, capsys
    ) -> None:
        _initialized(tmp_path, capsys)
        with (tmp_path / "pyproject.toml").open("a", encoding="utf-8") as handle:
            handle.write("\n# new dependency\n")
        capsys.readouterr()

        code, out, _ = _report(tmp_path, capsys=capsys)

        assert code == 0  # drift is a warning, not a hard failure
        assert "changed: pyproject.toml" in out
        assert "iterate refresh" in out

    def test_malformed_nested_values_do_not_crash_the_render(
        self, tmp_path: Path, capsys
    ) -> None:
        """A hand-edited config can violate the schema; the report must render.

        `iterate report` is a diagnostic command, so it is the *last* place
        allowed to traceback on the broken config it is supposed to describe.
        """
        _initialized(tmp_path, capsys)
        config = tmp_path / CONFIG
        text = config.read_text(encoding="utf-8")
        text = text.replace(
            "validation:\n",
            "dimension_sets:\n  - not-a-mapping\nvalidation:\n  bad: [1, 2]\n",
            1,
        )
        config.write_text(text, encoding="utf-8")
        capsys.readouterr()

        code, out, _ = _report(tmp_path, capsys=capsys)

        assert code == 1  # doctor reports the schema violations
        assert "## Review configuration" in out
        assert "needs attention" in out

    def test_pipes_in_values_are_escaped(self) -> None:
        report = {
            "language": "en",
            "skill_version": "9.9.9",
            "generated_at": "2026-01-01T00:00:00Z",
            "project": "/tmp/a|b",
            "onboarded": False,
            "onboarding": {},
            "config": {},
            "scan": {},
            "features": [],
            "summary": {
                "passed": 0,
                "warnings": 0,
                "errors": 1,
                "blocking": True,
                "health": "errors",
            },
            "doctor": {
                "findings": [
                    {
                        "severity": "error",
                        "check": "x|y",
                        "message": "line one | line two\nline three",
                        "detail": "",
                    }
                ]
            },
            "drift": "unknown",
            "drift_advice": None,
            "next_actions": ["iterate doctor"],
            "personalization_rules": 0,
        }

        text = render_markdown(report)

        assert r"x\|y" in text
        assert r"line one \| line two line three" in text
        assert text.count("\n|") >= 1

    def test_backticks_in_values_are_escaped(self) -> None:
        """A stray backtick must not open a code span and swallow the table."""
        report = {
            "language": "en",
            "skill_version": "9.9.9",
            "generated_at": "2026-01-01T00:00:00Z",
            "project": "/tmp/a`b",
            "onboarded": False,
            "onboarding": {},
            "config": {},
            "scan": {},
            "features": [],
            "summary": {
                "passed": 0,
                "warnings": 0,
                "errors": 1,
                "blocking": True,
                "health": "errors",
            },
            "doctor": {
                "findings": [
                    {
                        "severity": "error",
                        "check": "x`y",
                        "message": "open ` tick",
                        "detail": "",
                    }
                ]
            },
            "drift": "unknown",
            "drift_advice": None,
            "next_actions": ["iterate doctor"],
            "personalization_rules": 0,
        }

        text = render_markdown(report)

        assert r"x\`y" in text
        assert r"open \` tick" in text
        assert r"/tmp/a\`b" in text
        assert "x`y" not in text

    def test_html_markup_in_values_is_escaped(self) -> None:
        """Project-controlled values must not inject raw HTML into the report."""
        report = {
            "language": "en",
            "skill_version": "9.9.9",
            "generated_at": "2026-01-01T00:00:00Z",
            "project": "/tmp/<project>",
            "onboarded": False,
            "onboarding": {},
            "config": {},
            "scan": {},
            "features": [],
            "summary": {
                "passed": 0,
                "warnings": 0,
                "errors": 1,
                "blocking": True,
                "health": "errors",
            },
            "doctor": {
                "findings": [
                    {
                        "severity": "error",
                        "check": "<script>check</script>",
                        "message": "<img src=x onerror=alert(1)>",
                        "detail": "",
                    }
                ]
            },
            "drift": "unknown",
            "drift_advice": None,
            "next_actions": ["iterate doctor"],
            "personalization_rules": 0,
        }

        text = render_markdown(report)

        assert "&lt;img src=x onerror=alert(1)&gt;" in text
        assert "&lt;script&gt;check&lt;/script&gt;" in text
        assert "&lt;project&gt;" in text
        assert "<img" not in text
        assert "<script>" not in text


class TestJsonOutput:
    def test_json_is_one_document_with_stable_keys(
        self, tmp_path: Path, capsys
    ) -> None:
        _initialized(tmp_path, capsys)

        code, out, _ = _report(tmp_path, "--json", capsys=capsys)

        payload = json.loads(out)
        assert code == 0
        assert payload["ok"] is True
        assert payload["command"] == "report"
        assert payload["onboarded"] is True
        for key in (
            "project",
            "skill_version",
            "generated_at",
            "language",
            "onboarding",
            "config",
            "scan",
            "doctor",
            "summary",
            "next_actions",
            "drift",
            "drift_advice",
        ):
            assert key in payload
        assert payload["summary"]["blocking"] is False
        assert payload["doctor"]["healthy"] is True

    def test_json_failure_still_emits_one_document(
        self, tmp_path: Path, capsys
    ) -> None:
        (tmp_path / CONFIG).write_text("goal: [unterminated\n", encoding="utf-8")
        capsys.readouterr()

        code, out, _ = _report(tmp_path, "--json", capsys=capsys)

        payload = json.loads(out)
        assert code == 1
        assert payload["ok"] is False
        assert payload["summary"]["blocking"] is True

    def test_strict_makes_warnings_blocking(self, tmp_path: Path, capsys) -> None:
        _initialized(tmp_path, capsys)
        with (tmp_path / "pyproject.toml").open("a", encoding="utf-8") as handle:
            handle.write("\n# drift\n")
        capsys.readouterr()

        default_code, default_out, _ = _report(tmp_path, "--json", capsys=capsys)
        strict_code, strict_out, _ = _report(
            tmp_path, "--json", "--strict", capsys=capsys
        )

        assert json.loads(default_out)["summary"]["blocking"] is False
        assert default_code == 0
        assert json.loads(strict_out)["summary"]["blocking"] is True
        assert strict_code == 1


class TestOutFile:
    def test_out_writes_the_document_and_keeps_stdout_empty(
        self, tmp_path: Path, capsys
    ) -> None:
        _initialized(tmp_path, capsys)
        target = tmp_path / "artifacts" / "report.md"
        target.parent.mkdir()

        code, out, _ = _report(tmp_path, "--out", str(target), capsys=capsys)

        assert code == 0
        assert out == ""
        assert target.read_text(encoding="utf-8").startswith(
            "# Iterate Project Report"
        )

    def test_out_json_writes_a_parseable_file(self, tmp_path: Path, capsys) -> None:
        _initialized(tmp_path, capsys)
        target = tmp_path / "report.json"

        code, out, _ = _report(
            tmp_path, "--json", "--out", str(target), capsys=capsys
        )

        assert code == 0
        assert out == ""
        assert json.loads(target.read_text(encoding="utf-8"))["ok"] is True

    def test_out_dash_prints_to_stdout(self, tmp_path: Path, capsys) -> None:
        _initialized(tmp_path, capsys)

        code, out, _ = _report(tmp_path, "--out", "-", capsys=capsys)

        assert code == 0
        assert out.startswith("# Iterate Project Report")

    def test_out_refuses_to_clobber_iterate_state(
        self, tmp_path: Path, capsys
    ) -> None:
        _initialized(tmp_path, capsys)
        original = (tmp_path / CONFIG).read_text(encoding="utf-8")
        capsys.readouterr()

        code, _out, err = _report(
            tmp_path, "--out", str(tmp_path / CONFIG), capsys=capsys
        )

        assert code == 2
        assert "refusing to overwrite" in err
        assert (tmp_path / CONFIG).read_text(encoding="utf-8") == original

    def test_out_refuses_to_overwrite_user_file_without_force(
        self, tmp_path: Path, capsys
    ) -> None:
        _initialized(tmp_path, capsys)
        target = tmp_path / "report.md"
        target.write_text("my notes\n", encoding="utf-8")

        code, _, err = _report(tmp_path, "--out", str(target), capsys=capsys)

        assert code == 2
        assert "refusing to overwrite existing file" in err
        # The user's file is untouched.
        assert target.read_text(encoding="utf-8") == "my notes\n"

    def test_out_overwrites_with_force(self, tmp_path: Path, capsys) -> None:
        _initialized(tmp_path, capsys)
        target = tmp_path / "report.md"
        target.write_text("stale\n", encoding="utf-8")

        code, _, err = _report(
            tmp_path, "--out", str(target), "--force", capsys=capsys
        )

        assert code == 0
        assert "written to" in err
        assert target.read_text(encoding="utf-8").startswith("# ")

    def test_out_missing_parent_is_actionable(self, tmp_path: Path, capsys) -> None:
        _initialized(tmp_path, capsys)

        code, _, err = _report(
            tmp_path, "--out", str(tmp_path / "nope" / "r.md"), capsys=capsys
        )

        assert code == 1
        assert "parent directory does not exist" in err

    def test_out_empty_is_a_usage_error(self, tmp_path: Path, capsys) -> None:
        _initialized(tmp_path, capsys)

        code, _, err = _report(tmp_path, "--out", "", capsys=capsys)

        assert code == 2
        assert "--out must not be empty" in err


class TestProjectResolution:
    def test_missing_project_emits_json_error(self, tmp_path: Path, capsys) -> None:
        missing = tmp_path / "missing"

        code = cli_main(["report", "-p", str(missing), "--json"])

        payload = json.loads(capsys.readouterr().out)
        assert code == 1
        assert "project directory not found" in payload["error"]

    def test_help_lists_report(self, capsys) -> None:
        capsys.readouterr()

        code = cli_main(["help", "report"])

        out = capsys.readouterr().out
        assert code == 0
        assert "usage: iterate report" in out
        assert "--strict" in out

    def test_every_report_key_is_json_serialisable(self, tmp_path: Path, capsys) -> None:
        _initialized(tmp_path, capsys)

        report = build_report(tmp_path)

        json.dumps(report)  # must not raise
        assert report["command"] == "report"
        assert report["config"]["dimension_sets"]
