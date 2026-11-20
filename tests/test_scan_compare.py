"""Tests for ``iterate scan --compare`` (config-vs-scan gap analysis).

The scanner already reports what it *would* configure, but users could only
spot a config that had fallen behind the project's tech stack by reading
``scan --json`` and ``show --json`` side by side. ``scan --compare`` turns that
into one read-only report plus the exact commands that close each gap.

Covered here: the pure comparison (normal / missing / unusable / malformed
config), the advisory exit-code contract, JSON stability, CLI wiring,
discoverability, and the guarantee that nothing is written.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iterate_cli.cli import main as cli_main
from iterate_cli.compare import (
    CONFIG_MISSING,
    CONFIG_OK,
    CONFIG_UNUSABLE,
    _merge_dimensions,
    build_comparison,
)
from iterate_cli.scan import collect_scan_data


def _make_frontend_project(root: Path) -> None:
    (root / "package.json").write_text('{"name": "demo"}', encoding="utf-8")
    (root / "src" / "components").mkdir(parents=True)
    (root / "src" / "api").mkdir(parents=True)
    (root / "tests").mkdir()


def _write_config(root: Path, text: str) -> None:
    (root / "iterate.config.yaml").write_text(text, encoding="utf-8")


def _snapshot(root: Path) -> dict[str, float]:
    return {
        str(path.relative_to(root)): path.stat().st_mtime
        for path in sorted(root.rglob("*"))
    }


class TestBuildComparison:
    def test_missing_config_is_reported_not_listed_as_gaps(self, tmp_path: Path) -> None:
        _make_frontend_project(tmp_path)
        report = build_comparison(tmp_path)

        assert report["command"] == "scan --compare"
        assert report["config"]["status"] == CONFIG_MISSING
        assert report["gaps"] == {
            "dimensions": [],
            "dimension_sets": [],
            "validation_modules": [],
        }
        assert report["in_sync"] is False
        assert report["read_only"] is True
        assert report["next"][0] == "iterate init --yes"
        # The suggestions are still carried so a consumer can render a preview.
        assert report["suggested"]["dimensions"]

    def test_unusable_config_points_at_doctor(self, tmp_path: Path) -> None:
        _make_frontend_project(tmp_path)
        _write_config(tmp_path, "dimensions: [unclosed\n")
        report = build_comparison(tmp_path)

        assert report["config"]["status"] == CONFIG_UNUSABLE
        assert report["gaps"]["dimensions"] == []
        assert report["next"] == ["iterate doctor --fix", "iterate doctor"]

    def test_empty_config_file_counts_as_unusable(self, tmp_path: Path) -> None:
        _make_frontend_project(tmp_path)
        _write_config(tmp_path, "")
        report = build_comparison(tmp_path)
        assert report["config"]["status"] == CONFIG_UNUSABLE

    def test_detects_dimensions_sets_and_modules_behind_the_stack(
        self, tmp_path: Path
    ) -> None:
        _make_frontend_project(tmp_path)
        # A config written before the frontend/API layers existed: no ui-ux /
        # frontend-backend dimensions, no frontend set, no typescript commands.
        _write_config(
            tmp_path,
            "dimensions:\n"
            "  - correctness\n"
            "  - security\n"
            "dimension_sets: {}\n"
            "validation:\n"
            "  commands: {}\n",
        )
        report = build_comparison(tmp_path)

        assert report["config"]["status"] == CONFIG_OK
        assert report["config"]["dimensions"] == ["correctness", "security"]
        assert report["in_sync"] is False
        assert "ui-ux" in report["gaps"]["dimensions"]
        assert "frontend-backend" in report["gaps"]["dimensions"]
        assert "frontend" in report["gaps"]["dimension_sets"]
        assert "typescript" in report["gaps"]["validation_modules"]
        # Dimensions need the explicit config set; sets/modules come from refresh.
        assert report["next"] == [
            "iterate config set dimensions "
            + ",".join(["correctness", "security", *report["gaps"]["dimensions"]]),
            "iterate refresh",
        ]

    def test_in_sync_config_has_no_gaps(self, tmp_path: Path) -> None:
        _make_frontend_project(tmp_path)
        scan = collect_scan_data(tmp_path)
        dimensions = scan["suggested_dimensions"]
        sets = scan["suggested_dimension_sets"]
        commands = scan["suggested_validation_commands"]
        lines = ["dimensions:"] + [f"  - {d}" for d in dimensions]
        lines.append("dimension_sets:")
        for name, spec in sets.items():
            lines.append(f"  {name}:")
            lines.append("    dimensions:")
            for dimension in spec["dimensions"]:
                lines.append(f"      - {dimension}")
        lines.append("validation:")
        lines.append("  commands:")
        for module in commands:
            lines.append(f"    {module}:")
            for command in commands[module]:
                lines.append(f"      - {json.dumps(command)}")
        _write_config(tmp_path, "\n".join(lines) + "\n")

        report = build_comparison(tmp_path)

        assert report["config"]["status"] == CONFIG_OK
        assert report["gaps"] == {
            "dimensions": [],
            "dimension_sets": [],
            "validation_modules": [],
        }
        assert report["in_sync"] is True
        assert report["next"] == []

    def test_extra_dimensions_and_customised_sets_are_not_gaps(
        self, tmp_path: Path
    ) -> None:
        _make_frontend_project(tmp_path)
        scan = collect_scan_data(tmp_path)
        # Enable one extra dimension the scan did not suggest, and a fully
        # custom set name: both are deliberate user choices.
        dimensions = [*scan["suggested_dimensions"], "spec-compliance"]
        lines = ["dimensions:"] + [f"  - {d}" for d in dimensions]
        lines.append("dimension_sets:")
        lines.append("  my-team-set:")
        lines.append("    dimensions: [correctness]")
        lines.append("validation:")
        lines.append("  commands:")
        for module in scan["suggested_validation_commands"]:
            lines.append(f"    {module}:")
            for command in scan["suggested_validation_commands"][module]:
                lines.append(f"      - {json.dumps(command)}")
        # Still missing the scan's own named sets, but not reported as extra.
        _write_config(tmp_path, "\n".join(lines) + "\n")
        report = build_comparison(tmp_path)

        assert "spec-compliance" not in report["gaps"]["dimensions"]
        assert "my-team-set" not in report["gaps"]["dimension_sets"]
        assert report["gaps"]["dimension_sets"]  # scan sets still missing

    def test_malformed_shapes_never_crash(self, tmp_path: Path) -> None:
        _make_frontend_project(tmp_path)
        _write_config(
            tmp_path,
            "dimensions: correctness\n"
            "dimension_sets: [frontend]\n"
            "validation: not-a-mapping\n",
        )
        report = build_comparison(tmp_path)

        assert report["config"]["status"] == CONFIG_OK
        assert report["config"]["dimensions"] == []
        assert report["config"]["dimension_sets"] == []
        assert report["config"]["validation_modules"] == []
        assert report["gaps"]["dimensions"]
        assert "iterate config set dimensions " in report["next"][0]

    def test_non_string_entries_are_ignored(self, tmp_path: Path) -> None:
        _make_frontend_project(tmp_path)
        _write_config(
            tmp_path,
            "dimensions: [correctness, 7, null, '']\n"
            "dimension_sets: {}\n",
        )
        report = build_comparison(tmp_path)
        assert report["config"]["dimensions"] == ["correctness"]

    def test_json_payload_is_serialisable(self, tmp_path: Path) -> None:
        _make_frontend_project(tmp_path)
        report = build_comparison(tmp_path)
        # No `default=str` needed: every value is a plain JSON type.
        encoded = json.dumps(report)
        assert json.loads(encoded)["command"] == "scan --compare"

    def test_count_pluralisation(self) -> None:
        from iterate_cli.compare import _count

        assert _count("dimension", 0) == "0 dimensions"
        assert _count("dimension", 1) == "1 dimension"
        assert _count("set", 2) == "2 sets"
        assert _count("validation module", 1) == "1 validation module"

    def test_merge_dimensions_preserves_order_and_deduplicates(self) -> None:
        assert _merge_dimensions(["a", "b"], ["b", "c", "a", "d"]) == [
            "a",
            "b",
            "c",
            "d",
        ]
        assert _merge_dimensions([], ["x"]) == ["x"]


class TestCompareCli:
    def test_json_is_one_document_and_exits_zero(self, tmp_path: Path, capsys) -> None:
        _make_frontend_project(tmp_path)
        capsys.readouterr()
        code = cli_main(
            ["scan", "--compare", "--json", "-p", str(tmp_path), "--no-banner"]
        )
        out = capsys.readouterr().out

        assert code == 0
        payload = json.loads(out)
        assert payload["config"]["status"] == CONFIG_MISSING
        assert payload["read_only"] is True

    def test_tui_lists_gaps_and_next_steps(self, tmp_path: Path, capsys) -> None:
        _make_frontend_project(tmp_path)
        _write_config(
            tmp_path,
            "dimensions: [correctness]\n"
            "dimension_sets: {}\n"
            "validation:\n  commands: {}\n",
        )
        capsys.readouterr()
        code = cli_main(["scan", "--compare", "-p", str(tmp_path), "--no-banner"])
        out = capsys.readouterr().out

        assert code == 0
        assert "Scan vs config" in out
        assert "Suggested dimensions not enabled" in out
        assert "ui-ux" in out
        assert "iterate config set dimensions" in out
        assert "Read-only" in out

    def test_missing_config_tui_points_at_init(self, tmp_path: Path, capsys) -> None:
        _make_frontend_project(tmp_path)
        capsys.readouterr()
        code = cli_main(["scan", "--compare", "-p", str(tmp_path), "--no-banner"])
        captured = capsys.readouterr()

        assert code == 0
        assert "iterate init --yes" in captured.out
        assert "nothing to compare yet" in captured.err

    def test_unusable_config_tui_points_at_doctor(self, tmp_path: Path, capsys) -> None:
        _make_frontend_project(tmp_path)
        _write_config(tmp_path, "- not\n- a\n- mapping\n")
        capsys.readouterr()
        code = cli_main(["scan", "--compare", "-p", str(tmp_path), "--no-banner"])
        captured = capsys.readouterr()

        assert code == 0
        assert "iterate doctor --fix" in captured.out

    def test_compare_is_read_only(self, tmp_path: Path, capsys) -> None:
        _make_frontend_project(tmp_path)
        _write_config(tmp_path, "dimensions: [correctness]\n")
        before = _snapshot(tmp_path)
        capsys.readouterr()
        code = cli_main(["scan", "--compare", "--json", "-p", str(tmp_path)])
        capsys.readouterr()

        assert code == 0
        assert _snapshot(tmp_path) == before

    def test_compare_without_config_does_not_create_one(
        self, tmp_path: Path, capsys
    ) -> None:
        _make_frontend_project(tmp_path)
        capsys.readouterr()
        cli_main(["scan", "--compare", "-p", str(tmp_path), "--no-banner"])
        capsys.readouterr()
        assert not (tmp_path / "iterate.config.yaml").exists()

    def test_compare_is_advisory_even_when_out_of_sync(
        self, tmp_path: Path, capsys
    ) -> None:
        _make_frontend_project(tmp_path)
        _write_config(tmp_path, "dimensions: [correctness]\n")
        capsys.readouterr()
        code = cli_main(["scan", "--compare", "-p", str(tmp_path), "--no-banner"])
        capsys.readouterr()
        assert code == 0

    def test_compare_flag_appears_in_scan_help(self, capsys) -> None:
        capsys.readouterr()
        code = cli_main(["help", "scan"])
        out = capsys.readouterr().out
        assert code == 0
        assert "--compare" in out
        assert "iterate.config.yaml" in out

    def test_plain_scan_does_not_include_comparison(self, tmp_path: Path, capsys) -> None:
        _make_frontend_project(tmp_path)
        capsys.readouterr()
        cli_main(["scan", "--json", "-p", str(tmp_path)])
        payload = json.loads(capsys.readouterr().out)
        assert "gaps" not in payload
        assert payload["suggested_dimensions"]
