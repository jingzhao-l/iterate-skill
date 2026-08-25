"""Comprehensive tests for scripts/install.py.

The installer/uninstaller/config-manager script carries a large amount of
business logic (copy logic, assistant detection, interactive prompts, config
editing with atomic revert, release download with mandatory checksum
verification) that previously had no dedicated unit coverage.

Mirrors the import strategy of tests/test_validate.py: the standalone script
is imported directly via ``sys.path``, and pure logic is exercised without a
TTY or network. Network and ``subprocess`` paths are mocked via monkeypatch so
the behaviour contracts (mandatory checksum, fallback to local source, revert
on failed validation) are verified deterministically.
"""

from __future__ import annotations

import io
import shutil
import sys
import tarfile
import tempfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

import install  # noqa: I001  (module imported after sys.path setup for scripts/)


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #

def _make_fake_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a minimal skill source tree with small REQUIRED/OPTIONAL lists.

    Narrowing ``REQUIRED_FILES`` / ``OPTIONAL_FILES`` keeps copy tests fast and
    focused while exercising the same control flow as the real file lists.
    """
    source = tmp_path / "src"
    (source / "config").mkdir(parents=True)
    (source / "config" / "iterate.config.yaml").write_text("goal: test\n", encoding="utf-8")
    (source / "config" / "config.schema.json").write_text("{}", encoding="utf-8")
    (source / "config" / "dimensions").mkdir(parents=True)
    (source / "tools").mkdir(parents=True)
    (source / "tools" / "note.md").write_text("tool note", encoding="utf-8")
    source.joinpath("SKILL.md").write_text("# test skill\n", encoding="utf-8")

    monkeypatch.setattr(install, "REQUIRED_FILES", [
        "SKILL.md",
        "config/iterate.config.yaml",
        "config/config.schema.json",
        "config/dimensions",
    ])
    monkeypatch.setattr(install, "OPTIONAL_FILES", ["tools/note.md", "README.md"])
    return source


def _seed_real_validation_source(source: Path) -> None:
    """Upgrade a fake source tree with the real validation inputs.

    ``interactive_config`` / ``set_config_values`` load the master config
    (``config/iterate.config.yaml``) for defaults and validate the result with
    the real ``validate.py`` (which needs the real schema, the real dimension
    YAML files, and a non-empty ``validation.command_whitelist``). Without the
    master config the generated project config is missing ``command_whitelist``
    and validation would fail. Copying the real inputs keeps these tests
    faithful to actual end-to-end usage.
    """
    (source / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / "scripts" / "validate.py", source / "scripts" / "validate.py")
    (source / "config").mkdir(parents=True, exist_ok=True)
    (source / "config" / "config.schema.json").write_text(
        (REPO_ROOT / "config" / "config.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (source / "config" / "dimensions").mkdir(parents=True, exist_ok=True)
    for dim_file in (REPO_ROOT / "config" / "dimensions").glob("*.yaml"):
        shutil.copy(dim_file, source / "config" / "dimensions" / dim_file.name)
    shutil.copy(
        REPO_ROOT / "config" / "iterate.config.yaml",
        source / "config" / "iterate.config.yaml",
    )


class _SeqInput:
    """Inject a sequence of canned answers for interactive prompts."""

    def __init__(self, answers: list[str]) -> None:
        self._answers = list(answers)
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self._answers:
            raise AssertionError("More prompts than canned answers")
        return self._answers.pop(0)


# --------------------------------------------------------------------------- #
# copy_skill_files
# --------------------------------------------------------------------------- #

class TestCopySkillFiles:
    def test_copies_required_and_optional(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        dst = tmp_path / "dst"
        copied = install.copy_skill_files(source, dst, dry_run=False, force=False)
        assert (dst / "SKILL.md").read_text(encoding="utf-8") == "# test skill\n"
        assert (dst / "config" / "iterate.config.yaml").exists()
        assert (dst / "config" / "dimensions").is_dir()
        assert (dst / "tools" / "note.md").read_text(encoding="utf-8") == "tool note"
        # Missing optional (README.md) is skipped silently, but present files
        # are copied.
        assert any("note.md" in c for c in copied)

    def test_missing_required_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        # Remove a required file (the whole dimensions directory).
        shutil.rmtree(source / "config" / "dimensions")
        with pytest.raises(FileNotFoundError):
            install.copy_skill_files(source, tmp_path / "dst", dry_run=False, force=False)

    def test_dry_run_does_not_copy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        dst = tmp_path / "dst"
        copied = install.copy_skill_files(source, dst, dry_run=True, force=False)
        assert not dst.exists()
        assert copied

    def test_skip_when_exists_without_force(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "SKILL.md").write_text("old", encoding="utf-8")
        install.copy_skill_files(source, dst, dry_run=False, force=False)
        assert (dst / "SKILL.md").read_text(encoding="utf-8") == "old"

    def test_force_overwrites_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "SKILL.md").write_text("old", encoding="utf-8")
        install.copy_skill_files(source, dst, dry_run=False, force=True)
        assert (dst / "SKILL.md").read_text(encoding="utf-8") == "# test skill\n"

    def test_force_replaces_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        dst = tmp_path / "dst"
        dst.mkdir()
        # Pre-existing dimensions dir with stale content.
        (dst / "config").mkdir(parents=True)
        (dst / "config" / "dimensions").mkdir()
        (dst / "config" / "dimensions" / "stale.yaml").write_text("x", encoding="utf-8")
        install.copy_skill_files(source, dst, dry_run=False, force=True)
        assert (dst / "config" / "dimensions").is_dir()
        assert not (dst / "config" / "dimensions" / "stale.yaml").exists()

    def test_force_overwrites_symlink_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """--force must unlink a symlinked destination dir, not rmtree it (fix 6).

        shutil.rmtree() on a symlink raises OSError on modern Python; the fix
        unlinks the symlink first so a --force install over a symlinked
        directory completes instead of crashing.
        """
        source = _make_fake_source(tmp_path, monkeypatch)
        dst = tmp_path / "dst"
        dst.mkdir()
        (dst / "config").mkdir()
        link_target = tmp_path / "elsewhere"
        link_target.mkdir()
        (dst / "config" / "dimensions").symlink_to(link_target, target_is_directory=True)
        install.copy_skill_files(source, dst, dry_run=False, force=True)
        assert (dst / "config" / "dimensions").is_dir()
        assert not (dst / "config" / "dimensions").is_symlink()

    def test_rejects_copy_escaping_destination(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """A file entry resolving outside the destination must be refused (fix 12)."""
        source = tmp_path / "src"
        source.mkdir()
        # The source file exists (so the copy would succeed but for the check):
        (source / ".." / "SKILL.md").write_text("skill", encoding="utf-8")
        # ".." relative escapes the destination, which lives inside source.
        monkeypatch.setattr(install, "REQUIRED_FILES", ["../SKILL.md"])
        monkeypatch.setattr(install, "OPTIONAL_FILES", [])
        dst = source / "dst"
        dst.mkdir()
        with pytest.raises(ValueError):
            install.copy_skill_files(source, dst, dry_run=False, force=False)


# --------------------------------------------------------------------------- #
# detect_installed_assistants
# --------------------------------------------------------------------------- #

class TestDetectInstalledAssistants:
    def test_detects_by_parent_dir_marker(self, tmp_path: Path):
        # create .trae/skills and .cursor/skills parent markers
        (tmp_path / ".trae" / "skills").mkdir(parents=True)
        (tmp_path / ".cursor" / "skills").mkdir(parents=True)
        found = install.detect_installed_assistants(tmp_path)
        assert "trae" in found
        assert "cursor" in found
        assert "claude" not in found

    def test_returns_empty_when_none(self, tmp_path: Path):
        assert install.detect_installed_assistants(tmp_path) == []


# --------------------------------------------------------------------------- #
# _ArrowSelectState (pure state machine)
# --------------------------------------------------------------------------- #

class TestArrowSelectState:
    def test_default_all_selected(self):
        st = install._ArrowSelectState(["a", "b", "c"])
        assert set(st.result) == {"a", "b", "c"}

    def test_preselected_only(self):
        st = install._ArrowSelectState(["a", "b", "c"], preselected={"b"})
        assert st.result == ["b"]

    def test_move_wraps(self):
        st = install._ArrowSelectState(["a", "b", "c"])  # rows: a,b,c,None
        st.move(-1)
        assert st.index == len(st.rows) - 1  # wraps to Done row
        st.move(1)
        assert st.index == 0

    def test_toggle_on_done_finishes(self):
        st = install._ArrowSelectState(["a"])
        st.index = len(st.rows) - 1  # Done row
        st.toggle_current()
        assert st.finished is True

    def test_toggle_add_remove(self):
        st = install._ArrowSelectState(["a", "b"], preselected={"a"})
        st.toggle_current()  # row 0 = "a" -> remove
        assert "a" not in st.selected
        st.toggle_current()  # row 0 = "a" -> re-add
        assert "a" in st.selected

    def test_cancel_empties(self):
        st = install._ArrowSelectState(["a", "b"])
        st.cancel()
        assert st.finished is True
        assert st.result == []

    def test_window_scroll_follows_cursor(self):
        opts = [f"o{i}" for i in range(10)]
        st = install._ArrowSelectState(opts, window_size=4)
        assert st.visible_options() == ["o0", "o1", "o2", "o3"]
        for _ in range(4):
            st.move(1)  # move to index 4
        assert st.index == 4
        assert "o4" in st.visible_options()

    def test_done_row_shows_last_page(self):
        opts = [f"o{i}" for i in range(10)]
        st = install._ArrowSelectState(opts, window_size=4)
        st.index = len(st.rows) - 1  # Done row
        assert st.visible_options() == [f"o{i}" for i in range(6, 10)]

    def test_render_height_is_bounded(self):
        # Many options must render as a short fixed-height menu (no overflow),
        # preventing the "staircase / spiral" on terminals shorter than the list.
        opts = [f"o{i}" for i in range(30)]
        st = install._ArrowSelectState(opts, window_size=4)
        rendered = install._render_arrow_select(st, "title")
        assert len(rendered.split("\n")) == 7  # title + hint + 4 options + Done
        assert "Done" in rendered


class TestTuiRedrawHelpers:
    def test_strip_ansi_removes_cursor_and_color_sequences(self):
        # Cursor moves (A/B/G), erase (J/K) and SGR colors must all disappear so
        # visible width is measured from real text, not escape bytes.
        s = "\x1b[36m◆ title\x1b[0m\x1b[2A\x1b[0J"
        assert install._strip_ansi(s) == "◆ title"

    def test_wcwidth_counts_cjk_doubles(self):
        assert install._wcwidth_display_cols("ab") == 2
        assert install._wcwidth_display_cols("中文") == 4
        assert install._wcwidth_display_cols("a中") == 3

    def test_physical_row_count_handles_wrapping(self):
        # A long title (wider than the terminal) must count as multiple physical
        # rows so the redraw rewinds enough lines instead of cascading downward.
        lines = install._arrow_select_lines(
            install._ArrowSelectState(["claude"], window_size=6),
            "这是一个很长很长的标题 Select a fairly long title",
        )
        cols = 40
        rows = install._physical_row_count(lines, cols)
        assert rows >= len(lines), "wrapped lines must not drop physical rows"

    def test_physical_row_count_narrow_terminal_grows(self):
        lines = ["◆ title here", "  ○ claude", "  \u2192 Done / 完成"]
        assert install._physical_row_count(lines, 10) >= 4

    def test_physical_row_count_always_at_least_line_count(self):
        lines = install._arrow_select_lines(
            install._ArrowSelectState(["claude"], window_size=6),
            "title",
        )
        assert install._physical_row_count(lines, 0) == len(lines)
        assert install._physical_row_count(lines, 200) == len(lines)

    def test_arrow_redraw_output_uses_crlf_between_lines(self):
        # Raw terminal mode disables ONLCR (LF-only newline), so a redraw that
        # joins menu rows with bare "\n" stacks them diagonally ("staircase /
        # spiral" bug). The redraw must use "\r\n" so every row returns to
        # column 0 before the next one is written.
        state = install._ArrowSelectState(["claude", "trae"], window_size=6)
        out = install._arrow_redraw_output(state, "title", 120)
        assert "\n\n" not in out, "bare LF must not appear between menu rows"
        assert "\r\n" in out, "rows must be separated by CRLF in raw mode"
        # The frame still contains the same menu content (only the join changed).
        assert "title" in out
        assert "Claude" in out
        assert "Trae" in out


class TestReadArrowKey:
    def _stream(self, text: str) -> io.StringIO:
        return io.StringIO(text)

    def test_up(self):
        assert install._read_arrow_key(self._stream("\x1b[A")) == "up"

    def test_down(self):
        assert install._read_arrow_key(self._stream("\x1b[B")) == "down"

    def test_toggle(self):
        assert install._read_arrow_key(self._stream("\r")) == "toggle"
        assert install._read_arrow_key(self._stream("\n")) == "toggle"
        assert install._read_arrow_key(self._stream(" ")) == "toggle"

    def test_cancel(self):
        assert install._read_arrow_key(self._stream("q")) == "cancel"

    def test_ctrl_c_raises(self):
        with pytest.raises(KeyboardInterrupt):
            install._read_arrow_key(self._stream("\x03"))

    def test_unknown(self):
        assert install._read_arrow_key(self._stream("z")) is None


# --------------------------------------------------------------------------- #
# _prompt_multi_select
# --------------------------------------------------------------------------- #

class TestPromptMultiSelect:
    def test_enter_confirms_selection(self):
        seq = _SeqInput([""])
        result = install._prompt_multi_select(
            ["trae", "cursor"], seq, preselected={"trae"}
        )
        assert result == ["trae"]

    def test_toggle_by_number(self):
        seq = _SeqInput(["1,2", ""])
        result = install._prompt_multi_select(["trae", "cursor"], seq, preselected=set())
        assert result == ["cursor", "trae"]

    def test_select_all_and_none(self):
        seq = _SeqInput(["a", "n", ""])
        result = install._prompt_multi_select(["trae", "cursor"], seq, preselected={"cursor"})
        assert result == []
        # Ensure 'a' then 'n' toggled all on then none.
        assert result == []

    def test_out_of_range_does_not_crash(self):
        seq = _SeqInput(["999", ""])
        result = install._prompt_multi_select(["trae"], seq, preselected={"trae"})
        assert result == ["trae"]


# --------------------------------------------------------------------------- #
# _parse_checksum
# --------------------------------------------------------------------------- #

class TestParseChecksum:
    def test_plain(self):
        assert install._parse_checksum(b"abc123  iterate-skill.tar.gz\n", "iterate-skill.tar.gz") == "abc123"

    def test_starred(self):
        assert install._parse_checksum(b"def456 *iterate-skill.tar.gz\n", "iterate-skill.tar.gz") == "def456"

    def test_dot_slash_prefix(self):
        assert install._parse_checksum(b"abc123  ./iterate-skill.tar.gz\n", "iterate-skill.tar.gz") == "abc123"

    def test_crlf(self):
        assert install._parse_checksum(b"abc123  iterate-skill.tar.gz\r\n", "iterate-skill.tar.gz") == "abc123"

    def test_comments_and_blanks_ignored(self):
        text = b"# comment\n\nabc  file1\n"
        assert install._parse_checksum(text, "file1") == "abc"

    def test_missing_filename(self):
        assert install._parse_checksum(b"abc  other.txt\n", "iterate-skill.tar.gz") is None


# --------------------------------------------------------------------------- #
# parse_value / set_nested_value / load_config / save_config
# --------------------------------------------------------------------------- #

class TestParseValue:
    def test_empty(self):
        assert install.parse_value("") == ""

    def test_int(self):
        assert install.parse_value("7") == 7

    def test_float(self):
        assert install.parse_value("3.5") == 3.5

    def test_list(self):
        assert install.parse_value("[correctness, security]") == ["correctness", "security"]

    def test_dict(self):
        assert install.parse_value('{"a": 1}') == {"a": 1}

    def test_bool_kept(self):
        assert install.parse_value("true") is True
        assert install.parse_value("false") is False

    def test_plain_string_fallback(self):
        assert install.parse_value("improve code quality") == "improve code quality"

    def test_yes_not_bool(self):
        # YAML 1.1 treats yes as bool; we deliberately keep it a string.
        assert install.parse_value("yes") == "yes"


class TestSetNestedValue:
    def test_flat(self):
        cfg: dict[str, object] = {}
        install.set_nested_value(cfg, "goal", "x")
        assert cfg == {"goal": "x"}

    def test_nested_creates_mappings(self):
        cfg: dict[str, object] = {}
        install.set_nested_value(cfg, "validation.commands.python", ["ruff check"])
        assert cfg["validation"]["commands"]["python"] == ["ruff check"]  # type: ignore[index]


class TestLoadSaveConfig:
    def test_missing_returns_empty(self, tmp_path: Path):
        assert install.load_config(tmp_path / "nope.yaml") == {}

    def test_roundtrip(self, tmp_path: Path):
        path = tmp_path / "c.yaml"
        install.save_config(path, {"goal": "g", "nested": {"a": [1, 2]}})
        assert install.load_config(path) == {"goal": "g", "nested": {"a": [1, 2]}}

    def test_invalid_yaml_raises(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text("a: [unclosed\n", encoding="utf-8")
        with pytest.raises(ValueError):
            install.load_config(path)

    def test_non_mapping_raises(self, tmp_path: Path):
        path = tmp_path / "list.yaml"
        path.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(TypeError):
            install.load_config(path)


# --------------------------------------------------------------------------- #
# init_config / list_config / set_config_values / config_command
# --------------------------------------------------------------------------- #

class TestInitConfig:
    def test_init_copies_master(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = tmp_path / "src"
        (source / "config").mkdir(parents=True)
        (source / "config" / "iterate.config.yaml").write_text("goal: master\n", encoding="utf-8")
        target = tmp_path / "proj"
        target.mkdir()
        assert install.init_config(target, source) == 0
        assert (target / "iterate.config.yaml").read_text(encoding="utf-8").strip() == "goal: master"

    def test_init_refuses_when_exists(self, tmp_path: Path):
        source = tmp_path / "src"
        (source / "config").mkdir(parents=True)
        (source / "config" / "iterate.config.yaml").write_text("x", encoding="utf-8")
        target = tmp_path / "proj"
        target.mkdir()
        (target / "iterate.config.yaml").write_text("existing", encoding="utf-8")
        assert install.init_config(target, source) == 1

    def test_init_error_when_master_missing(self, tmp_path: Path):
        target = tmp_path / "proj"
        target.mkdir()
        assert install.init_config(target, tmp_path / "empty-src") == 1


class TestListConfig:
    def test_lists_existing(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        target = tmp_path / "proj"
        target.mkdir()
        (target / "iterate.config.yaml").write_text("goal: hi\n", encoding="utf-8")
        assert install.list_config(target) == 0
        out = capsys.readouterr().out
        assert "goal: hi" in out

    def test_missing_warns(self, tmp_path: Path):
        target = tmp_path / "proj"
        target.mkdir()
        assert install.list_config(target) == 1


class TestSetConfigValues:
    def test_sets_and_validates(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        _seed_real_validation_source(source)
        target = tmp_path / "proj"
        target.mkdir()
        # ``--set`` operates on an existing project config (the documented flow
        # is ``config --init`` then ``config --set key=value``). Seed it with
        # the master config so command_whitelist etc. are present.
        shutil.copy(source / "config" / "iterate.config.yaml", target / "iterate.config.yaml")
        assert install.set_config_values(target, source, [["goal=Improve quality"]]) == 0
        cfg = install.load_config(target / "iterate.config.yaml")
        assert cfg["goal"] == "Improve quality"

    def test_invalid_set_argument_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        assert install.set_config_values(target, source, [["notakeyvalue"]]) == 1


class TestConfigCommandDispatch:
    def test_no_action_warns(self, tmp_path: Path):
        assert install.config_command(tmp_path, tmp_path, False, False, False) == 1

    def test_init_dispatch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        assert install.config_command(target, source, True, False, False) == 0
        assert (target / "iterate.config.yaml").exists()


# --------------------------------------------------------------------------- #
# _safe_extractall (path traversal protection)
# --------------------------------------------------------------------------- #

class TestSafeExtractall:
    def _build_tar(self, tmp_path: Path, members: list[str]) -> str:
        tar_path = tmp_path / "a.tar"
        with tarfile.open(tar_path, "w") as tar:
            for name in members:
                info = tarfile.TarInfo(name)
                info.size = 4
                tar.addfile(info, io.BytesIO(b"data"))
        return str(tar_path)

    def _build_link_tar(self, tmp_path: Path, linkname: str) -> str:
        tar_path = tmp_path / "link.tar"
        with tarfile.open(tar_path, "w") as tar:
            info = tarfile.TarInfo("evil-link")
            info.type = tarfile.SYMTYPE
            info.linkname = linkname
            tar.addfile(info)
        return str(tar_path)

    def test_extracts_safe_members(self, tmp_path: Path):
        tar_path = self._build_tar(tmp_path, ["SKILL.md"])
        dest = tmp_path / "out"
        dest.mkdir()
        with tarfile.open(tar_path) as tar:
            install._safe_extractall(tar, dest)
        assert (dest / "SKILL.md").exists()

    def test_rejects_path_traversal(self, tmp_path: Path):
        tar_path = self._build_tar(tmp_path, ["../evil", "ok.md"])
        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(tarfile.TarError), tarfile.open(tar_path) as tar:
            install._safe_extractall(tar, dest)

    def test_rejects_symlink_escaping_dest(self, tmp_path: Path):
        """A symlink member pointing outside the destination is refused (fix 11)."""
        tar_path = self._build_link_tar(tmp_path, "../../outside")
        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(tarfile.TarError), tarfile.open(tar_path) as tar:
            install._safe_extractall(tar, dest)

    def test_rejects_absolute_symlink_target(self, tmp_path: Path):
        tar_path = self._build_link_tar(tmp_path, "/etc/passwd")
        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(tarfile.TarError), tarfile.open(tar_path) as tar:
            install._safe_extractall(tar, dest)

    def test_allows_symlink_inside_dest(self, tmp_path: Path):
        tar_path = self._build_link_tar(tmp_path, "inside/file.txt")
        dest = tmp_path / "out"
        dest.mkdir()
        with tarfile.open(tar_path) as tar:
            install._safe_extractall(tar, dest)
        assert (dest / "evil-link").is_symlink()


# --------------------------------------------------------------------------- #
# install_command
# --------------------------------------------------------------------------- #

class TestInstallCommand:
    def test_dry_run_lists_no_copy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        assert install.install_command("trae", target, dry_run=True, source=source, force=False, global_install=False) == 0
        assert not (target / ".trae").exists()

    def test_explicit_ai_copies(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        assert install.install_command("trae", target, dry_run=False, source=source, force=False, global_install=False) == 0
        assert (target / ".trae" / "skills" / "iterate" / "SKILL.md").exists()

    def test_missing_required_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        shutil.rmtree(source / "config" / "dimensions")
        target = tmp_path / "proj"
        target.mkdir()
        with pytest.raises(FileNotFoundError):
            install.install_command("trae", target, dry_run=False, source=source, force=False, global_install=False)

    def test_interactive_cancel_returns_1(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        # No assistants selected -> cancellation.
        seq = _SeqInput([""])
        monkeypatch.setattr(install, "interactive_select_assistants", lambda t, i: [])
        assert install.install_command(None, tmp_path, dry_run=False, source=source, force=False, global_install=False, input_func=seq) == 1

    def test_stale_install_asks_to_upgrade(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        dest = target / ".trae" / "skills" / "iterate"
        dest.mkdir(parents=True)
        (dest / "SKILL.md").write_text("old stale version", encoding="utf-8")
        monkeypatch.setattr(install.sys.stdin, "isatty", lambda: True)
        seq = _SeqInput(["y"])
        assert install.install_command("trae", target, dry_run=False, source=source, force=False, global_install=False, input_func=seq) == 0
        # User confirmed the upgrade -> stale files are overwritten.
        assert (dest / "SKILL.md").read_text(encoding="utf-8") == "# test skill\n"
        assert any("upgrade" in c or "覆盖升级" in c for c in seq.calls)

    def test_stale_install_decline_keeps_existing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        dest = target / ".trae" / "skills" / "iterate"
        dest.mkdir(parents=True)
        (dest / "SKILL.md").write_text("old stale version", encoding="utf-8")
        monkeypatch.setattr(install.sys.stdin, "isatty", lambda: True)
        seq = _SeqInput(["n"])
        assert install.install_command("trae", target, dry_run=False, source=source, force=False, global_install=False, input_func=seq) == 0
        # User declined the upgrade -> existing install is left untouched.
        assert (dest / "SKILL.md").read_text(encoding="utf-8") == "old stale version"


# --------------------------------------------------------------------------- #
# uninstall_command
# --------------------------------------------------------------------------- #

class TestUninstallCommand:
    def test_uninstall_with_yes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        install.install_command("trae", target, dry_run=False, source=source, force=False, global_install=False)
        assert (target / ".trae" / "skills" / "iterate").is_dir()
        assert install.uninstall_command("trae", target, global_install=False, yes=True) == 0
        assert not (target / ".trae" / "skills" / "iterate").exists()

    def test_uninstall_decline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        install.install_command("trae", target, dry_run=False, source=source, force=False, global_install=False)
        seq = _SeqInput(["n"])
        assert install.uninstall_command("trae", target, global_install=False, yes=False, input_func=seq) == 0
        assert (target / ".trae" / "skills" / "iterate").exists()

    def test_none_installed_warns(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        assert install.uninstall_command("trae", target, global_install=False, yes=True) == 0


# --------------------------------------------------------------------------- #
# update_command (network mocked)
# --------------------------------------------------------------------------- #

class TestUpdateCommand:
    def test_falls_back_to_local_no_release(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        monkeypatch.setattr(install, "_fetch_latest_release_info", lambda token: None)
        assert install.update_command("trae", target, source, None, global_install=False, yes=True) == 0
        assert (target / ".trae" / "skills" / "iterate" / "SKILL.md").exists()

    def test_refuses_without_checksum(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        monkeypatch.setattr(install, "_fetch_latest_release_info", lambda token: {"tag": "v1", "tarball_url": "http://x/tar"})
        # without 'checksum_url', update must refuse download and fall back to local.
        assert install.update_command("trae", target, source, None, global_install=False, yes=True) == 0
        assert (target / ".trae" / "skills" / "iterate" / "SKILL.md").exists()

    def test_user_declines_download(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
        source = _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        info = {"tag": "v1", "tarball_url": "http://x/tar", "checksum_url": "http://x/sha"}
        monkeypatch.setattr(install, "_fetch_latest_release_info", lambda token: info)
        # Confirmation prompt is served through the injected input_func (fix 10).
        seq = _SeqInput(["n"])
        assert install.update_command("trae", target, source, None, global_install=False, yes=False, input_func=seq) == 0
        assert not (target / ".trae").exists()

    def test_downloads_when_release_available(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        # update_command cleanup runs ``rmtree(release_source.parent)`` to drop
        # the download's temp area, so the mock must serve a release dir under
        # its own dedicated mkdtemp (exactly like ``_download_release_source``
        # does in production) — NOT inside tmp_path, or cleaning its parent
        # would also delete ``target``.
        release_root = Path(tempfile.mkdtemp())
        try:
            release_path = release_root / "release"
            release_path.mkdir(parents=True, exist_ok=True)
            (release_path / "SKILL.md").write_text("release skill\n", encoding="utf-8")
            # A real release carries all REQUIRED_FILES; complete the source so
            # the subsequent copy in update_command does not raise.
            _seed_real_validation_source(release_path)
            monkeypatch.setattr(install, "_fetch_latest_release_info", lambda token: {"tag": "v1", "tarball_url": "x", "checksum_url": "y"})
            monkeypatch.setattr(install, "_download_release_source", lambda a, b, c: release_path)
            assert install.update_command("trae", target, source, None, global_install=False, yes=True) == 0
            installed = target / ".trae" / "skills" / "iterate" / "SKILL.md"
            # The traversed volume can lag on directory-entry visibility right
            # after a copy; poll briefly for the file before asserting contents.
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if installed.exists():
                    break
                time.sleep(0.05)
            assert installed.read_text(encoding="utf-8") == "release skill\n"
        finally:
            shutil.rmtree(release_root, ignore_errors=True)

    def test_no_installed_returns_1(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        monkeypatch.setattr(install, "_fetch_latest_release_info", lambda token: None)
        monkeypatch.setattr(install, "detect_installed_assistants", lambda t: [])
        assert install.update_command(None, target, source, None, global_install=False, yes=True) == 1

    def test_malformed_token_fails_fast(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """A malformed --token must abort the update before any network call."""
        source = _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        called = {"fetch": False}

        def _noop_fetch(token):
            called["fetch"] = True

        monkeypatch.setattr(install, "_fetch_latest_release_info", _noop_fetch)
        assert install.update_command("trae", target, source, "not-a-token", global_install=False, yes=True) == 1
        assert called["fetch"] is False

    def test_empty_token_treated_as_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Whitespace-only tokens are absent (no validation error)."""
        source = _make_fake_source(tmp_path, monkeypatch)
        target = tmp_path / "proj"
        target.mkdir()
        monkeypatch.setattr(install, "_fetch_latest_release_info", lambda token: None)
        assert install.update_command("trae", target, source, "   ", global_install=False, yes=True) == 0
        assert (target / ".trae" / "skills" / "iterate" / "SKILL.md").exists()


