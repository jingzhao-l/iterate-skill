"""Scalar-type coverage for the ``iterate status`` renderers.

A hand-edited (or AI-written) ``iterate.config.yaml`` can contain YAML scalars
that are not strings: an unquoted ``completed_at`` loads as ``datetime.date``,
``skill_version: 1.0`` as a float, ``channel: 2026`` as an int. Both renderers
used to pass those straight through — the TUI's display-width wrapper raised
``TypeError`` and ``--json`` aborted with no document at all, breaking the
"stdout holds exactly one JSON document" contract.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from iterate_cli.cli import main as cli_main

CONFIG = """\
dimensions:
  - correctness
validation:
  commands:
    python:
      - ruff check .
onboarding:
  completed_at: 2026-10-20
  channel: 2026
  skill_version: 1.0
  drift_check: false
  fingerprints: []
"""


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "ITERATE.md").write_text("# Project\n", encoding="utf-8")
    (project / "iterate.config.yaml").write_text(CONFIG, encoding="utf-8")
    return project


def test_status_json_serializes_yaml_scalars(tmp_path: Path, capsys) -> None:
    project = _project(tmp_path)
    capsys.readouterr()

    rc = cli_main(["--no-banner", "status", "--json", "-p", str(project)])
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    payload = json.loads(captured.out)  # exactly one document
    assert payload["onboarded"] is True
    assert payload["completed_at"] == "2026-10-20"
    # JSON-native scalars keep their type; only non-JSON YAML types (date) are
    # stringified by ``default=str``.
    assert payload["channel"] == 2026
    assert payload["skill_version"] == 1.0


def test_status_tui_renders_yaml_scalars(tmp_path: Path, capsys) -> None:
    project = _project(tmp_path)
    capsys.readouterr()

    rc = cli_main(["--no-banner", "status", "-p", str(project)])
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert rc == 0, combined
    assert "Traceback" not in combined
    assert "2026-10-20" in combined
    assert "1.0" in combined
