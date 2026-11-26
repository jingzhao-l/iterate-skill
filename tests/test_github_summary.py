"""Tests for GitHub Actions run-summary output (``iterate report``).

``report`` aggregates the project state into one Markdown document, but inside
GitHub Actions that document landed only in the job log or a downloaded
artifact. ``--github-summary`` appends it to ``$GITHUB_STEP_SUMMARY`` so it
renders on the workflow's run-summary page — the place developers already look
for a CI outcome.

The tests pin the contract that keeps this safe:

* the summary is a **separate sink** — it never touches stdout (so ``--json``
  still emits exactly one machine document), never changes the exit code, and
  the summary always carries the *Markdown* form (the page is for humans);
* append (never truncate) semantics, because the runner lets every step write
  to the same per-job summary file;
* the ``--github-summary``/``--no-github-summary``/auto tri-state, matching the
  ``--annotate`` convention (explicit flags win, otherwise ``GITHUB_STEP_SUMMARY``
  auto-detects);
* an explicit ``--github-summary`` outside GitHub Actions is a usage error
  (exit 2) that says what to do, instead of silently writing nowhere;
* an unwritable summary warns but never fails the report gate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iterate_cli.cli import main as cli_main
from iterate_cli.report import (
    append_github_summary,
    enabled_from_args,
    enabled_from_env,
    github_summary_path,
)

CONFIG = "iterate.config.yaml"


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


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------

def test_enabled_from_env_requires_the_env_var(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert enabled_from_env() is False
    assert github_summary_path() is None

    monkeypatch.setenv("GITHUB_STEP_SUMMARY", "/tmp/summary.md")
    assert enabled_from_env() is True
    assert github_summary_path() == "/tmp/summary.md"


def test_enabled_from_args_tri_state(monkeypatch) -> None:
    # Explicit flags always win.
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", "/tmp/summary.md")
    assert enabled_from_args(True) is True
    assert enabled_from_args(False) is False
    # Auto-detect only when the flag is not given.
    assert enabled_from_args(None) is True

    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert enabled_from_args(True) is True  # explicit still on (fails later if no path)
    assert enabled_from_args(False) is False
    assert enabled_from_args(None) is False


def test_enabled_from_args_empty_env_is_off(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", "   ")
    assert enabled_from_env() is False
    assert github_summary_path() is None


# ---------------------------------------------------------------------------
# Append helper
# ---------------------------------------------------------------------------

def test_append_creates_and_appends(tmp_path: Path) -> None:
    target = tmp_path / "summary.md"
    assert append_github_summary("# first", str(target)) == target
    # Second write appends (does not truncate) and guarantees a newline.
    append_github_summary("second", str(target))
    assert target.read_text(encoding="utf-8") == "# first\nsecond\n"


def test_append_adds_trailing_newline(tmp_path: Path) -> None:
    target = tmp_path / "summary.md"
    append_github_summary("line1\nline2", str(target))
    assert target.read_text(encoding="utf-8") == "line1\nline2\n"


def test_append_without_path_returns_none() -> None:
    assert append_github_summary("x") is None


def test_append_uses_env_path(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "env-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    append_github_summary("hello")
    assert target.read_text(encoding="utf-8") == "hello\n"


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestCliGitHubSummary:
    def test_explicit_flag_writes_summary(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        _initialized(tmp_path, capsys)
        summary = tmp_path / "step-summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

        code, out, _err = _report(tmp_path, "--github-summary", capsys=capsys)

        assert code == 0
        # stdout is still the Markdown document, byte-identical to no flag.
        assert out.startswith("# Iterate Project Report\n")
        assert summary.exists()
        body = summary.read_text(encoding="utf-8")
        assert "# Iterate Project Report" in body
        assert "## Health checks" in body
        assert "## Next steps" in body

    def test_auto_detects_when_env_is_set(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        _initialized(tmp_path, capsys)
        summary = tmp_path / "auto-summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

        code, _, _ = _report(tmp_path, capsys=capsys)

        assert code == 0
        assert summary.exists()
        assert "# Iterate Project Report" in summary.read_text(encoding="utf-8")

    def test_no_flag_skips_when_env_absent(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        _initialized(tmp_path, capsys)
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

        code, _, _ = _report(tmp_path, capsys=capsys)

        assert code == 0
        assert not (tmp_path / "step-summary.md").exists()

    def test_no_github_summary_disables_auto(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        _initialized(tmp_path, capsys)
        summary = tmp_path / "disabled.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

        code, _, _ = _report(tmp_path, "--no-github-summary", capsys=capsys)

        assert code == 0
        assert not summary.exists()

    def test_explicit_flag_without_env_is_usage_error(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        _initialized(tmp_path, capsys)
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

        code, out, err = _report(tmp_path, "--github-summary", capsys=capsys)

        assert code == 2
        assert "GITHUB_STEP_SUMMARY" in err
        assert "workflow step" in err
        # The report itself is not emitted to stdout on this path.
        assert out == ""

    def test_json_keeps_stdout_clean_and_summary_markdown(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        _initialized(tmp_path, capsys)
        summary = tmp_path / "json-summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

        code, out, _ = _report(tmp_path, "--json", "--github-summary", capsys=capsys)

        assert code == 0
        payload = json.loads(out)  # exactly one JSON document on stdout
        assert payload["command"] == "report"
        # The summary still carries the human Markdown form.
        body = summary.read_text(encoding="utf-8")
        assert "# Iterate Project Report" in body
        assert "## Health checks" in body

    def test_unwritable_summary_warns_but_does_not_fail(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        _initialized(tmp_path, capsys)
        # Point the summary at a directory: opening it for append raises EISDIR.
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path))

        code, out, err = _report(tmp_path, "--github-summary", capsys=capsys)

        assert code == 0  # the gate is unaffected
        assert out.startswith("# Iterate Project Report")
        assert "could not write GitHub step summary" in err

    def test_flags_are_mutually_exclusive(self, capsys) -> None:
        with pytest.raises(SystemExit) as excinfo:
            cli_main(
                ["report", "-p", "/tmp", "--github-summary", "--no-github-summary"]
            )
        assert excinfo.value.code == 2

    def test_bundle_contract_on_usage_error(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        _initialized(tmp_path, capsys)
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

        code, out, _err = _report(
            tmp_path, "--json", "--github-summary", capsys=capsys
        )

        assert code == 2
        payload = json.loads(out)  # still exactly one JSON document
        assert "GITHUB_STEP_SUMMARY" in payload["error"]