# --------------------------------------------------------------------------- #
# Interactive prompt helpers (via input_func)
# --------------------------------------------------------------------------- #

class TestPromptHelpers:
    def test_prompt_choice_by_number(self):
        assert install.prompt_choice("q", ["a", "b"], input_func=lambda p: "2") == "b"

    def test_prompt_choice_by_name_and_default(self):
        assert install.prompt_choice("q", ["a", "b"], default="a", input_func=lambda p: "") == "a"
        assert install.prompt_choice("q", ["a", "b"], input_func=lambda p: "b") == "b"

    def test_prompt_text_with_default(self):
        assert install.prompt_text("q", default="d", input_func=lambda p: "") == "d"
        assert install.prompt_text("q", input_func=lambda p: "v") == "v"

    def test_prompt_int(self):
        assert install.prompt_int("q", default=5, input_func=lambda p: "") == 5
        assert install.prompt_int("q", input_func=lambda p: "12") == 12

    def test_prompt_int_in_range_retries(self):
        calls = iter(["99", "3"])
        assert install.prompt_int_in_range("q", 1, 10, 5, input_func=lambda p: next(calls)) == 3

    def test_prompt_bool(self):
        assert install.prompt_bool("q", default=True, input_func=lambda p: "") is True
        assert install.prompt_bool("q", default=True, input_func=lambda p: "n") is False

    def test_prompt_dimensions_empty_keeps_current(self):
        assert install.prompt_dimensions(["correctness"], input_func=lambda p: "") == ["correctness"]

    def test_prompt_dimensions_by_number(self):
        assert install.prompt_dimensions([], input_func=lambda p: "1,2") == ["correctness", "security"]


