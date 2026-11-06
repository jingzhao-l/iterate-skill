"""Tests for ``iterate backup`` — list and restore timestamped backups.

The CLI writes a timestamped copy of a file beside itself before every
mutation (``config set``/``unset``, ``doctor --fix``, ``refresh``,
``personalize``, ``onboard``, ``import``, ``reonboard``). Before this command
existed a user had to ``ls`` the project directory and guess which backup was
the pre-change copy; ``iterate backup list``/``restore`` close that gap.

The properties that matter:

* **Recognises every tag** the CLI actually writes (configset, configunset,
  doctorfix, refresh, personalize, onboard, import, bak) plus ``restore``.
* **Round-trip fidelity** — restore reproduces the backed-up file exactly.
* **Reversible** — a restore backs up the current file first (tag ``restore``).
* **Fail closed** — an unrecognised file, an outside-project path, a directory
  target and a missing backup are all refused before anything is written.
* **``--json`` contract** — stdout holds exactly one JSON document on success,
  dry run and failure alike.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

# Bare `pytest` (CI) does not add the repo root to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iterate_cli.backup import (
    BACKUP_TAGS,
    BackupError,
    list_backups,
    restore_backup,
)
from iterate_cli.cli import main as cli_main

CONFIG_YAML = "iterate.config.yaml"


def _make_backup_name(base: str, tag: str, stamp: str | None = None) -> str:
    """Build a filename in the exact ``<base>.<tag>-<UTC>-<salt>`` shape."""
    if stamp is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{base}.{tag}-{stamp}-{uuid4().hex[:6]}"


def _write_backup(project: Path, base: str, content: str, tag: str) -> Path:
    """Write ``base`` live plus a ``tag`` backup of it, return the backup path."""
    live = project / base
    live.write_text(content, encoding="utf-8")
    backup = project / _make_backup_name(base, tag)
    backup.write_text(content, encoding="utf-8")
    return backup


# ---------------------------------------------------------------------------
# list_backups
# ---------------------------------------------------------------------------


class TestListBackups:
    def test_empty_project_lists_nothing(self, tmp_path) -> None:
        assert list_backups(tmp_path) == []

    def test_recognises_every_real_tag(self, tmp_path) -> None:
        """Every tag the CLI writes is listed, not just a hand-picked subset."""
        for tag in BACKUP_TAGS:
            base = "ITERATE.md" if tag == "bak" else CONFIG_YAML
            _write_backup(tmp_path, base, "content", tag)
        entries = list_backups(tmp_path)
        tags = {entry.tag for entry in entries}
        assert tags == set(BACKUP_TAGS)

    def test_newest_first(self, tmp_path) -> None:
        older_stamp = "20261104T110000Z"
        older = tmp_path / _make_backup_name(CONFIG_YAML, "configset", older_stamp)
        older.write_text("old", encoding="utf-8")
        # A later timestamp must sort above an earlier one even if the salt
        # would otherwise sort first.
        new_stamp = "20261104T120000Z"
        new = tmp_path / _make_backup_name(CONFIG_YAML, "doctorfix", new_stamp)
        new.write_text("new", encoding="utf-8")
        entries = list_backups(tmp_path)
        assert [e.path for e in entries] == [new, older]
        assert entries[0].tag == "doctorfix"
        assert entries[1].tag == "configset"

    def test_ignores_unrelated_files(self, tmp_path) -> None:
        (tmp_path / "README.md").write_text("x", encoding="utf-8")
        (tmp_path / "iterate.config.yaml").write_text("x", encoding="utf-8")
        (tmp_path / "notes.configset-20261101T091500Z-a1b2c3.md").write_text(
            "x", encoding="utf-8"
        )  # wrong shape: tag is not at the end
        assert list_backups(tmp_path) == []

    def test_entries_carry_metadata(self, tmp_path) -> None:
        backup = _write_backup(tmp_path, CONFIG_YAML, "goal: fix", "configset")
        (entry,) = list_backups(tmp_path)
        assert entry.base == CONFIG_YAML
        assert entry.tag == "configset"
        assert entry.label == "config set"
        assert entry.size == len("goal: fix")
        d = entry.to_dict()
        assert d["name"] == backup.name
        assert d["operation"] == "config set"
        assert d["timestamp"].endswith("+00:00")

    def test_label_falls_back_to_raw_tag(self) -> None:
        """A tag added elsewhere later must still render without a KeyError."""
        from iterate_cli.backup import BackupEntry

        entry = BackupEntry(
            path=Path("/x"), base="f", tag="futuretag", stamp="20261104T120000Z", size=1
        )
        assert entry.label == "futuretag"


# ---------------------------------------------------------------------------
# restore_backup
# ---------------------------------------------------------------------------


class TestRestoreBackup:
    def test_restore_reproduces_the_backed_up_file(self, tmp_path) -> None:
        backup = _write_backup(tmp_path, CONFIG_YAML, "goal: fix bugs\n", "configset")
        # The live file drifts from the backup.
        (tmp_path / CONFIG_YAML).write_text("goal: changed\n", encoding="utf-8")
        outcome = restore_backup(tmp_path, backup.name)
        assert outcome["restored"] is True
        assert (tmp_path / CONFIG_YAML).read_text(encoding="utf-8") == "goal: fix bugs\n"

    def test_restore_is_reversible(self, tmp_path) -> None:
        backup = _write_backup(tmp_path, CONFIG_YAML, "goal: fix bugs\n", "configset")
        (tmp_path / CONFIG_YAML).write_text("goal: changed\n", encoding="utf-8")
        outcome = restore_backup(tmp_path, backup.name)
        # A fresh backup of the pre-restore file was taken.
        pre = outcome["pre_restore_backup"]
        assert pre is not None
        assert Path(pre).is_file()
        assert Path(pre).read_text(encoding="utf-8") == "goal: changed\n"
        # Restoring that backup undoes the restore.
        undo = restore_backup(tmp_path, Path(pre).name)
        assert (tmp_path / CONFIG_YAML).read_text(encoding="utf-8") == "goal: changed\n"
        assert undo["restored"] is True

    def test_restore_creates_target_when_missing(self, tmp_path) -> None:
        backup = _write_backup(tmp_path, CONFIG_YAML, "goal: fix\n", "configset")
        (tmp_path / CONFIG_YAML).unlink()
        outcome = restore_backup(tmp_path, backup.name)
        assert outcome["restored"] is True
        assert (tmp_path / CONFIG_YAML).read_text(encoding="utf-8") == "goal: fix\n"
        assert outcome["pre_restore_backup"] is None

    def test_non_utf8_backup_is_refused_with_actionable_message(
        self, tmp_path
    ) -> None:
        """A backup that is not UTF-8 text cannot be restored; the operator
        must get an actionable message (restore manually), not a generic
        decode failure that hides the real cause."""
        backup = tmp_path / _make_backup_name(CONFIG_YAML, "configset")
        backup.write_bytes(b"\xff\xfe invalid utf-8 \x80")
        with pytest.raises(BackupError, match="not UTF-8 text") as exc_info:
            restore_backup(tmp_path, backup.name)
        assert "manually" in str(exc_info.value)

    def test_dry_run_writes_nothing(self, tmp_path) -> None:
        backup = _write_backup(tmp_path, CONFIG_YAML, "goal: fix\n", "configset")
        (tmp_path / CONFIG_YAML).write_text("goal: changed\n", encoding="utf-8")
        outcome = restore_backup(tmp_path, backup.name, dry_run=True)
        assert outcome["dry_run"] is True
        assert outcome["restored"] is False
        assert (tmp_path / CONFIG_YAML).read_text(encoding="utf-8") == "goal: changed\n"
        # No restore-tagged backup was created either.
        assert not list(tmp_path.glob("*.restore-*"))

    def test_refuses_unrecognised_file(self, tmp_path) -> None:
        (tmp_path / "README.md").write_text("x", encoding="utf-8")
        with pytest.raises(BackupError, match="not an iterate backup"):
            restore_backup(tmp_path, "README.md")

    def test_refuses_path_outside_project(self, tmp_path) -> None:
        outside = tmp_path.parent / f"{uuid4().hex}.configset-20261104T120000Z-a1b2c3"
        outside.write_text("x", encoding="utf-8")
        with pytest.raises(BackupError, match="inside the project directory"):
            restore_backup(tmp_path, str(outside))
        outside.unlink()

    def test_refuses_absolute_path_outside_project(self, tmp_path) -> None:
        with pytest.raises(BackupError, match="inside the project directory"):
            restore_backup(tmp_path, "/etc/hosts")

    def test_refuses_directory_target(self, tmp_path) -> None:
        backup = _write_backup(tmp_path, CONFIG_YAML, "x", "configset")
        (tmp_path / CONFIG_YAML).unlink()  # target is a file now; replace it with a dir
        (tmp_path / CONFIG_YAML).mkdir()
        with pytest.raises(BackupError, match="is a directory"):
            restore_backup(tmp_path, backup.name)

    def test_refuses_missing_backup(self, tmp_path) -> None:
        name = _make_backup_name(CONFIG_YAML, "configset")
        with pytest.raises(BackupError, match="backup not found"):
            restore_backup(tmp_path, name)


# ---------------------------------------------------------------------------
# CLI layer
# ---------------------------------------------------------------------------


class TestBackupCli:
    def test_list_empty_exits_zero(self, tmp_path, capsys) -> None:
        capsys.readouterr()
        code = cli_main(["backup", "-p", str(tmp_path)])
        out = capsys.readouterr().out
        assert code == 0
        assert "No iterate backups found" in out

    def test_list_json_is_one_document(self, tmp_path, capsys) -> None:
        _write_backup(tmp_path, CONFIG_YAML, "goal: fix\n", "configset")
        capsys.readouterr()
        code = cli_main(["backup", "list", "-p", str(tmp_path), "--json"])
        out = capsys.readouterr().out
        assert code == 0
        payload = json.loads(out)  # must be exactly one JSON document
        assert payload["count"] == 1
        assert payload["backups"][0]["base"] == CONFIG_YAML
        assert payload["backups"][0]["operation"] == "config set"

    def test_list_json_empty_is_one_document(self, tmp_path, capsys) -> None:
        capsys.readouterr()
        code = cli_main(["backup", "-p", str(tmp_path), "--json"])
        out = capsys.readouterr().out
        assert code == 0
        payload = json.loads(out)
        assert payload["count"] == 0

    def test_restore_requires_a_file(self, tmp_path, capsys) -> None:
        capsys.readouterr()
        code = cli_main(["backup", "restore", "-p", str(tmp_path)])
        err = capsys.readouterr().err
        assert code == 2
        assert "no backup file given" in err

    def test_restore_non_interactive_without_yes_refuses(self, tmp_path, capsys) -> None:
        backup = _write_backup(tmp_path, CONFIG_YAML, "goal: fix\n", "configset")
        (tmp_path / CONFIG_YAML).write_text("goal: changed\n", encoding="utf-8")
        capsys.readouterr()
        code = cli_main(
            ["backup", "restore", backup.name, "-p", str(tmp_path)],
        )
        captured = capsys.readouterr()
        assert code == 2
        assert "Non-interactive stdin detected" in captured.err

    def test_restore_json_requires_yes(self, tmp_path, capsys) -> None:
        backup = _write_backup(tmp_path, CONFIG_YAML, "goal: fix\n", "configset")
        capsys.readouterr()
        code = cli_main(
            ["backup", "restore", backup.name, "-p", str(tmp_path), "--json"]
        )
        out = capsys.readouterr().out
        assert code == 2
        assert "--yes" in json.loads(out)["error"]

    def test_restore_dry_run_end_to_end(self, tmp_path, capsys) -> None:
        backup = _write_backup(tmp_path, CONFIG_YAML, "goal: fix\n", "configset")
        (tmp_path / CONFIG_YAML).write_text("goal: changed\n", encoding="utf-8")
        capsys.readouterr()
        code = cli_main(
            ["backup", "restore", backup.name, "-p", str(tmp_path), "--dry-run"]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "nothing was written" in out
        assert (tmp_path / CONFIG_YAML).read_text(encoding="utf-8") == "goal: changed\n"

    def test_restore_yes_end_to_end(self, tmp_path, capsys) -> None:
        backup = _write_backup(tmp_path, CONFIG_YAML, "goal: fix bugs\n", "configset")
        (tmp_path / CONFIG_YAML).write_text("goal: changed\n", encoding="utf-8")
        capsys.readouterr()
        code = cli_main(
            ["backup", "restore", backup.name, "-p", str(tmp_path), "--yes"]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "Restored" in out
        assert (tmp_path / CONFIG_YAML).read_text(encoding="utf-8") == "goal: fix bugs\n"
        # The pre-restore backup is listed so the undo path is discoverable.
        assert "restore-2026" in out

    def test_restore_json_success(self, tmp_path, capsys) -> None:
        backup = _write_backup(tmp_path, CONFIG_YAML, "goal: fix bugs\n", "configset")
        (tmp_path / CONFIG_YAML).write_text("goal: changed\n", encoding="utf-8")
        capsys.readouterr()
        code = cli_main(
            ["backup", "restore", backup.name, "-p", str(tmp_path), "--yes", "--json"]
        )
        out = capsys.readouterr().out
        assert code == 0
        payload = json.loads(out)
        assert payload["restored"] is True
        assert payload["base"] == CONFIG_YAML
        assert payload["pre_restore_backup"]

    def test_restore_refuses_unrecognised_file(self, tmp_path, capsys) -> None:
        (tmp_path / "README.md").write_text("x", encoding="utf-8")
        capsys.readouterr()
        code = cli_main(
            ["backup", "restore", "README.md", "-p", str(tmp_path), "--yes"]
        )
        err = capsys.readouterr().err
        assert code == 1
        assert "not an iterate backup" in err

    def test_help_lists_backup(self, capsys) -> None:
        capsys.readouterr()
        code = cli_main(["help", "backup"])
        out = capsys.readouterr().out
        assert code == 0
        assert "usage: iterate backup" in out
