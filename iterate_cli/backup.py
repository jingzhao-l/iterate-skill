"""Backup inspection and restore (``iterate backup``).

The CLI writes a timestamped copy of a file beside itself before every
mutation — ``config set``/``config unset`` (``*.configset-*`` /
``*.configunset-*``), ``doctor --fix`` (``*.doctorfix-*``), ``refresh`` /
``personalize`` / ``onboard`` (``*.refresh-*`` / ``*.personalize-*`` /
``*.onboard-*``), ``import`` (``*.import-*``) and ``reonboard``
(``*.bak-*``). Until now there was **no way to see or restore them**: a user
who needed to undo a bad ``config set`` had to ``ls`` the project directory
and guess which of the ``*.configset-*`` files was the pre-change copy, or
re-run the interactive wizard and hope.

This module closes that gap. ``iterate backup list`` enumerates every
recognisable backup in the project root (newest first, with the original
file, the operation that wrote it, and the UTC timestamp). ``iterate backup
restore FILE`` puts one back: the current file is itself backed up first
(tagged ``restore``) so a restore is reversible, then the backup content is
written to the original path. A restore never touches a file that does not
look like an iterate backup, never leaves the project root, and is refused
when the target is a directory.

The CLI layer (``iterate_cli/cli.py``) handles I/O, prompts and exit codes;
everything here is pure and unit-testable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from iterate_cli.generator import atomic_write, backup_file

#: Every tag the CLI uses when it copies a file aside before rewriting it,
#: plus the ``restore`` tag this module writes before overwriting a target so
#: a restore is itself reversible. Keeping the list here (rather than in the
#: regex literal) lets ``list`` label each backup with the operation that
#: created it.
BACKUP_TAGS: tuple[str, ...] = (
    "configset",
    "configunset",
    "doctorfix",
    "refresh",
    "personalize",
    "onboard",
    "import",
    "bak",
    "restore",
)

#: Human label for each tag, shown in the TUI listing. Unknown tags fall back
#: to the raw tag so a future tag added elsewhere still renders.
TAG_LABELS: dict[str, str] = {
    "configset": "config set",
    "configunset": "config unset",
    "doctorfix": "doctor --fix",
    "refresh": "refresh",
    "personalize": "personalize",
    "onboard": "onboard",
    "import": "import",
    "bak": "reonboard",
    "restore": "restore",
}

#: ``<base>.<tag>-<UTCstamp>-<salt>`` where tag is one of BACKUP_TAGS, stamp
#: is ``YYYYMMDDTHHMMSSZ`` and salt is 6 hex chars (``uuid4().hex[:6]``).
#: Anchored and greedy on the base so ``iterate.config.yaml.configset-…``
#: yields base ``iterate.config.yaml``, not ``iterate.config``.
_BACKUP_RE = re.compile(
    r"^(?P<base>.+)\.(?P<tag>configset|configunset|doctorfix|refresh|"
    r"personalize|onboard|import|bak|restore)-"
    r"(?P<stamp>\d{8}T\d{6}Z)-(?P<salt>[0-9a-f]{6})$"
)


class BackupError(Exception):
    """A backup could not be listed or restored.

    The message is user-facing and always states what to do next; the CLI
    prints it verbatim (to stdout as ``{"error": ...}`` under ``--json``).
    """


@dataclass(frozen=True)
class BackupEntry:
    """One recognisable backup file in the project root.

    Attributes:
        path: Absolute path of the backup file.
        base: The original file the backup was taken from (its filename).
        tag: The operation tag that created it (one of ``BACKUP_TAGS``).
        stamp: The ``YYYYMMDDTHHMMSSZ`` UTC timestamp component.
        size: Backup file size in bytes.
    """

    path: Path
    base: str
    tag: str
    stamp: str
    size: int

    @property
    def timestamp(self) -> datetime:
        """The backup's UTC timestamp, timezone-aware."""
        return datetime.strptime(self.stamp, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )

    @property
    def label(self) -> str:
        """Human-readable operation label for the TUI listing."""
        return TAG_LABELS.get(self.tag, self.tag)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable representation."""
        return {
            "path": str(self.path),
            "name": self.path.name,
            "base": self.base,
            "tag": self.tag,
            "operation": self.label,
            "timestamp": self.timestamp.isoformat(),
            "size": self.size,
        }


def _parse_backup_name(name: str) -> tuple[str, str, str] | None:
    """Split a backup filename into ``(base, tag, stamp)`` or None.

    Returns None when ``name`` is not a recognisable iterate backup, so callers
    can refuse to touch unrelated files.
    """
    match = _BACKUP_RE.match(name)
    if not match:
        return None
    return match.group("base"), match.group("tag"), match.group("stamp")


def list_backups(project_root: Path) -> list[BackupEntry]:
    """Return every recognisable backup file under ``project_root``.

    Newest first (by UTC timestamp, then by salt as a stable tie-break). A
    project with no backups returns an empty list — that is informational, not
    an error.
    """
    entries: list[BackupEntry] = []
    try:
        children = list(project_root.iterdir())
    except OSError as exc:
        raise BackupError(f"cannot read project directory {project_root}: {exc}") from exc
    for path in children:
        if not path.is_file():
            continue
        parsed = _parse_backup_name(path.name)
        if parsed is None:
            continue
        base, tag, stamp = parsed
        try:
            size = path.stat().st_size
        except OSError:
            continue  # raced away or unreadable; skip rather than fail the listing
        entries.append(BackupEntry(path=path, base=base, tag=tag, stamp=stamp, size=size))
    entries.sort(key=lambda e: (e.stamp, e.path.name), reverse=True)
    return entries


def restore_backup(
    project_root: Path,
    backup_arg: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Restore one backup file to its original name.

    The backup is resolved against ``project_root`` and must be a recognisable
    iterate backup file (see :func:`_parse_backup_name`). Before the target is
    overwritten, the *current* target is itself backed up (tag ``restore``), so
    the restore is reversible; then the backup content is written to the target
    atomically. ``--dry-run`` reports everything without writing.

    Returns a JSON-serialisable outcome dict::

        {
            "ok": True,
            "dry_run": bool,
            "backup": str,            # the restored backup path
            "target": str,            # the original path restored to
            "base": str,              # original filename
            "tag": str,               # operation that made the backup
            "operation": str,         # human label
            "timestamp": str,         # backup UTC ISO timestamp
            "pre_restore_backup": str | None,  # fresh backup of the current
                                               # target, or None when the
                                               # target did not exist
            "restored": bool,
        }

    Raises:
        BackupError: If the argument is not a recognisable backup, points
            outside the project root, names a directory target, or the write
            fails.
    """
    # Resolve the backup path against the project root and refuse anything that
    # escapes it (a symlink, an absolute path, or a ``../`` traversal).
    backup_path = Path(backup_arg)
    if not backup_path.is_absolute():
        backup_path = project_root / backup_path
    try:
        backup_resolved = backup_path.resolve()
        project_resolved = project_root.resolve()
        backup_resolved.relative_to(project_resolved)
    except (OSError, ValueError) as exc:
        raise BackupError(
            f"backup must be inside the project directory {project_root}: {backup_arg}"
        ) from exc

    parsed = _parse_backup_name(backup_resolved.name)
    if parsed is None:
        raise BackupError(
            f"{backup_resolved.name} is not an iterate backup "
            "(expected <file>.<tag>-<UTCstamp>-<salt>, e.g. "
            "iterate.config.yaml.configset-20261101T091500Z-a1b2c3). "
            "Run `iterate backup list` to see the available backups."
        )
    if not backup_resolved.is_file():
        raise BackupError(
            f"backup not found: {backup_resolved} (run `iterate backup list` "
            "to see the available backups)"
        )

    base, tag, stamp = parsed
    target = backup_resolved.parent / base

    if target.is_dir():
        raise BackupError(
            f"cannot restore {backup_resolved.name}: {base} is a directory, "
            "not a file"
        )
    if target == backup_resolved:
        raise BackupError(
            f"cannot restore {backup_resolved.name}: it is already the live file"
        )

    target_exists = target.is_file()
    pre_restore_backup: str | None = None

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "backup": str(backup_resolved),
            "target": str(target),
            "base": base,
            "tag": tag,
            "operation": TAG_LABELS.get(tag, tag),
            "timestamp": datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")
            .replace(tzinfo=timezone.utc)
            .isoformat(),
            "pre_restore_backup": None,
            "restored": False,
        }

    try:
        content = backup_resolved.read_text(encoding="utf-8")
        # Back up the current target so the restore can be undone. If the
        # target does not exist there is nothing to preserve; the restore
        # simply recreates it.
        if target_exists:
            pre_restore_backup = backup_file(target, "restore")
        atomic_write(target, content)
    except (OSError, UnicodeDecodeError) as exc:
        raise BackupError(f"failed to restore {backup_resolved.name}: {exc}") from exc

    return {
        "ok": True,
        "dry_run": False,
        "backup": str(backup_resolved),
        "target": str(target),
        "base": base,
        "tag": tag,
        "operation": TAG_LABELS.get(tag, tag),
        "timestamp": datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")
        .replace(tzinfo=timezone.utc)
        .isoformat(),
        "pre_restore_backup": str(pre_restore_backup) if pre_restore_backup else None,
        "restored": True,
    }


def backups_json(project_root: Path, backups: list[BackupEntry]) -> str:
    """Serialise a listing as the single ``--json`` document."""
    return json.dumps(
        {
            "project": str(project_root),
            "count": len(backups),
            "backups": [entry.to_dict() for entry in backups],
        },
        ensure_ascii=False,
        indent=2,
    )