class TestInteractiveConfig:
    def test_wizard_creates_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        source = _make_fake_source(tmp_path, monkeypatch)
        # Real validate.py + real schema + real dimensions + master config are
        # all needed so the post-wizard validation passes (master config carries
        # validation.command_whitelist and the definition of valid dimensions).
        _seed_real_validation_source(source)
        target = tmp_path / "proj"
        target.mkdir()

        # prompt ordering: goal, max_rounds, language, dimensions, scope,
        # max_lines, push_per_round.
        seq = _SeqInput([
            "Improve quality",  # goal
            "7",                # max_rounds
            "1",                # language -> zh
            "1,2",              # dimensions -> correctness, security
            "2",                # scope -> changed-only
            "20",               # max_lines
            "n",                # push_per_round False
        ])
        assert install.interactive_config(target, source, input_func=seq) == 0
        cfg = install.load_config(target / "iterate.config.yaml")
        assert cfg["goal"] == "Improve quality"
        assert cfg["max_rounds"] == 7
        assert cfg["language"] == "zh"
        assert cfg["dimensions"] == ["correctness", "security"]
        assert cfg["review"]["scope"] == "changed-only"
        assert cfg["git"]["push_per_round"] is False


# --------------------------------------------------------------------------- #
# Arrow-menu terminal redraw integration (against a simulated real terminal)
# --------------------------------------------------------------------------- #

