"""Tests for scripts/publish_qoder.py.

Covers the dependencies/self-containment section idempotency marker: a marker
appended to a staged SKILL.md must be detected verbatim on a later build, so it
is never appended twice when the same annotated file is reused (``--source``).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

import publish_qoder


class TestAppendDependenciesIdempotent:
    def test_marker_written_verbatim_matches_guard(self, tmp_path: Path) -> None:
        """The appended marker must equal the guard marker character-for-character.

        Regression: the section wrote ``_DEP_MARKER`` through a pair of str
        ``replace()`` calls that produced a *two-space* ``<!-- QODER:DEPENDENCIES
         -->``, while the guard ``if _DEP_MARKER in text`` checked the *one-space*
        form. Reusing the annotated SKILL.md then never detected the marker and
        appended a duplicate section on every build.
        """
        skill = tmp_path / "SKILL.md"
        skill.write_text("# Iterate\n", encoding="utf-8")

        first = publish_qoder._append_dependencies_section(str(skill))
        assert first  # appended once

        after_one = skill.read_text(encoding="utf-8")
        # The marker is present in its canonical, single-space form.
        assert publish_qoder._DEP_MARKER in after_one
        # Only one occurrence of the marker (no duplicate section yet).
        assert after_one.count(publish_qoder._DEP_MARKER) == 1

        second = publish_qoder._append_dependencies_section(str(skill))
        assert second == []  # idempotent: no second append

        after_two = skill.read_text(encoding="utf-8")
        assert after_two == after_one  # unchanged by the second call
        assert after_two.count(publish_qoder._DEP_MARKER) == 1

    def test_plain_skill_without_marker_appends_once(self, tmp_path: Path) -> None:
        skill = tmp_path / "SKILL.md"
        skill.write_text("# Iterate\n", encoding="utf-8")
        result = publish_qoder._append_dependencies_section(str(skill))
        assert result
        assert publish_qoder._DEP_MARKER in skill.read_text(encoding="utf-8")