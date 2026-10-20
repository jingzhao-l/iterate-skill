"""Tests for ``iterate export`` / ``iterate import`` (portable bundles).

The two commands are the only supported way to move a project's iterate state
(``iterate.config.yaml`` + ``ITERATE.md``) between machines, repositories or a
review comment. The properties that matter:

* **Round-trip fidelity** — export → import reproduces both files exactly
  (semantically for YAML, byte-for-byte for Markdown).
* **Fail closed** — a foreign/corrupt/schema-invalid bundle is refused before a
  single byte is written, and the refusal is actionable.
* **Nothing is lost** — every overwrite leaves a timestamped backup, and an
  import without ``--yes`` on a non-interactive stdin refuses rather than
  hanging or silently applying.
* **``--json`` contract** — stdout holds exactly one JSON document on success,
  dry run and failure alike.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from iterate_cli.cli import main as cli_main
from iterate_cli.portable import (
    BUNDLE_FORMAT,
    BUNDLE_VERSION,
    MAX_BUNDLE_BYTES,
    BundleError,
    apply_bundle,
    build_bundle,
    bundle_to_json,
    default_bundle_name,
    diff_against_project,
    flatten_leaves,
    parse_bundle_text,
    strip_fingerprints,
    summarize_bundle,
    validate_bundle,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

CONFIG: dict[str, object] = {
    "goal": "Improve quality",
    "max_rounds": 5,
    "language": "en",
    "mode": "iterate",
    "dimensions": ["correctness", "security"],
    "validation": {"commands": {"python": ["pytest tests/ -q"]}},
    "onboarding": {
        "version": "1.0",
        "completed_at": "2026-10-01T00:00:00Z",
        "channel": "cli",
        "skill_version": "3.6.0",
        "drift_check": True,
        "fingerprints": [{"path": "pyproject.toml", "sha256": "a" * 64}],
    },
}

ITERATE_MD = "# Iterate — demo\n\n## Tech Stack\n\nPython\n"


def _write_project(
    root: Path, *, config: dict | None = CONFIG, md: str | None = ITERATE_MD
) -> Path:
    """Create a project skeleton; ``config=None``/``md=None`` skip that file."""
    root.mkdir(parents=True, exist_ok=True)
    if config is not None:
        (root / "iterate.config.yaml").write_text(
            yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    if md is not None:
        (root / "ITERATE.md").write_text(md, encoding="utf-8")
    return root


def _snapshot(root: Path) -> dict[str, int]:
    return {
        str(path.relative_to(root)): path.stat().st_size
        for path in sorted(root.rglob("*"))
    }


FIXED_NOW = datetime(2026, 10, 20, 9, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# build_bundle
# ---------------------------------------------------------------------------


class TestBuildBundle:
    def test_captures_config_and_markdown(self, tmp_path: Path) -> None:
        _write_project(tmp_path)
        bundle = build_bundle(tmp_path, now=FIXED_NOW)

        assert bundle["format"] == BUNDLE_FORMAT
        assert bundle["bundle_version"] == BUNDLE_VERSION
        assert bundle["exported_at"] == "2026-10-20T09:00:00Z"
        assert bundle["project"] == tmp_path.name
        assert bundle["config"] == CONFIG
        assert bundle["iterate_md"] == ITERATE_MD

    def test_missing_config_is_actionable(self, tmp_path: Path) -> None:
        with pytest.raises(BundleError) as excinfo:
            build_bundle(tmp_path)
        message = str(excinfo.value)
        assert "iterate.config.yaml" in message
        assert "iterate onboard" in message
        assert "iterate import" in message

    def test_invalid_yaml_names_the_file_and_the_doctor(self, tmp_path: Path) -> None:
        (tmp_path / "iterate.config.yaml").write_text("a: [\n", encoding="utf-8")
        with pytest.raises(BundleError) as excinfo:
            build_bundle(tmp_path)
        assert "not valid YAML" in str(excinfo.value)
        assert "iterate doctor" in str(excinfo.value)

    def test_non_mapping_config_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "iterate.config.yaml").write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(BundleError, match="must be a mapping"):
            build_bundle(tmp_path)

    def test_empty_config_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "iterate.config.yaml").write_text("", encoding="utf-8")
        with pytest.raises(BundleError, match="empty"):
            build_bundle(tmp_path)

    def test_absent_iterate_md_yields_null(self, tmp_path: Path) -> None:
        _write_project(tmp_path, md=None)
        assert build_bundle(tmp_path)["iterate_md"] is None

    def test_yaml_timestamps_become_json_strings(self, tmp_path: Path) -> None:
        """``yaml.safe_load`` returns ``date`` objects for unquoted timestamps;
        ``json.dumps`` would then raise TypeError during export."""
        (tmp_path / "iterate.config.yaml").write_text(
            "onboarding:\n  completed_at: 2026-10-01\n", encoding="utf-8"
        )
        bundle = build_bundle(tmp_path)
        assert bundle["config"]["onboarding"]["completed_at"] == "2026-10-01"
        json.dumps(bundle)  # must not raise

    def test_no_absolute_path_leaks(self, tmp_path: Path) -> None:
        _write_project(tmp_path)
        text = bundle_to_json(build_bundle(tmp_path))
        assert str(tmp_path) not in text

    def test_never_writes_to_the_project(self, tmp_path: Path) -> None:
        _write_project(tmp_path)
        before = _snapshot(tmp_path)
        build_bundle(tmp_path)
        assert _snapshot(tmp_path) == before


# ---------------------------------------------------------------------------
# validate_bundle / parse_bundle_text
# ---------------------------------------------------------------------------


def _valid_payload() -> dict:
    return {
        "format": BUNDLE_FORMAT,
        "bundle_version": BUNDLE_VERSION,
        "skill_version": "3.6.0",
        "exported_at": "2026-10-20T09:00:00Z",
        "project": "demo",
        "config": CONFIG,
        "iterate_md": ITERATE_MD,
    }


class TestValidateBundle:
    def test_valid_payload_has_no_errors(self) -> None:
        result = validate_bundle(_valid_payload())
        assert result.ok
        assert result.errors == []
        assert result.schema_checked is True

    def test_non_object_root(self) -> None:
        result = validate_bundle(["nope"])
        assert not result.ok
        assert "root must be a JSON object" in result.errors[0]

    def test_wrong_format(self) -> None:
        payload = _valid_payload()
        payload["format"] = "something-else"
        assert any("format must be" in error for error in validate_bundle(payload).errors)

    def test_newer_bundle_version_is_refused_with_upgrade_hint(self) -> None:
        payload = _valid_payload()
        payload["bundle_version"] = BUNDLE_VERSION + 1
        errors = validate_bundle(payload).errors
        assert any("newer iterate" in error and "iterate update" in error for error in errors)

    def test_non_integer_version(self) -> None:
        payload = _valid_payload()
        payload["bundle_version"] = "1"
        assert any("must be an integer" in e for e in validate_bundle(payload).errors)

    def test_bool_version_is_not_an_integer(self) -> None:
        payload = _valid_payload()
        payload["bundle_version"] = True
        assert any("must be an integer" in e for e in validate_bundle(payload).errors)

    def test_config_must_be_an_object(self) -> None:
        payload = _valid_payload()
        payload["config"] = "nope"
        assert any("config must be a JSON object" in e for e in validate_bundle(payload).errors)

    def test_empty_config_is_refused(self) -> None:
        payload = _valid_payload()
        payload["config"] = {}
        assert any("config is empty" in e for e in validate_bundle(payload).errors)

    def test_schema_violations_are_reported(self) -> None:
        payload = _valid_payload()
        payload["config"] = {"language": "fr"}
        errors = validate_bundle(payload).errors
        assert any("config" in error and "language" in error for error in errors)

    def test_iterate_md_must_be_string_or_null(self) -> None:
        payload = _valid_payload()
        payload["iterate_md"] = 3
        assert any("iterate_md must be a string or null" in e for e in validate_bundle(payload).errors)

    def test_blank_iterate_md_is_refused(self) -> None:
        payload = _valid_payload()
        payload["iterate_md"] = "  \n"
        assert any("present but empty" in e for e in validate_bundle(payload).errors)

    def test_absent_iterate_md_is_fine(self) -> None:
        payload = _valid_payload()
        payload.pop("iterate_md")
        assert validate_bundle(payload).ok

    def test_unknown_keys_only_warn(self) -> None:
        payload = _valid_payload()
        payload["future_field"] = {"anything": True}
        result = validate_bundle(payload)
        assert result.ok
        assert any("future_field" in warning for warning in result.warnings)

    def test_unavailable_schema_warns_instead_of_claiming_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from iterate_cli import portable

        monkeypatch.setattr(portable, "_schema_violations", lambda config: None)
        result = validate_bundle(_valid_payload())
        assert result.ok
        assert result.schema_checked is False
        assert any("not schema-checked" in warning for warning in result.warnings)


class TestParseBundleText:
    def test_round_trips_bundle_json(self, tmp_path: Path) -> None:
        _write_project(tmp_path)
        bundle = build_bundle(tmp_path)
        assert parse_bundle_text(bundle_to_json(bundle)) == bundle

    def test_invalid_json_reports_line_and_column(self) -> None:
        with pytest.raises(BundleError) as excinfo:
            parse_bundle_text("{not json", source="b.json")
        assert "b.json is not valid JSON" in str(excinfo.value)
        assert "line 1" in str(excinfo.value)

    def test_lists_every_error_at_once(self) -> None:
        payload = {"format": "x", "bundle_version": "y", "config": {}}
        with pytest.raises(BundleError) as excinfo:
            parse_bundle_text(json.dumps(payload), source="b.json")
        message = str(excinfo.value)
        assert message.count("\n  - ") == 3

    def test_oversized_document_is_refused(self) -> None:
        with pytest.raises(BundleError, match="larger than"):
            parse_bundle_text("x" * (MAX_BUNDLE_BYTES + 1), source="huge.json")


# ---------------------------------------------------------------------------
# flatten / diff / strip
# ---------------------------------------------------------------------------


class TestDiffHelpers:
    def test_flatten_treats_lists_as_leaves(self) -> None:
        flat = flatten_leaves({"a": {"b": 1}, "c": [1, 2], "d": {}})
        assert flat == {"a.b": 1, "c": [1, 2], "d": {}}

    def test_strip_fingerprints_removes_only_that_key(self) -> None:
        cleaned = strip_fingerprints(CONFIG)
        assert "fingerprints" not in cleaned["onboarding"]
        assert cleaned["onboarding"]["completed_at"] == "2026-10-01T00:00:00Z"
        assert cleaned["goal"] == CONFIG["goal"]
        # The input must not be mutated.
        assert CONFIG["onboarding"]["fingerprints"]

    def test_strip_fingerprints_drops_empty_section(self) -> None:
        cleaned = strip_fingerprints({"onboarding": {"fingerprints": []}})
        assert "onboarding" not in cleaned

    def test_diff_reports_added_changed_removed(self, tmp_path: Path) -> None:
        _write_project(
            tmp_path,
            config={
                "goal": "old goal",
                "max_rounds": 5,
                "obsolete": True,
                "onboarding": {"fingerprints": []},
            },
            md=None,
        )
        bundle = _valid_payload()
        changes = diff_against_project(tmp_path, bundle)

        assert "goal" in changes["config"]["changed"]
        assert "obsolete" in changes["config"]["removed"]
        assert "dimensions" in changes["config"]["added"]
        assert changes["iterate_md"] == "created"
        assert changes["would_write"] == ["iterate.config.yaml", "ITERATE.md"]

    def test_diff_marks_unchanged_markdown_and_config(self, tmp_path: Path) -> None:
        _write_project(tmp_path)
        changes = diff_against_project(tmp_path, _valid_payload())
        assert changes["config"] == {"added": [], "changed": [], "removed": []}
        assert changes["iterate_md"] == "unchanged"
        assert changes["would_write"] == ["iterate.config.yaml"]

    def test_diff_respects_reset_fingerprints(self, tmp_path: Path) -> None:
        _write_project(tmp_path, config={"goal": CONFIG["goal"]}, md=None)
        changes = diff_against_project(tmp_path, _valid_payload())
        assert any(
            key.startswith("onboarding.fingerprints")
            for key in changes["config"]["added"]
        )
        reset = diff_against_project(tmp_path, _valid_payload(), reset_fingerprints=True)
        assert not any(
            key.startswith("onboarding.fingerprints")
            for key in reset["config"]["added"]
        )

    def test_diff_survives_a_corrupt_current_config(self, tmp_path: Path) -> None:
        (tmp_path / "iterate.config.yaml").write_text("a: [\n", encoding="utf-8")
        changes = diff_against_project(tmp_path, _valid_payload())
        assert changes["config"]["added"]

    def test_summarize_is_json_serialisable(self) -> None:
        summary = summarize_bundle(_valid_payload())
        json.dumps(summary)
        assert summary["has_iterate_md"] is True
        assert summary["iterate_md_lines"] == ITERATE_MD.count("\n") + 1
        assert "goal" in summary["config_keys"]


# ---------------------------------------------------------------------------
# apply_bundle
# ---------------------------------------------------------------------------


class TestApplyBundle:
    def test_creates_both_files(self, tmp_path: Path) -> None:
        report = apply_bundle(tmp_path, _valid_payload(), now=FIXED_NOW)

        assert report["written"] == ["iterate.config.yaml", "ITERATE.md"]
        assert report["backups"] == []
        assert yaml.safe_load((tmp_path / "iterate.config.yaml").read_text()) == CONFIG
        assert (tmp_path / "ITERATE.md").read_text() == ITERATE_MD

    def test_existing_files_are_backed_up(self, tmp_path: Path) -> None:
        _write_project(tmp_path, config={"goal": "old"}, md="old md")
        report = apply_bundle(tmp_path, _valid_payload(), now=FIXED_NOW)

        assert len(report["backups"]) == 2
        for name in report["backups"]:
            assert name.startswith(
                ("iterate.config.yaml.import-", "ITERATE.md.import-")
            )
        original = next(n for n in report["backups"] if n.startswith("iterate.config"))
        assert "goal: old" in (tmp_path / original).read_text()

    def test_backup_names_are_unique_within_the_same_second(self, tmp_path: Path) -> None:
        _write_project(tmp_path, config={"goal": "old"}, md="old md")
        first = apply_bundle(tmp_path, _valid_payload(), now=FIXED_NOW)
        second = apply_bundle(tmp_path, _valid_payload(), now=FIXED_NOW)
        assert set(first["backups"]).isdisjoint(second["backups"])

    def test_absent_iterate_md_leaves_existing_markdown_alone(
        self, tmp_path: Path
    ) -> None:
        _write_project(tmp_path, config={"goal": "old"}, md="keep me")
        payload = _valid_payload()
        payload["iterate_md"] = None
        report = apply_bundle(tmp_path, payload, now=FIXED_NOW)

        assert (tmp_path / "ITERATE.md").read_text() == "keep me"
        assert report["written"] == ["iterate.config.yaml"]

    def test_reset_fingerprints_removes_the_baseline(self, tmp_path: Path) -> None:
        apply_bundle(tmp_path, _valid_payload(), reset_fingerprints=True)
        written = yaml.safe_load((tmp_path / "iterate.config.yaml").read_text())
        assert "fingerprints" not in written["onboarding"]

    def test_write_failure_is_reported_as_bundle_error(self, tmp_path: Path) -> None:
        with pytest.raises(BundleError, match="Failed to write"):
            apply_bundle(tmp_path / "missing", _valid_payload())


# ---------------------------------------------------------------------------
# CLI: export
# ---------------------------------------------------------------------------


class TestExportCli:
    def test_json_prints_one_bundle_and_writes_nothing(
        self, tmp_path: Path, capsys
    ) -> None:
        _write_project(tmp_path)
        before = _snapshot(tmp_path)
        capsys.readouterr()
        code = cli_main(["export", "--json", "-p", str(tmp_path), "--no-banner"])

        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["format"] == BUNDLE_FORMAT
        assert payload["config"] == CONFIG
        assert _snapshot(tmp_path) == before

    def test_out_dash_equals_json(self, tmp_path: Path, capsys) -> None:
        _write_project(tmp_path)
        capsys.readouterr()
        code = cli_main(
            ["export", "--out", "-", "-p", str(tmp_path), "--no-banner"]
        )
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["format"] == BUNDLE_FORMAT

    def test_default_writes_a_timestamped_file(self, tmp_path: Path, capsys) -> None:
        _write_project(tmp_path)
        capsys.readouterr()
        code = cli_main(["export", "-p", str(tmp_path), "--no-banner"])

        produced = list(tmp_path.glob("iterate-bundle-*.json"))
        assert code == 0
        assert len(produced) == 1
        assert json.loads(produced[0].read_text())["format"] == BUNDLE_FORMAT
        assert "Bundle written" in capsys.readouterr().out

    def test_out_path_is_honoured(self, tmp_path: Path, capsys) -> None:
        _write_project(tmp_path)
        target = tmp_path / "snapshot.json"
        capsys.readouterr()
        assert cli_main(
            ["export", "--out", str(target), "-p", str(tmp_path), "--no-banner"]
        ) == 0
        assert json.loads(target.read_text())["project"] == tmp_path.name

    def test_refuses_to_overwrite_without_force(self, tmp_path: Path, capsys) -> None:
        _write_project(tmp_path)
        target = tmp_path / "snapshot.json"
        target.write_text("{}", encoding="utf-8")
        capsys.readouterr()
        code = cli_main(
            ["export", "--out", str(target), "-p", str(tmp_path), "--no-banner"]
        )
        assert code == 1
        assert target.read_text() == "{}"
        assert "--force" in capsys.readouterr().err

    def test_force_overwrites(self, tmp_path: Path, capsys) -> None:
        _write_project(tmp_path)
        target = tmp_path / "snapshot.json"
        target.write_text("{}", encoding="utf-8")
        capsys.readouterr()
        assert cli_main(
            ["export", "--out", str(target), "--force", "-p", str(tmp_path), "--no-banner"]
        ) == 0
        assert json.loads(target.read_text())["format"] == BUNDLE_FORMAT

    def test_json_with_out_is_a_usage_error(self, tmp_path: Path, capsys) -> None:
        _write_project(tmp_path)
        capsys.readouterr()
        code = cli_main(
            ["export", "--json", "--out", str(tmp_path / "x.json"),
             "-p", str(tmp_path), "--no-banner"]
        )
        payload = json.loads(capsys.readouterr().out)
        assert code == 2
        assert "drop --out" in payload["error"]
        assert not (tmp_path / "x.json").exists()

    def test_missing_parent_directory_is_reported(self, tmp_path: Path, capsys) -> None:
        _write_project(tmp_path)
        capsys.readouterr()
        code = cli_main(
            ["export", "--out", str(tmp_path / "nope" / "x.json"),
             "-p", str(tmp_path), "--no-banner"]
        )
        assert code == 1
        assert "parent directory does not exist" in capsys.readouterr().err

    def test_missing_config_emits_one_json_error(self, tmp_path: Path, capsys) -> None:
        capsys.readouterr()
        code = cli_main(["export", "--json", "-p", str(tmp_path), "--no-banner"])
        payload = json.loads(capsys.readouterr().out)
        assert code == 1
        assert "iterate onboard" in payload["error"]

    def test_default_bundle_name_is_utc_and_timestamped(self) -> None:
        assert default_bundle_name(FIXED_NOW) == "iterate-bundle-20261020T090000Z.json"


# ---------------------------------------------------------------------------
# CLI: import
# ---------------------------------------------------------------------------


def _write_bundle(tmp_path: Path, payload: dict | None = None) -> Path:
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(payload or _valid_payload()), encoding="utf-8")
    return path


class TestImportCli:
    def test_yes_applies_and_reports_json(self, tmp_path: Path, capsys) -> None:
        source = _write_project(tmp_path / "src")
        bundle = _write_bundle(tmp_path)
        target = tmp_path / "dst"
        target.mkdir()
        capsys.readouterr()

        code = cli_main(
            ["import", str(bundle), "--yes", "--json", "-p", str(target), "--no-banner"]
        )
        payload = json.loads(capsys.readouterr().out)

        assert code == 0
        assert payload["ok"] is True
        assert payload["written"] == ["iterate.config.yaml", "ITERATE.md"]
        assert (target / "ITERATE.md").read_text() == (source / "ITERATE.md").read_text()

    def test_dry_run_writes_nothing(self, tmp_path: Path, capsys) -> None:
        bundle = _write_bundle(tmp_path)
        target = tmp_path / "dst"
        target.mkdir()
        capsys.readouterr()

        code = cli_main(
            ["import", str(bundle), "--dry-run", "--json", "-p", str(target), "--no-banner"]
        )
        payload = json.loads(capsys.readouterr().out)

        assert code == 0
        assert payload["dry_run"] is True
        assert payload["would_write"] == ["iterate.config.yaml", "ITERATE.md"]
        assert list(target.iterdir()) == []

    def test_dry_run_tui_previews_without_writing(self, tmp_path: Path, capsys) -> None:
        bundle = _write_bundle(tmp_path)
        target = tmp_path / "dst"
        target.mkdir()
        capsys.readouterr()

        code = cli_main(
            ["import", str(bundle), "--dry-run", "-p", str(target), "--no-banner"]
        )
        out = capsys.readouterr().out

        assert code == 0
        assert "Import preview" in out
        assert "Dry run: nothing was written" in out
        assert list(target.iterdir()) == []

    def test_non_interactive_without_yes_refuses(self, tmp_path: Path, capsys, monkeypatch) -> None:
        bundle = _write_bundle(tmp_path)
        target = tmp_path / "dst"
        target.mkdir()
        monkeypatch.setattr("iterate_cli.cli._stdin_is_interactive", lambda: False)
        capsys.readouterr()

        code = cli_main(["import", str(bundle), "-p", str(target), "--no-banner"])

        assert code == 1
        assert "--yes" in capsys.readouterr().err
        assert list(target.iterdir()) == []

    def test_json_without_yes_is_refused(self, tmp_path: Path, capsys, monkeypatch) -> None:
        bundle = _write_bundle(tmp_path)
        target = tmp_path / "dst"
        target.mkdir()
        monkeypatch.setattr("iterate_cli.cli._stdin_is_interactive", lambda: True)
        capsys.readouterr()

        code = cli_main(
            ["import", str(bundle), "--json", "-p", str(target), "--no-banner"]
        )
        payload = json.loads(capsys.readouterr().out)

        assert code == 2
        assert "requires --yes" in payload["error"]

    def test_interactive_decline_writes_nothing(self, tmp_path: Path, capsys, monkeypatch) -> None:
        bundle = _write_bundle(tmp_path)
        target = tmp_path / "dst"
        target.mkdir()
        monkeypatch.setattr("iterate_cli.cli._stdin_is_interactive", lambda: True)
        monkeypatch.setattr("iterate_cli.cli._confirm", lambda *a, **k: False)
        capsys.readouterr()

        code = cli_main(["import", str(bundle), "-p", str(target), "--no-banner"])

        assert code == 1
        assert list(target.iterdir()) == []

    def test_stdin_bundle(self, tmp_path: Path, capsys, monkeypatch) -> None:
        import io

        target = tmp_path / "dst"
        target.mkdir()
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_valid_payload())))
        capsys.readouterr()

        code = cli_main(
            ["import", "-", "--yes", "--json", "-p", str(target), "--no-banner"]
        )
        payload = json.loads(capsys.readouterr().out)

        assert code == 0
        assert payload["source"] == "<stdin>"
        assert (target / "iterate.config.yaml").is_file()

    def test_missing_bundle_file(self, tmp_path: Path, capsys) -> None:
        target = tmp_path / "dst"
        target.mkdir()
        capsys.readouterr()
        code = cli_main(
            ["import", str(tmp_path / "nope.json"), "--json",
             "-p", str(target), "--no-banner"]
        )
        payload = json.loads(capsys.readouterr().out)
        assert code == 1
        assert "not found" in payload["error"]

    def test_foreign_bundle_is_refused_before_writing(self, tmp_path: Path, capsys) -> None:
        bundle = _write_bundle(tmp_path, {"format": "other", "bundle_version": 1, "config": CONFIG})
        target = tmp_path / "dst"
        target.mkdir()
        capsys.readouterr()

        code = cli_main(
            ["import", str(bundle), "--yes", "--json", "-p", str(target), "--no-banner"]
        )
        payload = json.loads(capsys.readouterr().out)

        assert code == 1
        assert "format must be" in payload["error"]
        assert list(target.iterdir()) == []

    def test_schema_invalid_config_is_refused_before_writing(self, tmp_path: Path, capsys) -> None:
        payload = _valid_payload()
        payload["config"] = {"language": "fr"}
        bundle = _write_bundle(tmp_path, payload)
        target = tmp_path / "dst"
        target.mkdir()
        capsys.readouterr()

        code = cli_main(
            ["import", str(bundle), "--yes", "--json", "-p", str(target), "--no-banner"]
        )
        assert code == 1
        assert "language" in json.loads(capsys.readouterr().out)["error"]
        assert list(target.iterdir()) == []

    def test_backups_are_reported(self, tmp_path: Path, capsys) -> None:
        _write_project(tmp_path / "dst", config={"goal": "old"}, md="old")
        bundle = _write_bundle(tmp_path)
        capsys.readouterr()

        code = cli_main(
            ["import", str(bundle), "--yes", "--json", "-p", str(tmp_path / "dst"),
             "--no-banner"]
        )
        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert len(payload["backups"]) == 2

    def test_reset_fingerprints_flag_is_reported(self, tmp_path: Path, capsys) -> None:
        bundle = _write_bundle(tmp_path)
        target = tmp_path / "dst"
        target.mkdir()
        capsys.readouterr()

        code = cli_main(
            ["import", str(bundle), "--yes", "--reset-fingerprints", "--json",
             "-p", str(target), "--no-banner"]
        )
        payload = json.loads(capsys.readouterr().out)

        assert code == 0
        assert payload["fingerprints_reset"] is True
        written = yaml.safe_load((target / "iterate.config.yaml").read_text())
        assert "fingerprints" not in written["onboarding"]

    def test_export_then_import_round_trips_faithfully(self, tmp_path: Path, capsys) -> None:
        source = _write_project(tmp_path / "src")
        target = tmp_path / "dst"
        target.mkdir()
        capsys.readouterr()

        assert cli_main(["export", "--json", "-p", str(source), "--no-banner"]) == 0
        exported = json.loads(capsys.readouterr().out)
        bundle = tmp_path / "bundle.json"
        bundle.write_text(json.dumps(exported), encoding="utf-8")

        assert cli_main(
            ["import", str(bundle), "--yes", "-p", str(target), "--no-banner"]
        ) == 0
        capsys.readouterr()

        assert yaml.safe_load((target / "iterate.config.yaml").read_text()) == CONFIG
        assert (target / "ITERATE.md").read_text() == ITERATE_MD

    def test_imported_config_passes_doctor(self, tmp_path: Path, capsys) -> None:
        """An accepted bundle must leave a project the very next command agrees
        is healthy — otherwise import "succeeded" into a broken state."""
        bundle = _write_bundle(tmp_path)
        target = tmp_path / "dst"
        target.mkdir()
        capsys.readouterr()
        assert cli_main(
            ["import", str(bundle), "--yes", "-p", str(target), "--no-banner"]
        ) == 0
        capsys.readouterr()

        code = cli_main(["doctor", "--json", "-p", str(target), "--no-banner"])
        report = json.loads(capsys.readouterr().out)
        config_errors = [
            finding
            for finding in report["findings"]
            if finding["severity"] == "error"
            and finding["check"].startswith("config.")
        ]
        assert config_errors == [], config_errors
        assert report["healthy"] is True
        assert code == 0


# ---------------------------------------------------------------------------
# Discoverability
# ---------------------------------------------------------------------------


class TestPortableIsDiscoverable:
    def test_both_commands_appear_in_top_level_help(self) -> None:
        from iterate_cli.cli import _build_parser

        text = _build_parser().format_help()
        assert "export" in text
        assert "import" in text

    def test_iterate_help_export_and_import(self, capsys) -> None:
        for command in ("export", "import"):
            capsys.readouterr()
            assert cli_main(["help", command]) == 0
            assert f"usage: iterate {command}" in capsys.readouterr().out

    def test_json_help_lists_both_commands(self) -> None:
        from iterate_cli.cli import _build_parser

        parser = _build_parser()
        json_help = next(
            action.help
            for action in parser._actions
            if "--json" in getattr(action, "option_strings", [])
        )
        assert "export" in (json_help or "")
        assert "import" in (json_help or "")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