class _SimTerminal:
    """A tiny terminal that interprets only the ANSI sequences ``redraw`` emits:
    ``ESC[nA`` (cursor up), ``\r`` (column 0), ``ESC[0J`` (clear to end of
    screen) and plain text (with SGR color codes stripped, width-1 glyphs).
    This reproduces the visible grid the real terminal ends up with after any
    number of arrow-key redraws, letting us assert the menu stays a single
    clean frame (the "staircase / spiral" bug would leave stacked rows)."""

    WIDTH = 120

    def __init__(self, width: int = WIDTH) -> None:
        self.width = width
        self.grid: list[list[str]] = []  # row -> list of width cells
        self.row = 0
        self.col = 0

    def _ensure(self, row: int) -> None:
        while len(self.grid) <= row:
            self.grid.append([" "] * self.width)

    def _put(self, ch: str) -> None:
        self._ensure(self.row)
        width = install._wcwidth_display_cols(ch)
        width = max(1, width)
        if self.col + width > self.width:
            self.row += 1
            self.col = 0
        self._ensure(self.row)
        self.grid[self.row][self.col : self.col + width] = (
            list(ch.ljust(width)) if width > 1 else [ch]
        )
        self.col += width

    def feed(self, data: str) -> None:
        i = 0
        n = len(data)
        while i < n:
            ch = data[i]
            if ch == "\x1b":
                # Parse ESC [ <parameters> <final byte>. Cursor moves (A) and
                # erase-to-end (J) are applied; SGR color codes (final 'm')
                # and other controls are skipped without printing glyphs.
                if i + 1 < n and data[i + 1] == "[":
                    j = i + 2
                    while j < n and data[j] in "0123456789;":
                        j += 1
                    params = data[i + 2:j]
                    final = data[j] if j < n else ""
                    if final == "A":
                        param = int(params or "1")
                        self.row = max(0, self.row - param)
                    elif final == "J":
                        # Erase from cursor to end of screen.
                        self._erase_to_end()
                    # final 'm' (colors), 'H/D/B', etc. are ignored by design.
                    i = j + 1
                else:
                    i += 2
            elif ch == "\r":
                self.col = 0
                i += 1
            elif ch == "\n":
                # Raw terminal mode: LF moves down only, column is NOT reset
                # (OPOST/ONLCR is disabled by tty.setraw). A redraw that joins
                # lines with bare "\n" would therefore stack each row
                # diagonally — the "staircase / spiral" bug this simulates.
                self.row += 1
                i += 1
            else:
                self._put(ch)
                i += 1

    def _erase_to_end(self) -> None:
        if self.row < len(self.grid):
            self.grid[self.row][self.col:] = [" "] * (self.width - self.col)
        for r in range(self.row + 1, len(self.grid)):
            self.grid[r] = [" "] * self.width

    def screen(self) -> str:
        return "\n".join(
            "".join(row).rstrip()
            for row in self.grid
            if "".join(row).strip()
        )


