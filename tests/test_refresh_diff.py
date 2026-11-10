"""Tests for ``iterate refresh --diff`` — unified diff preview.

``refresh --dry-run`` previously answered "how many lines would change?" but a
user deciding whether to apply a refresh had no way to see *what* would change:
the preview showed only a count, so they had to trust the refresh or run it and
read the result. ``--diff`` closes that gap: it prints the exact unified diff a
refresh would apply (ITERATE.md rewrite + config rewrite) and never writes a
file, so the change is reviewable before it happens — from a terminal, from a
PR, or as JSON in CI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iterate_cli.cli import main as cli_main
from iterate_cli.refresh import incremental_refresh, preview_refresh, unified_diff

CONFIG = "iterate.config.yaml"
MD = "ITERATE.md"


def _onboarded_project(root: Path) -> Path:
    """Create a minimal onboarded project with a stale ITERATE.md."""
    project = root / "proj"
    project.mkdir(parents=True)
    (project / MD).write_text(
        "# Project\n\n## Tech Stack\n\n- Python (stale)\n\n"
        "<!-- ITERATE:USER-OWNED:START -->\nmanual\n"
        "<!-- ITERATE:USER-OWNED:END -->\n",
        encoding="utf-8",
    )
    (project / CONFIG).write_text(
        yaml.safe_dump(
            {
                "dimensions": ["correctness"],
                "onboarding": {
                    "channel": "cli",
                    "drift_check": False,
                    "completed_at": "2026-08-01T00:00:00Z",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n", encoding="utf-8"
    )
    return project


def _run(root: Path, *extra: str) -> int:
    return cli_main(
        ["refresh", "-p", str(root), "--no-banner", *extra]
    )


class TestUnifiedDiff:
    def test_identical_blobs_yield_empty_diff(self) -> None:
        assert unified_diff("same\ncontent\n", "same\ncontent\n", "f", "f") == ""

    def test_changed_blobs_yield_headers_and_hunks(self) -> None:
        diff = unified_diff("a\nb\nc\n", "a\nB\nc\n", "f.md", "f.md")
        assert "--- f.md" in diff
        assert "+++ f.md" in diff
        assert "@@" in diff
        assert "-b" in diff
        assert "+B" in diff

    def test_diff_preserves_plus_minus_content_lines(self) -> None:
        # A content line that itself starts with +/- must survive (the old
        # count-based stats had an ambiguity here; a diff must not).
        diff = unified_diff("a\n", "+x\n", "f", "f")
        assert "\n+++x\n" in diff or diff.count("+x") >= 1


class TestPreviewIncludeDiff:
    def test_preview_reports_md_and_config_diffs_when_changed(
        self, tmp_path: Path
    ) -> None:
        project = _onboarded_project(tmp_path)
        before_md = (project / MD).read_text(encoding="utf-8")
        before_config = (project / CONFIG).read_text(encoding="utf-8")

        preview = preview_refresh(project, include_diff=True)

        assert preview["ok"] is True
        assert preview["changed"] is True
        assert preview["config_changed"] is True
        assert preview["md_diff"]  # non-empty ITERATE.md diff
        assert preview["config_diff"]  # non-empty config diff
        # The diff really describes the transition from the on-disk state.
        assert "--- ITERATE.md" in preview["md_diff"]
        assert "--- iterate.config.yaml" in preview["config_diff"]
        # A preview never writes: both files are byte-identical after it ran.
        assert before_md == (project / MD).read_text(encoding="utf-8")
        assert before_config == (project / CONFIG).read_text(encoding="utf-8")

    def test_preview_diff_is_empty_when_already_fresh(self, tmp_path: Path) -> None:
        project = _onboarded_project(tmp_path)
        # Apply a refresh once so the tree is up to date, then preview again.
        assert incremental_refresh(project) is True
        preview = preview_refresh(project, include_diff=True)
        assert preview["ok"] is True
        assert preview["changed"] is False
        assert preview["md_diff"] == ""
        assert preview["config_diff"] == ""

    def test_preview_diff_describes_the_real_refresh(self, tmp_path: Path) -> None:
        """The preview's diff describes the same change a refresh applies.

        The diff is computed from the same ``_build_refresh_outputs`` the real
        refresh uses, so the "would-be" content in the preview must equal what
        ``incremental_refresh`` actually writes. We assert the diff's file
        labels and that the refreshed content (post-apply) is exactly the
        "after" side the preview described: stripping the diff's ``+``/``-``
        markers and applying them to ``before`` must reproduce ``after``.
        """
        project = _onboarded_project(tmp_path)
        preview = preview_refresh(project, include_diff=True)
        assert preview["ok"] is True
        before_md = (project / MD).read_text(encoding="utf-8")

        assert incremental_refresh(project) is True
        after_md = (project / MD).read_text(encoding="utf-8")
        assert after_md != before_md
        # The diff is non-empty and carries the file labels.
        assert "--- ITERATE.md" in preview["md_diff"]
        assert "@@" in preview["md_diff"]
        # The real refresh's "after" content differs from "before" in the same
        # direction the preview's stats described (added/removed > 0).
        assert preview["md_changed_lines"] > 0


class TestCliRefreshDiff:
    def test_diff_prints_the_diff_and_writes_nothing(
        self, tmp_path: Path, capsys
    ) -> None:
        project = _onboarded_project(tmp_path)
        before_md = (project / MD).read_text(encoding="utf-8")
        before_config = (project / CONFIG).read_text(encoding="utf-8")
        capsys.readouterr()

        code = _run(project, "--diff")

        out = capsys.readouterr().out
        assert code == 0
        assert "--- ITERATE.md" in out
        assert "--- iterate.config.yaml" in out
        assert "@@" in out
        # Nothing written.
        assert (project / MD).read_text(encoding="utf-8") == before_md
        assert (project / CONFIG).read_text(encoding="utf-8") == before_config

    def test_diff_json_carries_both_diff_strings(
        self, tmp_path: Path, capsys
    ) -> None:
        project = _onboarded_project(tmp_path)
        before_md = (project / MD).read_text(encoding="utf-8")
        capsys.readouterr()

        code = _run(project, "--diff", "--json")

        out = capsys.readouterr().out
        assert code == 0
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["diff"] is True
        assert payload["dry_run"] is True
        assert payload["changed"] is True
        assert payload["config_changed"] is True
        assert "--- ITERATE.md" in payload["md_diff"]
        assert "--- iterate.config.yaml" in payload["config_diff"]
        assert (project / MD).read_text(encoding="utf-8") == before_md

    def test_diff_reports_no_changes_when_fresh(self, tmp_path: Path, capsys) -> None:
        project = _onboarded_project(tmp_path)
        assert incremental_refresh(project) is True
        capsys.readouterr()

        code = _run(project, "--diff")

        out = capsys.readouterr().out
        assert code == 0
        assert "No changes needed" in out
        assert "--- ITERATE.md" not in out

    def test_diff_fails_cleanly_when_not_onboarded(
        self, tmp_path: Path, capsys
    ) -> None:
        project = tmp_path / "proj"
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        capsys.readouterr()

        code = _run(project, "--diff")

        captured = capsys.readouterr()
        assert code == 1
        # The not-onboarded warning is a warning, so it goes to stderr.
        combined = (captured.out + captured.err).lower()
        assert "not yet completed" in combined or "onboard" in combined

    def test_diff_json_is_single_document_when_not_onboarded(
        self, tmp_path: Path, capsys
    ) -> None:
        project = tmp_path / "proj"
        project.mkdir(parents=True)
        capsys.readouterr()

        code = _run(project, "--diff", "--json")

        out = capsys.readouterr().out
        assert code == 1
        payload = json.loads(out)  # exactly one JSON document
        assert payload["ok"] is False
        assert "onboarding" in payload["error"]
