"""Tests for ``iterate scan`` — the read-only tech-stack scan export.

The scanner itself (``iterate_cli.scan.scan_project``) is exercised indirectly
by the wizard and refresh suites; this file covers the surface added on top of
it: :func:`collect_scan_data` (the structured report), :func:`render_scan` (TUI
and ``--json`` rendering) and the ``iterate scan`` CLI wiring.

Three properties matter enough to assert explicitly:

* **Read-only.** ``scan`` must never create or modify a file, because it is
  advertised as safe to run on any project (and from CI).
* **Always exit 0.** The scan asserts only what *exists*; a project that
  matches nothing recognisable is a normal outcome, not a failure. A CI caller
  using ``--json`` must not have to special-case the exit code.
* **JSON keys keep the scanner's own field names**, so the report and
  ``ScanResult`` can never drift into disagreeing about which flag means what.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iterate_cli.cli import main as cli_main
from iterate_cli.scan import collect_scan_data, render_scan

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_python_project(root: Path) -> Path:
    """A recognisable Python project: manifest, tests, CI, no frontend."""
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "iterate_cli").mkdir()
    (root / ".github" / "workflows").mkdir(parents=True)
    return root


def _snapshot(root: Path) -> dict[str, float]:
    """Map of relative path → mtime for every entry under ``root``."""
    return {
        str(p.relative_to(root)): p.stat().st_mtime
        for p in sorted(root.rglob("*"))
    }


# ---------------------------------------------------------------------------
# collect_scan_data
# ---------------------------------------------------------------------------


class TestCollectScanData:
    def test_python_project_reports_language_and_commands(self, tmp_path: Path) -> None:
        _make_python_project(tmp_path)
        data = collect_scan_data(tmp_path)

        assert data["project"] == str(tmp_path)
        assert "pyproject.toml" in data["manifests"]
        assert data["detected_languages"] == ["Python"]
        assert data["detected_package_managers"] == ["pip/poetry"]
        assert data["has_tests"] is True
        assert data["has_ci"] is True
        assert data["has_frontend"] is False
        assert "python" in data["suggested_validation_commands"]
        assert data["suggested_validation_commands"]["python"]

    def test_feature_keys_mirror_scan_result_field_names(self, tmp_path: Path) -> None:
        """The four ``has_*`` keys must be spelled exactly as ScanResult's."""
        from dataclasses import fields

        from iterate_cli.scan import ScanResult

        data = collect_scan_data(tmp_path)
        for f in fields(ScanResult):
            if f.name.startswith("has_"):
                assert f.name in data, f"{f.name} missing from the scan report"

    def test_empty_directory_is_all_empty_not_an_error(self, tmp_path: Path) -> None:
        data = collect_scan_data(tmp_path)

        assert data["manifests"] == []
        assert data["detected_languages"] == []
        assert data["detected_package_managers"] == []
        assert data["has_specs"] is False
        assert data["has_tests"] is False
        assert data["has_ci"] is False
        assert data["has_frontend"] is False
        assert data["suggested_validation_commands"] == {}

    def test_frontend_dirs_flip_the_flag_and_add_dimensions(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        (tmp_path / "src" / "components").mkdir(parents=True)
        data = collect_scan_data(tmp_path)

        assert data["has_frontend"] is True
        assert "ui-ux" in data["suggested_dimensions"]
        assert "frontend-backend" in data["suggested_dimensions"]

    def test_json_serialisable_without_default_str(self, tmp_path: Path) -> None:
        """The payload must be plain JSON without an encoder crutch."""
        _make_python_project(tmp_path)
        data = collect_scan_data(tmp_path)
        json.dumps(data)  # raises TypeError if a Path/int-keyed map sneaks in

    def test_repeated_calls_are_stable_and_never_write(self, tmp_path: Path) -> None:
        _make_python_project(tmp_path)
        before = _snapshot(tmp_path)
        first = collect_scan_data(tmp_path)
        second = collect_scan_data(tmp_path)

        assert first == second
        assert _snapshot(tmp_path) == before


# ---------------------------------------------------------------------------
# render_scan
# ---------------------------------------------------------------------------


class TestRenderScan:
    def test_json_mode_prints_one_document_and_returns_0(
        self, tmp_path: Path, capsys
    ) -> None:
        _make_python_project(tmp_path)
        capsys.readouterr()
        code = render_scan(collect_scan_data(tmp_path), json_output=True)

        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["detected_languages"] == ["Python"]

    def test_tui_mode_returns_0_and_mentions_read_only(
        self, tmp_path: Path, capsys
    ) -> None:
        _make_python_project(tmp_path)
        capsys.readouterr()
        code = render_scan(collect_scan_data(tmp_path))

        out = capsys.readouterr().out
        assert code == 0
        assert "Iterate Skill — Scan" in out
        assert "Read-only" in out
        assert "iterate scan --json" in out

    def test_tui_mode_marks_absent_lists_explicitly(
        self, tmp_path: Path, capsys
    ) -> None:
        """An empty right-hand side reads like a rendering bug, not "nothing
        found", so the empty case has its own marker."""
        capsys.readouterr()
        code = render_scan(collect_scan_data(tmp_path))

        out = capsys.readouterr().out
        assert code == 0
        assert "(none detected)" in out

    def test_tui_warns_when_nothing_was_recognised(self, tmp_path: Path, capsys) -> None:
        capsys.readouterr()
        render_scan(collect_scan_data(tmp_path))
        captured = capsys.readouterr()

        assert "No recognised tech-stack manifest" in captured.err

    def test_tui_does_not_warn_for_a_recognised_project(
        self, tmp_path: Path, capsys
    ) -> None:
        _make_python_project(tmp_path)
        capsys.readouterr()
        render_scan(collect_scan_data(tmp_path))

        assert "No recognised tech-stack manifest" not in capsys.readouterr().err

    def test_rendered_output_contains_no_ansi_when_not_a_tty(
        self, tmp_path: Path, capsys
    ) -> None:
        """The report must survive being piped into a file/PR body."""
        _make_python_project(tmp_path)
        capsys.readouterr()
        render_scan(collect_scan_data(tmp_path))

        assert "\x1b[" not in capsys.readouterr().out

    def test_missing_keys_do_not_crash_the_renderer(self, capsys) -> None:
        """render_scan is given a plain dict by callers/tests; absent optional
        keys must degrade instead of raising KeyError."""
        capsys.readouterr()
        assert render_scan({}) == 0
        assert "Iterate Skill — Scan" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


class TestScanCli:
    def test_scan_json_from_the_cli(self, tmp_path: Path, capsys) -> None:
        _make_python_project(tmp_path)
        capsys.readouterr()
        code = cli_main(["scan", "--json", "-p", str(tmp_path), "--no-banner"])

        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["project"] == str(tmp_path)
        assert payload["detected_languages"] == ["Python"]

    def test_scan_tui_from_the_cli(self, tmp_path: Path, capsys) -> None:
        _make_python_project(tmp_path)
        capsys.readouterr()
        code = cli_main(["scan", "-p", str(tmp_path), "--no-banner"])

        assert code == 0
        assert "Iterate Skill — Scan" in capsys.readouterr().out

    def test_scan_exits_0_on_an_empty_project(self, tmp_path: Path, capsys) -> None:
        capsys.readouterr()
        assert cli_main(["scan", "--json", "-p", str(tmp_path), "--no-banner"]) == 0

    def test_scan_missing_project_dir_is_still_an_error(
        self, tmp_path: Path, capsys
    ) -> None:
        """Non-gating applies to *what was found*, not to a nonexistent path."""
        missing = tmp_path / "nope"
        capsys.readouterr()
        code = cli_main(["scan", "--json", "-p", str(missing), "--no-banner"])

        assert code == 1
        assert "project directory not found" in json.loads(capsys.readouterr().out)["error"]

    def test_scan_never_writes_to_the_project(self, tmp_path: Path, capsys) -> None:
        _make_python_project(tmp_path)
        before = _snapshot(tmp_path)
        capsys.readouterr()
        cli_main(["scan", "-p", str(tmp_path), "--no-banner"])
        capsys.readouterr()

        assert _snapshot(tmp_path) == before

    def test_scan_is_not_treated_as_an_interactive_command(
        self, tmp_path: Path, capsys
    ) -> None:
        capsys.readouterr()
        code = cli_main(["scan", "--json", "-p", str(tmp_path), "--no-banner"])

        assert code == 0, "--json must be accepted on scan, not rejected as interactive"

    def test_scan_accepts_project_flag_after_the_subcommand(
        self, tmp_path: Path, capsys
    ) -> None:
        _make_python_project(tmp_path)
        capsys.readouterr()
        code = cli_main(["scan", "-p", str(tmp_path), "--no-banner"])

        assert code == 0


# ---------------------------------------------------------------------------
# Help / discoverability
# ---------------------------------------------------------------------------


class TestScanIsDiscoverable:
    def _help_text(self) -> str:
        from iterate_cli.cli import _build_parser

        return _build_parser().format_help()

    def test_scan_appears_in_the_top_level_help(self) -> None:
        assert "scan" in self._help_text()

    def test_scan_help_mentions_it_is_read_only(self) -> None:
        from iterate_cli.cli import _build_parser

        parser = _build_parser()
        subcommands = next(
            a for a in parser._actions if hasattr(a, "choices") and a.choices
        )
        scan_help = subcommands.choices["scan"].format_help()

        assert "Read-only" in scan_help or "read-only" in scan_help
        assert "--json" in scan_help

    def test_json_help_lists_scan(self) -> None:
        from iterate_cli.cli import _build_parser

        parser = _build_parser()
        json_help = next(
            action.help
            for action in parser._actions
            if "--json" in getattr(action, "option_strings", [])
        )
        assert "scan" in (json_help or "")

    def test_iterate_help_scan_prints_the_subcommand_help(self, capsys) -> None:
        capsys.readouterr()
        code = cli_main(["help", "scan"])

        out = capsys.readouterr().out
        assert code == 0
        assert "usage: iterate scan" in out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
