"""Tests for scripts/publish_qoder.py.

Covers the dependencies/self-containment section idempotency marker: a marker
appended to a staged SKILL.md must be detected verbatim on a later build, so it
is never appended twice when the same annotated file is reused (``--source``).
Also covers the safe zip extraction guard (``_safe_members``) that replaces the
previous unsafe ``os.system`` + bare ``extract`` path.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

import publish_qoder
import pytest


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


def _zip_with_members(
    dst: Path, entries: list[tuple[str, bytes, bool]]
) -> zipfile.ZipFile:
    """Write ``entries`` (name, data, is_symlink) into a zip under ``dst``."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as archive:
        for name, data, is_symlink in entries:
            info = zipfile.ZipInfo(name)
            if is_symlink:
                # External attr mode 0xA000 == S_IFLNK (symlink).
                info.create_system = 3
                info.external_attr = (0xA000 | 0o777) << 16
            archive.writestr(info, data)
    buf.seek(0)
    path = dst / "members.zip"
    path.write_bytes(buf.getvalue())
    return zipfile.ZipFile(path)


class TestSafeMembers:
    def test_accepts_normal_nested_members(self, tmp_path: Path) -> None:
        with _zip_with_members(
            tmp_path, [("iterate/SKILL.md", b"# skill", False)]
        ) as archive:
            names = [
                m.filename for m in publish_qoder._safe_members(archive, str(tmp_path))
            ]
        assert names == ["iterate/SKILL.md"]

    def test_rejects_path_traversal_member(self, tmp_path: Path) -> None:
        with _zip_with_members(
            tmp_path, [("../escape.txt", b"pwn", False)]
        ) as archive, pytest.raises(ValueError, match="unsafe member path"):
            list(publish_qoder._safe_members(archive, str(tmp_path)))

    def test_rejects_absolute_member(self, tmp_path: Path) -> None:
        with _zip_with_members(
            tmp_path, [("/etc/passwd", b"x", False)]
        ) as archive, pytest.raises(ValueError, match="unsafe member path"):
            list(publish_qoder._safe_members(archive, str(tmp_path)))

    def test_rejects_duplicate_members(self, tmp_path: Path) -> None:
        with _zip_with_members(
            tmp_path,
            [("iterate/SKILL.md", b"a", False), ("iterate/SKILL.md", b"b", False)],
        ) as archive, pytest.raises(ValueError, match="duplicate member"):
            list(publish_qoder._safe_members(archive, str(tmp_path)))

    def test_rejects_symlink_escaping_destination(self, tmp_path: Path) -> None:
        with _zip_with_members(
            tmp_path, [("iterate/link", b"../../out", True)]
        ) as archive, pytest.raises(ValueError, match="unsafe symlink target"):
            list(publish_qoder._safe_members(archive, str(tmp_path)))

    def test_accepts_safe_symlink_within_destination(self, tmp_path: Path) -> None:
        with _zip_with_members(
            tmp_path, [("iterate/link", b"SKILL.md", True)]
        ) as archive:
            names = [
                m.filename for m in publish_qoder._safe_members(archive, str(tmp_path))
            ]
        assert names == ["iterate/link"]


def _minimal_source(tmp_path: Path) -> Path:
    """A minimal publishable skill tree (SKILL.md + one file)."""
    source = tmp_path / "src"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: iterate\ndescription: d\nversion: 9.9.9\n---\n# body\n",
        encoding="utf-8",
    )
    (source / "a.txt").write_text("a", encoding="utf-8")
    (source / "b").mkdir(parents=True)
    (source / "b" / "nested.txt").write_text("b", encoding="utf-8")
    return source


class TestBuildPackageDefaultOut:
    def test_build_without_out_survives(self, tmp_path: Path) -> None:
        """Building without --out must leave the zip on disk.

        Regression: the default zip path lived inside the temp staging dir and
        was deleted when the context manager exited — a build with no --out
        silently produced nothing.
        """
        source = _minimal_source(tmp_path)
        zip_path, _warnings, meta = publish_qoder.build_package(
            "9.9.9", source=str(source), out=None
        )
        assert zip_path == meta["zip"]
        assert Path(zip_path).is_file()
        assert Path(zip_path).stat().st_size > 0

    def test_deterministic_zip_bytes(self, tmp_path: Path) -> None:
        """Two builds of the same tree produce byte-identical zips.

        Regression: the zip walk did not sort file entries, so ordering (and
        therefore the archive bytes) was filesystem-dependent, breaking
        checksum-and-upload flows.
        """
        source = _minimal_source(tmp_path)
        first, _w1, _m1 = publish_qoder.build_package(
            "9.9.9", source=str(source), out=str(tmp_path / "one.zip")
        )
        second, _w2, _m2 = publish_qoder.build_package(
            "9.9.9", source=str(source), out=str(tmp_path / "two.zip")
        )
        assert Path(first).read_bytes() == Path(second).read_bytes()


class TestCopyTreeDotfiles:
    def test_copy_tree_keeps_dotfiles_drops_only_git_and_excludes(
        self, tmp_path: Path
    ) -> None:
        """--source builds must match git-archive output on dotfiles.

        Regression: _copy_tree skipped every top-level dotfile, so --source
        trees dropped .gitignore / CI files that the canonical git-archive path
        ships — the fleet of distributions disagreed on the same skill body.
        """
        src = tmp_path / "src"
        src.mkdir()
        (src / ".gitignore").write_text("x", encoding="utf-8")
        (src / ".someconfig").write_text("y", encoding="utf-8")
        (src / ".git").mkdir(parents=True)
        (src / ".git" / "HEAD").write_text("ref", encoding="utf-8")
        (src / "harness").mkdir()
        (src / "harness" / "x.txt").write_text("h", encoding="utf-8")
        (src / "plain.txt").write_text("z", encoding="utf-8")

        dst = tmp_path / "dst"
        dst.mkdir()
        publish_qoder._copy_tree(str(src), str(dst), ("harness",))
        names = sorted(p.name for p in dst.iterdir())
        assert ".gitignore" in names
        assert ".someconfig" in names
        assert "plain.txt" in names
        assert ".git" not in names
        assert "harness" not in names