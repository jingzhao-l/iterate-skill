"""Tests for GitHub Actions annotation output (iterate_cli.annotate).

Covers the escaping rules (message vs property), the render shape with and
without file/line anchors, the emit helper (stderr default, return count), the
finding→annotation mapping (severity mapping, ITERATE.md vs config file anchor,
passing findings skipped) and the ``--annotate``/``--no-annotate``/auto
decision logic.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

# CI runs `pytest tests/ -q` (not `python -m pytest`), so the repo root is not
# on sys.path and `import iterate_cli` would fail at collection. Same pattern
# as every other test module in this suite.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iterate_cli.annotate import (
    Annotation,
    annotations_from_findings,
    emit,
    enabled_from_args,
    escape_message,
    escape_property,
    render,
)
from iterate_cli.cli import main as cli_main

# ---------------------------------------------------------------------------
# Escaping
# ---------------------------------------------------------------------------

def test_escape_message_percent_cr_lf() -> None:
    # % first, then CR/LF; a literal "%25" round-trips as "%2525" (decoded once).
    assert escape_message("100% done") == "100%25 done"
    assert escape_message("a%25b") == "a%2525b"
    assert escape_message("line1\r\nline2") == "line1%0D%0Aline2"
    assert escape_message("") == ""


def test_escape_message_leaves_other_tokens_alone() -> None:
    # A message that already contains a valid %XX token must not be mangled into
    # a different token; escaping only % , CR and LF keeps the rest literal.
    assert escape_message(":error::") == ":error::"
    assert escape_message("file=iterate.config.yaml") == "file=iterate.config.yaml"


def test_escape_property_adds_colon_and_comma() -> None:
    # Properties delimit on : and , so those must be escaped on top of message.
    assert escape_property("a:b") == "a%3Ab"
    assert escape_property("a,b") == "a%2Cb"
    assert escape_property("100%") == "100%25"


def test_escape_property_also_escapes_newlines() -> None:
    assert escape_property("line1\nline2") == "line1%0Aline2"


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def test_render_minimal() -> None:
    assert render(Annotation("warning", "drift detected")) == (
        "::warning::drift detected"
    )


def test_render_with_file_only() -> None:
    assert render(Annotation("error", "bad config", file="iterate.config.yaml")) == (
        "::error file=iterate.config.yaml::bad config"
    )


def test_render_with_file_and_line() -> None:
    assert render(
        Annotation("notice", "hi", file="ITERATE.md", line=12)
    ) == "::notice file=ITERATE.md,line=12::hi"


def test_render_escapes_message_and_properties() -> None:
    # A finding whose message contains % and a file path containing a comma.
    assert render(
        Annotation("error", "100% broken\nsee docs", file="a,b/iterate.config.yaml")
    ) == "::error file=a%2Cb/iterate.config.yaml::100%25 broken%0Asee docs"


def test_render_rejects_unknown_severity() -> None:
    try:
        Annotation("fatal", "boom")
    except ValueError as exc:
        assert "severity" in str(exc)
    else:  # pragma: no cover - the constructor must raise
        raise AssertionError("Annotation accepted an invalid severity")


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------

def test_emit_writes_one_line_per_annotation_and_counts() -> None:
    buf = io.StringIO()
    count = emit(
        [
            Annotation("error", "one"),
            Annotation("warning", "two"),
        ],
        stream=buf,
    )
    assert count == 2
    assert buf.getvalue() == "::error::one\n::warning::two\n"


def test_emit_defaults_to_stderr(monkeypatch) -> None:
    # emit() must not pollute stdout (doctor/report own it for the document).
    captured = io.StringIO()
    monkeypatch.setattr(sys, "stderr", captured)
    emit([Annotation("error", "no stdout pollution")])
    assert captured.getvalue() == "::error::no stdout pollution\n"


def test_emit_empty() -> None:
    buf = io.StringIO()
    assert emit([], stream=buf) == 0
    assert buf.getvalue() == ""


# ---------------------------------------------------------------------------
# Finding → annotation mapping
# ---------------------------------------------------------------------------

def _finding(severity: str, check: str, message: str) -> dict:
    return {"severity": severity, "check": check, "message": message}


def test_annotations_from_findings_skips_ok() -> None:
    findings = [_finding("ok", "dimensions", "dimensions look good")]
    assert annotations_from_findings(findings) == []


def test_annotations_from_findings_maps_severities() -> None:
    annotations = annotations_from_findings(
        [
            _finding("error", "config.schema", "schema violation"),
            _finding("warn", "drift", "stack changed"),
        ]
    )
    assert [a.severity for a in annotations] == ["error", "warning"]
    assert [a.message for a in annotations] == ["schema violation", "stack changed"]


def test_annotations_anchor_iterate_md_checks_to_iterate_md() -> None:
    annotations = annotations_from_findings(
        [_finding("error", "iterate.md.markers", "markers missing")]
    )
    assert annotations[0].file == "ITERATE.md"


def test_annotations_anchor_config_checks_to_config() -> None:
    annotations = annotations_from_findings(
        [_finding("error", "config.parse", "unparseable")]
    )
    assert annotations[0].file == "iterate.config.yaml"


def test_annotations_accept_doctorfinding_objects() -> None:
    # The real doctor path passes DoctorFinding instances, not dicts.
    from iterate_cli.doctor import DoctorFinding

    annotations = annotations_from_findings(
        [DoctorFinding("error", "config.parse", "unparseable", "detail")]
    )
    assert len(annotations) == 1
    assert annotations[0].severity == "error"
    assert annotations[0].message == "unparseable"
    assert annotations[0].file == "iterate.config.yaml"


def test_annotations_handles_unknown_severity_and_empty_message() -> None:
    # A defensive pass: an unexpected severity must not crash the annotate step
    # (it would otherwise take down a CI run), and an empty message degrades to
    # a stable placeholder instead of a bare "::error::".
    annotations = annotations_from_findings(
        [{"severity": "something-new", "check": "x", "message": "hi"}]
    )
    assert annotations == []
    annotations = annotations_from_findings(
        [_finding("error", "config.parse", "   ")]
    )
    assert annotations[0].message == "iterate diagnostic finding"


# ---------------------------------------------------------------------------
# Enable decision
# ---------------------------------------------------------------------------

def test_enabled_from_args_explicit_flags_win(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert enabled_from_args(True) is True
    assert enabled_from_args(False) is False


def test_enabled_from_args_auto_detects_github_actions(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert enabled_from_args(None) is True
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert enabled_from_args(None) is False
    monkeypatch.setenv("GITHUB_ACTIONS", "True")
    assert enabled_from_args(None) is True
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    assert enabled_from_args(None) is False


# ---------------------------------------------------------------------------
# CLI integration — doctor --annotate / --no-annotate / auto-detect
# ---------------------------------------------------------------------------


class TestAnnotateCLI:
    """Wire the annotate flags through ``iterate doctor`` end to end.

    An empty project dir is deliberately used: ``doctor`` on it reports the
    onboarding failure, which is a stable ``error`` finding mapped to
    ``ITERATE.md`` — so every assertion below is deterministic.
    """

    def test_doctor_annotate_emits_annotation_to_stderr(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        code = cli_main(["doctor", "-p", str(tmp_path), "--annotate"])
        captured = capsys.readouterr()
        assert code == 1
        assert "::error file=ITERATE.md::" in captured.err
        # stdout is the TUI report, not the annotation stream.
        assert "::error" not in captured.out

    def test_doctor_auto_annotates_under_github_actions(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        code = cli_main(["doctor", "-p", str(tmp_path)])
        captured = capsys.readouterr()
        assert code == 1
        assert "::error" in captured.err

    def test_doctor_no_annotate_suppresses_even_in_ci(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        code = cli_main(["doctor", "-p", str(tmp_path), "--no-annotate"])
        captured = capsys.readouterr()
        assert code == 1
        assert "::error" not in captured.err

    def test_doctor_annotate_keeps_json_stdout_clean(
        self, tmp_path, capsys, monkeypatch
    ) -> None:
        # The --json contract ("stdout holds exactly one JSON document") must
        # survive annotations: the document is the only thing on stdout.
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        code = cli_main(["doctor", "-p", str(tmp_path), "--annotate", "--json"])
        captured = capsys.readouterr()
        assert code == 1
        assert "::error" in captured.err
        data = json.loads(captured.out)
        assert data["healthy"] is False

    def test_annotate_and_no_annotate_are_mutually_exclusive(self, tmp_path) -> None:
        with pytest.raises(SystemExit) as exc:
            cli_main(
                ["doctor", "-p", str(tmp_path), "--annotate", "--no-annotate"]
            )
        assert exc.value.code == 2
