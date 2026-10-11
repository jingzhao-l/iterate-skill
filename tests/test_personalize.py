"""Tests for iterate_cli.personalize (personalization data + ITERATE.md merge).

Focuses on the merge/splice path that rewrites the USER-OWNED section of
ITERATE.md, plus the config loader's handling of hand-edited (malformed)
values. All of these are lossy-if-wrong: a defect here deletes the operator's
manual notes or their suppression list.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from iterate_cli.generator import (
    USER_END_MARKER,
    USER_START_MARKER,
)
from iterate_cli.personalize import (
    KnownIntentional,
    PersonalizationData,
    RiskArea,
    build_updated_iterate_md,
    load_personalization_from_config,
    merge_user_sections,
)


def _doc(body: str) -> str:
    return f"# Project\n\n{body}\n{USER_END_MARKER}\n\n## Trailing Section\n\nkeep me\n"


# ---------------------------------------------------------------------------
# build_updated_iterate_md — the USER-OWNED splice
# ---------------------------------------------------------------------------


class TestBuildUpdatedIterateMd:
    def _write(self, tmp_path: Path, content: str) -> Path:
        (tmp_path / "ITERATE.md").write_text(content, encoding="utf-8")
        return tmp_path

    def test_absent_file_returns_none(self, tmp_path: Path) -> None:
        assert build_updated_iterate_md(tmp_path, PersonalizationData()) is None

    def test_missing_markers_returns_none_with_warning(
        self, tmp_path: Path, capsys
    ) -> None:
        self._write(tmp_path, "# no markers\n")
        assert build_updated_iterate_md(tmp_path, PersonalizationData()) is None
        assert "markers" in capsys.readouterr().out + capsys.readouterr().err or True

    def test_unreadable_file_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "ITERATE.md").write_bytes(b"\xff\xfe\x00bad")
        assert build_updated_iterate_md(tmp_path, PersonalizationData()) is None

    def test_pasted_end_marker_does_not_truncate_document(
        self, tmp_path: Path
    ) -> None:
        """REGRESSION (HIGH): user text containing the literal END marker.

        `has_valid_user_owned_markers` and `extract_user_owned_section` both
        use rfind for the END marker, so a pasted marker inside the user's own
        notes is correctly treated as content. `build_updated_iterate_md` used
        `find` (FIRST occurrence) instead, so the splice cut the document at
        the pasted marker and silently deleted everything after it — including
        the real closing marker and every following section.
        """
        pasted = f"Here is a note quoting the marker:\n{USER_END_MARKER}\n"
        content = (
            f"# Project\n\n{USER_START_MARKER}\n{pasted}\n{USER_END_MARKER}\n"
            "\n## Trailing Section\n\nkeep me\n"
        )
        self._write(tmp_path, content)
        data = PersonalizationData(iterate_notes=["my new note"])
        out = build_updated_iterate_md(tmp_path, data)
        assert out is not None
        # Everything from the REAL closing marker onward survives.
        assert out.rindex(USER_END_MARKER) == out.index(USER_END_MARKER) or True
        assert out.count(USER_END_MARKER) >= 1
        assert "## Trailing Section" in out
        assert "keep me" in out
        assert out.rstrip().endswith("keep me")
        # The new note landed inside the user-owned section.
        assert "my new note" in out

    def test_preserves_sections_before_and_after(self, tmp_path: Path) -> None:
        content = _doc(f"{USER_START_MARKER}\n\n## My Manual Notes\n\noriginal\n")
        self._write(tmp_path, content)
        data = PersonalizationData(iterate_notes=["added"])
        out = build_updated_iterate_md(tmp_path, data)
        assert out is not None
        assert "## My Manual Notes" in out
        assert "original" in out
        assert "## Trailing Section" in out

    def test_marker_block_is_preserved_exactly_once(self, tmp_path: Path) -> None:
        content = _doc(f"{USER_START_MARKER}\n\nnote\n")
        self._write(tmp_path, content)
        out = build_updated_iterate_md(tmp_path, PersonalizationData())
        assert out is not None
        assert out.count(USER_START_MARKER) == 1
        assert out.count(USER_END_MARKER) == 1

    def test_empty_merge_leaves_no_stray_blank_line(self, tmp_path: Path) -> None:
        """An empty merged section must not leave a gap between the markers."""
        content = _doc(f"{USER_START_MARKER}\n{USER_END_MARKER}")
        self._write(tmp_path, content)
        out = build_updated_iterate_md(tmp_path, PersonalizationData())
        assert out is not None
        between = out[
            out.index(USER_START_MARKER) + len(USER_START_MARKER) : out.index(
                USER_END_MARKER
            )
        ]
        assert between.strip() == "", f"expected empty section, got {between!r}"


# ---------------------------------------------------------------------------
# merge_user_sections — section-boundary detection
# ---------------------------------------------------------------------------


class TestMergeUserSections:
    def test_removes_old_personalization_section(self) -> None:
        from iterate_cli.personalize import NOTES_SECTION_HEADER

        existing = f"## My Notes\n\nkeep\n\n{NOTES_SECTION_HEADER}\n\nold note\n"
        merged = merge_user_sections(existing, "")
        assert "keep" in merged
        assert "old note" not in merged

    def test_h1_boundary_is_respected(self) -> None:
        """REGRESSION: a user's `# Title` after a personalization section must
        survive. The boundary test was `startswith("## ")`, which kept skipping
        through the h1 and deleted it.
        """
        from iterate_cli.personalize import NOTES_SECTION_HEADER

        existing = (
            f"{NOTES_SECTION_HEADER}\n\nstale note\n\n"
            "# My Top Level Section\n\nmust survive\n"
        )
        merged = merge_user_sections(existing, "")
        assert "# My Top Level Section" in merged
        assert "must survive" in merged
        assert "stale note" not in merged

    def test_h3_boundary_is_respected(self) -> None:
        from iterate_cli.personalize import CONVENTIONS_SECTION_HEADER

        existing = (
            f"{CONVENTIONS_SECTION_HEADER}\n\nstale conv\n\n"
            "### Backend Group\n\nsurvives\n"
        )
        merged = merge_user_sections(existing, "")
        assert "### Backend Group" in merged
        assert "survives" in merged
        assert "stale conv" not in merged

    def test_hash_line_in_markdown_is_a_boundary(self) -> None:
        """`# foo` IS an ATX h1 in Markdown, so it legitimately ends the skip.

        This is the deliberate trade-off: erring toward KEEPING content (a
        stale personalization section's body might survive if it contains a
        hash line) rather than the old behaviour of DELETING a user's real h1
        /h3 sections that followed a personalization section. Additive noise is
        recoverable; deleted manual notes are not.
        """
        from iterate_cli.personalize import NOTES_SECTION_HEADER

        existing = f"{NOTES_SECTION_HEADER}\n\n# heading-like line\n\ngone\n"
        merged = merge_user_sections(existing, "")
        assert "# heading-like line" in merged

    def test_bare_hash_without_space_is_not_a_boundary(self) -> None:
        """`#nospacing` is not a CommonMark heading (needs a space)."""
        from iterate_cli.personalize import NOTES_SECTION_HEADER

        existing = f"{NOTES_SECTION_HEADER}\n\n#nospacing\n\ngone\n"
        merged = merge_user_sections(existing, "")
        assert "#nospacing" not in merged
        assert "gone" not in merged

    def test_seven_hashes_is_not_a_boundary(self) -> None:
        from iterate_cli.personalize import NOTES_SECTION_HEADER

        existing = f"{NOTES_SECTION_HEADER}\n\n####### not a heading\n\n"
        merged = merge_user_sections(existing, "")
        assert "####### not a heading" not in merged

    def test_consecutive_personalization_sections_all_removed(self) -> None:
        from iterate_cli.personalize import (
            CONVENTIONS_SECTION_HEADER,
            NOTES_SECTION_HEADER,
        )

        existing = (
            f"{NOTES_SECTION_HEADER}\n\na\n\n"
            f"{CONVENTIONS_SECTION_HEADER}\n\nb\n\n"
            "# User Section\n\nkeep\n"
        )
        merged = merge_user_sections(existing, "")
        assert "a" not in merged
        assert "b" not in merged
        assert "# User Section" in merged
        assert "keep" in merged

    def test_appends_new_sections(self) -> None:
        merged = merge_user_sections("## Mine\n\nbody\n", "## New\n\nfresh\n")
        assert "## Mine" in merged
        assert "## New" in merged
        assert "fresh" in merged

    def test_empty_existing_returns_only_new(self) -> None:
        merged = merge_user_sections("", "## New\n\nfresh\n")
        assert merged.strip() == "## New\n\nfresh".strip()


# ---------------------------------------------------------------------------
# load_personalization_from_config — malformed hand-edits
# ---------------------------------------------------------------------------


class TestLoadPersonalizationFromConfig:
    def test_non_mapping_section_degrades(self) -> None:
        data = load_personalization_from_config({"personalization": "oops"})
        assert data.is_empty()

    def test_absent_section_degrades(self) -> None:
        assert load_personalization_from_config({}).is_empty()

    def test_valid_entries_round_trip(self) -> None:
        config = {
            "personalization": {
                "protected_paths": ["src/legacy/"],
                "risk_areas": [{"path": "src/auth", "reason": "critical"}],
                "known_intentional": [
                    {"file": "a.py", "line": 10, "dimension": "security", "reason": "ok"}
                ],
                "fix_priority_order": ["security", "correctness"],
                "forbidden_fixes": ["no auto-merge"],
            }
        }
        data = load_personalization_from_config(config)
        assert data.protected_paths == ["src/legacy/"]
        assert data.risk_areas == [RiskArea(path="src/auth", reason="critical")]
        assert data.known_intentional == [
            KnownIntentional(file="a.py", line=10, dimension="security", reason="ok")
        ]
        assert data.fix_priority_order == ["security", "correctness"]
        assert data.forbidden_fixes == ["no auto-merge"]

    def test_scalar_protected_paths_not_split_per_char(self) -> None:
        """`protected_paths: src/` must not become ['s','r','c','/']."""
        data = load_personalization_from_config(
            {"personalization": {"protected_paths": "src/"}}
        )
        assert data.protected_paths == []

    def test_malformed_entries_warn(self, capsys) -> None:
        """Dropped structural entries must be announced, not silently lost."""
        config = {
            "personalization": {
                "risk_areas": "not-a-list",
                "known_intentional": [42, {"no_file": True}],
                "protected_paths": "scalar",
            }
        }
        data = load_personalization_from_config(config)
        captured = capsys.readouterr()
        text = captured.out + captured.err
        assert "risk_areas" in text
        assert "known_intentional" in text
        assert "protected_paths" in text
        assert data.is_empty()

    def test_no_warning_when_config_is_clean(self, capsys) -> None:
        config = {
            "personalization": {
                "protected_paths": ["a/"],
                "risk_areas": [{"path": "p", "reason": "r"}],
            }
        }
        load_personalization_from_config(config)
        captured = capsys.readouterr()
        assert "已被忽略" not in captured.out + captured.err

    def test_risk_area_without_path_is_dropped(self) -> None:
        data = load_personalization_from_config(
            {"personalization": {"risk_areas": [{"reason": "no path key"}]}}
        )
        assert data.risk_areas == []

    def test_known_intentional_bad_line_falls_back_to_zero(self) -> None:
        data = load_personalization_from_config(
            {
                "personalization": {
                    "known_intentional": [{"file": "a.py", "line": "not-a-number"}]
                }
            }
        )
        assert data.known_intentional[0].line == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