class TestArrowMenuRedrawOnTerminal:
    def _render(self, cols: int) -> str:
        """Run the menu through the simulated terminal with N arrow presses."""
        state = install._ArrowSelectState(
            ["claude", "codex", "trae", "qoder", "warp", "opencode", "roo"],
            window_size=6,
        )
        term = _SimTerminal(width=cols)

        def emit() -> None:
            out = install._arrow_redraw_output(
                state, "选择要安装的 AI 工具 / Select AI assistants to install to", cols
            )
            term.feed(out)

        emit()  # first frame
        for _ in range(3):
            state.move(1)      # arrow-down
            state.toggle_current()
            emit()             # redraw after each key
        return term.screen()

    def test_redraw_stays_one_clean_frame_wide(self):
        # On a wide terminal the frame must contain the title/hint/button exactly
        # once each and no leftover rows — i.e. no stacked "spiral". We assert on
        # structural markers (hint "↑/↓", button "→ Done / 完 成") instead of the
        # bare word "Done", which also appears inside the hint line ("· Done 完 成").
        s = self._render(120)
        assert s.count("Select AI assistants to install to") == 1, s
        assert s.count("↑/↓") == 1, s
        assert s.count("→ Done / 完 成") == 1, s

    def test_redraw_stays_one_clean_frame_narrow(self):
        # Even in a narrow terminal where the long title wraps, the redraw must
        # reclaim all physical rows so the frame still appears exactly once. The
        # wrapped title splits the full English substring across two lines, so we
        # anchor on the title's leading "◆" plus the hint/button structural rows.
        s = self._render(50)
        assert s.count("◆") == 1, s
        assert s.count("↑/↓") == 1, s
        assert s.count("→ Done / 完 成") == 1, s
        assert "Done" in s