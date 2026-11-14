"""Tests for ``iterate template`` — bundled template surfacing.

The templates the generator consumes silently (ITERATE.md skeleton, onboarding
playbook, decision-log structure) were unreachable from the CLI: a user who
wanted to know what structure ``iterate onboard`` produces, or to customise a
copy of the skeleton, had to locate the file inside the installed skill
directory by hand. ``iterate template list|show`` makes that surface
discoverable and read-only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iterate_cli.cli import main as cli_main
from iterate_cli.template_cmd import (
    TEMPLATE_REGISTRY,
    list_templates,
    read_template,
    resolve_template,
)


def _run(*args: str) -> int:
    return cli_main(["template", "--no-banner", *args])


class TestRegistry:
    def test_exposes_three_canonical_templates(self) -> None:
        assert set(TEMPLATE_REGISTRY) == {
            "ITERATE.template.md",
            "onboarding-playbook.md",
            "iterate-decisions.template.md",
        }

    def test_resolve_accepts_friendly_aliases(self) -> None:
        assert resolve_template("iterate") == "ITERATE.template.md"
        assert resolve_template("playbook") == "onboarding-playbook.md"
        assert resolve_template("decisions") == "iterate-decisions.template.md"
        assert resolve_template("nope") is None

    def test_every_registered_template_exists_on_disk(self) -> None:
        for item in list_templates():
            assert item["exists"], item["name"]
            assert item["path"].endswith(item["name"])

    def test_read_template_returns_content(self) -> None:
        result = read_template("ITERATE.template.md")
        assert result is not None
        canonical, content, _ = result
        assert canonical == "ITERATE.template.md"
        assert "# ITERATE.md" in content or "ITERATE.md" in content

    def test_read_unknown_returns_none(self) -> None:
        assert read_template("missing.md") is None

    def test_bundled_data_copies_match_repo_templates(self) -> None:
        # A pip wheel ships only iterate_cli/data/ (package-data), never the
        # repo-relative templates/ dir. If the two drift, a source checkout and
        # an installed package show different template content.
        data_dir = Path(__file__).resolve().parent.parent / "iterate_cli" / "data"
        repo_dir = Path(__file__).resolve().parent.parent / "templates"
        for name in TEMPLATE_REGISTRY:
            bundled = data_dir / name
            repo = repo_dir / name
            assert bundled.is_file(), f"{name} is missing from package data"
            assert repo.is_file(), f"{name} is missing from templates/"
            assert bundled.read_bytes() == repo.read_bytes(), name

    def test_list_prefers_bundled_package_data(self) -> None:
        data_dir = (
            Path(__file__).resolve().parent.parent / "iterate_cli" / "data"
        )
        for item in list_templates():
            assert Path(item["path"]).parent == data_dir, item

    def test_missing_known_template_is_an_install_error(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        from iterate_cli import template_cmd

        monkeypatch.setattr(template_cmd, "_TEMPLATE_DIRS", (tmp_path,))
        capsys.readouterr()
        code = template_cmd.run_template("show", "playbook")
        captured = capsys.readouterr()
        assert code == 1
        assert "missing from this installation" in captured.err
        # The fix is a reinstall, not a different template name.
        assert "Reinstall" in captured.out

    def test_missing_known_template_json_is_one_document(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        from iterate_cli import template_cmd

        monkeypatch.setattr(template_cmd, "_TEMPLATE_DIRS", (tmp_path,))
        capsys.readouterr()
        code = template_cmd.run_template("show", "decisions", json_output=True)
        out = capsys.readouterr().out
        assert code == 1
        payload = json.loads(out)
        assert payload["template"] == "iterate-decisions.template.md"
        assert "Reinstall" in payload["hint"]

    def test_missing_template_list_reports_exists_false(
        self, tmp_path, monkeypatch
    ) -> None:
        from iterate_cli import template_cmd

        monkeypatch.setattr(template_cmd, "_TEMPLATE_DIRS", (tmp_path,))
        monkeypatch.setattr(template_cmd, "_PACKAGE_DATA_ROOT", tmp_path)
        items = template_cmd.list_templates()
        assert items
        assert all(not item["exists"] for item in items)


class TestCliTemplate:
    def test_default_action_lists_templates(self, capsys) -> None:
        capsys.readouterr()
        code = _run()
        out = capsys.readouterr().out
        assert code == 0
        assert "ITERATE.template.md" in out
        assert "onboarding-playbook.md" in out
        assert "iterate-decisions.template.md" in out

    def test_list_json_is_single_document(self, capsys) -> None:
        capsys.readouterr()
        code = _run("list", "--json")
        out = capsys.readouterr().out
        assert code == 0
        payload = json.loads(out)
        assert len(payload["templates"]) == 3
        assert all(t["exists"] for t in payload["templates"])

    def test_show_prints_content_verbatim(self, capsys) -> None:
        capsys.readouterr()
        code = _run("show", "ITERATE.template.md")
        out = capsys.readouterr().out
        assert code == 0
        assert out.strip() == (
            read_template("ITERATE.template.md")[1].strip()
        )

    def test_show_accepts_alias(self, capsys) -> None:
        capsys.readouterr()
        code = _run("show", "playbook")
        out = capsys.readouterr().out
        assert code == 0
        assert "Onboarding Playbook" in out

    def test_show_unknown_is_usage_error(self, capsys) -> None:
        capsys.readouterr()
        code = _run("show", "does-not-exist")
        captured = capsys.readouterr()
        assert code == 2
        # tui.error writes to stderr; the guidance hint goes to stdout.
        assert "Unknown template" in captured.err
        assert "template list" in captured.out

    def test_show_unknown_json_carries_hint(self, capsys) -> None:
        capsys.readouterr()
        code = _run("show", "does-not-exist", "--json")
        out = capsys.readouterr().out
        assert code == 2
        payload = json.loads(out)
        assert "does-not-exist" in payload["error"]
        assert "template list" in payload["hint"]

    def test_show_requires_a_name(self, capsys) -> None:
        capsys.readouterr()
        code = _run("show")
        captured = capsys.readouterr()
        assert code == 2
        assert "requires a template name" in captured.err

    def test_unknown_action_is_usage_error(self, capsys) -> None:
        # An unknown sub-action is an argparse choice error (SystemExit 2), the
        # same path a mistyped top-level command takes.
        import pytest

        capsys.readouterr()
        with pytest.raises(SystemExit) as excinfo:
            _run("frobnicate")
        assert excinfo.value.code == 2

    def test_works_outside_a_project(self, tmp_path, capsys) -> None:
        # Template describes the skill, not a project, so it must work from a
        # directory with no iterate state at all.
        capsys.readouterr()
        code = cli_main(["template", "list", "-p", str(tmp_path), "--no-banner"])
        out = capsys.readouterr().out
        assert code == 0
        assert "ITERATE.template.md" in out
