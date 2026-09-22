"""Tests for scripts/publish_qoder.py.

Covers the dependencies/self-containment section idempotency marker: a marker
appended to a staged SKILL.md must be detected verbatim on a later build, so it
is never appended twice when the same annotated file is reused (``--source``).
Also covers the safe zip extraction guard (``_safe_members``) that replaces the
previous unsafe ``os.system`` + bare ``extract`` path.
"""

from __future__ import annotations

import io
import os
import subprocess
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


class TestFindHarness:
    def test_finds_harness_dir_at_any_depth(self, tmp_path: Path) -> None:
        tree = tmp_path / "iterate"
        (tree / "nested").mkdir(parents=True)
        (tree / "nested" / "harness").mkdir()
        (tree / "nested" / "harness" / "x").write_text("x", encoding="utf-8")
        hits = publish_qoder._find_harness(str(tree))
        assert hits == [os.path.join("nested", "harness")]

    def test_finds_file_named_harness(self, tmp_path: Path) -> None:
        tree = tmp_path / "iterate"
        tree.mkdir()
        (tree / "harness").write_text("x", encoding="utf-8")
        hits = publish_qoder._find_harness(str(tree))
        assert hits == ["harness"]

    def test_clean_tree_has_no_hits(self, tmp_path: Path) -> None:
        tree = tmp_path / "iterate"
        (tree / "scripts").mkdir(parents=True)
        (tree / "scripts" / "harness_guard.txt").write_text("x", encoding="utf-8")
        assert publish_qoder._find_harness(str(tree)) == []


def _zip_path_with_members(tmp_path: Path, entries: list[tuple[str, bytes]]) -> str:
    """Write ``entries`` into a zip file and return its path."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    buf.seek(0)
    path = tmp_path / "members.zip"
    path.write_bytes(buf.getvalue())
    return str(path)


class TestValidateZipTopLevel:
    def test_foreign_top_level_entry_rejected(self, tmp_path: Path) -> None:
        """A zip smuggling a rival top-level dir under a sorted-later name must
        fail: checking only names[0] would let 'z-pwn/evil' slip past."""
        zip_path = _zip_path_with_members(
            tmp_path,
            [("iterate/SKILL.md", b"# skill"), ("z-pwn/evil.sh", b"pwn")],
        )
        errors, _warnings, _size = publish_qoder.validate_zip(zip_path)
        assert any("z-pwn" in e and "iterate" in e for e in errors), errors
        assert any("harness" in e for e in errors) is False

    def test_only_iterate_top_passes(self, tmp_path: Path) -> None:
        zip_path = _zip_path_with_members(
            tmp_path,
            [("iterate/SKILL.md", b"# skill"), ("iterate/config/iterate.config.yaml", b"goal: x")],
        )
        errors, _warnings, _size = publish_qoder.validate_zip(zip_path)
        assert errors == []

    def test_harness_entry_anywhere_rejected(self, tmp_path: Path) -> None:
        zip_path = _zip_path_with_members(
            tmp_path,
            [("iterate/SKILL.md", b"# skill"), ("iterate/harness/x", b"x")],
        )
        errors, _warnings, _size = publish_qoder.validate_zip(zip_path)
        assert any("harness" in e for e in errors), errors


class TestBuildPackageDefaultOut:
    def test_build_without_out_survives(self, tmp_path: Path, monkeypatch) -> None:
        """Building without --out must leave the zip on disk.

        Regression: the default zip path lived inside the temp staging dir and
        was deleted when the context manager exited — a build with no --out
        silently produced nothing.
        """
        # `out=None` writes the zip to the process CWD; pin that to a temp dir
        # so the artifact never leaks into the repo working tree.
        monkeypatch.chdir(tmp_path)
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


class TestCopyTrackedTree:
    def _git(self, repo: Path, args: list[str], env: dict) -> None:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            env=env,
            capture_output=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr.decode()

    def test_only_committed_files_copied_scratch_never_leaks(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Tracked-tree fallback must equal git archive: untracked dev/scratch
        artifacts in the working tree must never ship in the package body."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "SKILL.md").write_text("# skill\n", encoding="utf-8")
        (repo / "shipped.txt").write_text("s", encoding="utf-8")
        (repo / "scripts").mkdir()
        (repo / "scripts" / "install.py").write_text("ok", encoding="utf-8")
        (repo / ".gitignore").write_text("scratch.\n", encoding="utf-8")
        (repo / "scratch.py").write_text("untracked wat", encoding="utf-8")
        (repo / "dev").mkdir()
        (repo / "dev" / "experiments.py").write_text("dev only", encoding="utf-8")

        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        self._git(repo, ["init", "-q", "-b", "main"], env)
        self._git(repo, ["add", "SKILL.md", "shipped.txt", "scripts/install.py", ".gitignore"], env)
        self._git(repo, ["commit", "-q", "-m", "seed"], env)

        monkeypatch.setattr(publish_qoder, "REPO_ROOT", str(repo))
        dst = tmp_path / "dst"
        dst.mkdir()
        publish_qoder._copy_tracked_tree(str(dst), ("dev",))
        names = sorted(str(p.relative_to(dst)) for p in dst.rglob("*") if p.is_file())
        assert "SKILL.md" in names
        assert "shipped.txt" in names
        assert "scripts/install.py" in names
        assert ".gitignore" in names
        # Untracked scratch and excluded dir never ship.
        assert all("scratch.py" not in n for n in names)
        assert all("dev" not in n for n in names)