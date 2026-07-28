"""Tests for iterate_cli onboarding modules.

Covers fingerprint, scan, generator, wizard, refresh, and CLI with
normal paths, error paths, and boundary scenarios.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

# Make iterate_cli and scripts importable.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from iterate_cli.fingerprint import (
    FINGERPRINT_VERSION,
    FingerprintEntry,
    compare_fingerprints,
    compute_sha256,
    capture_fingerprints,
    check_drift,
    fingerprints_from_dict,
    fingerprints_to_dict,
    scan_manifests,
)
from iterate_cli.scan import (
    ScanResult,
    scan_project,
    suggest_command_whitelist,
    suggest_dimensions,
    suggest_validation_commands,
)
from iterate_cli.generator import (
    AI_START_MARKER,
    AI_END_MARKER,
    USER_START_MARKER,
    USER_END_MARKER,
    OnboardingData,
    extract_user_owned_section,
    generate_config_yaml,
    generate_iterate_md,
    generate_refreshed_md,
    write_onboarding_outputs,
)
from iterate_cli.wizard import (
    ALL_DIMENSIONS,
    run_wizard,
    _parse_dimension_selection,
    _ask_yes_no,
)
from iterate_cli.refresh import (
    check_onboarding_drift,
    full_reonboard,
    incremental_refresh,
    is_onboarding_complete,
    load_onboarding_config,
)
from iterate_cli.cli import main as cli_main


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    """Create a minimal fake project with a Python manifest."""
    project = tmp_path / "myproject"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "myproject"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (project / "src").mkdir()
    (project / "tests").mkdir()
    return project


@pytest.fixture
def fake_multi_project(tmp_path: Path) -> Path:
    """Create a project with multiple manifests and frontend indicators."""
    project = tmp_path / "fullstack"
    project.mkdir()
    (project / "package.json").write_text(
        '{"name": "fullstack", "version": "1.0.0"}',
        encoding="utf-8",
    )
    (project / "tsconfig.json").write_text(
        '{"compilerOptions": {"target": "es2020"}}',
        encoding="utf-8",
    )
    (project / "src").mkdir()
    (project / "src" / "pages").mkdir()
    (project / "src" / "components").mkdir()
    (project / "tests").mkdir()
    (project / "specs").mkdir()
    (project / ".github").mkdir()
    (project / ".github" / "workflows").mkdir()
    (project / "README.md").write_text("# Fullstack Project", encoding="utf-8")
    return project


@pytest.fixture
def empty_project(tmp_path: Path) -> Path:
    """Create an empty project directory with no manifests."""
    project = tmp_path / "empty"
    project.mkdir()
    return project


def _build_onboarding_data(project_root: Path, scan: ScanResult | None = None) -> OnboardingData:
    """Helper: build minimal OnboardingData for generator tests."""
    if scan is None:
        scan = scan_project(project_root)
    return OnboardingData(
        project_root=project_root,
        channel="cli",
        scan=scan,
        project_description="Test project",
        code_conventions="Use 4-space indentation",
        dimensions=suggest_dimensions(scan),
        target_branch="main",
        review_scope="full",
        push_per_round=True,
        validation_commands=suggest_validation_commands(scan),
        command_whitelist=suggest_command_whitelist(scan),
        fingerprints=capture_fingerprints(project_root),
    )


# ---------------------------------------------------------------------------
# Fingerprint tests
# ---------------------------------------------------------------------------

class TestComputeSha256:
    def test_hash_is_correct(self, tmp_path: Path) -> None:
        path = tmp_path / "test.txt"
        content = b"hello world"
        path.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert compute_sha256(path) == expected

    def test_hash_is_hex_string(self, tmp_path: Path) -> None:
        path = tmp_path / "test.txt"
        path.write_bytes(b"data")
        result = compute_sha256(path)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            compute_sha256(tmp_path / "nonexistent.txt")

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_bytes(b"content_a")
        f2.write_bytes(b"content_b")
        assert compute_sha256(f1) != compute_sha256(f2)


class TestScanManifests:
    def test_finds_existing_manifests(self, fake_project: Path) -> None:
        result = scan_manifests(fake_project)
        names = [p.name for p in result]
        assert "pyproject.toml" in names

    def test_finds_multiple_manifests(self, fake_multi_project: Path) -> None:
        result = scan_manifests(fake_multi_project)
        names = [p.name for p in result]
        assert "package.json" in names
        assert "tsconfig.json" in names

    def test_empty_project_returns_empty(self, empty_project: Path) -> None:
        assert scan_manifests(empty_project) == []

    def test_sorted_by_name(self, fake_multi_project: Path) -> None:
        result = scan_manifests(fake_multi_project)
        names = [p.name for p in result]
        assert names == sorted(names)


class TestCaptureFingerprints:
    def test_captures_all_manifests(self, fake_project: Path) -> None:
        entries = capture_fingerprints(fake_project)
        assert len(entries) == 1
        assert entries[0].path == "pyproject.toml"
        assert len(entries[0].sha256) == 64

    def test_empty_project(self, empty_project: Path) -> None:
        assert capture_fingerprints(empty_project) == []


class TestFingerprintSerialization:
    def test_roundtrip(self) -> None:
        entries = [
            FingerprintEntry(path="package.json", sha256="a" * 64),
            FingerprintEntry(path="pyproject.toml", sha256="b" * 64),
        ]
        dicts = fingerprints_to_dict(entries)
        restored = fingerprints_from_dict(dicts)
        assert restored == entries

    def test_from_dict_invalid_entry(self) -> None:
        with pytest.raises(ValueError, match="not a dict"):
            fingerprints_from_dict(["not a dict"])  # type: ignore[list-item]

    def test_from_dict_missing_path(self) -> None:
        with pytest.raises(ValueError, match="missing 'path'"):
            fingerprints_from_dict([{"sha256": "a" * 64}])

    def test_from_dict_missing_sha256(self) -> None:
        with pytest.raises(ValueError, match="missing 'sha256'"):
            fingerprints_from_dict([{"path": "package.json"}])


class TestCompareFingerprints:
    def test_no_drift(self) -> None:
        stored = [{"path": "package.json", "sha256": "a" * 64}]
        current = [{"path": "package.json", "sha256": "a" * 64}]
        result = compare_fingerprints(stored, current)
        assert not result.has_drift
        assert "package.json" in result.unchanged

    def test_changed(self) -> None:
        stored = [{"path": "package.json", "sha256": "a" * 64}]
        current = [{"path": "package.json", "sha256": "b" * 64}]
        result = compare_fingerprints(stored, current)
        assert result.has_drift
        assert "package.json" in result.changed

    def test_added(self) -> None:
        stored = []
        current = [{"path": "package.json", "sha256": "a" * 64}]
        result = compare_fingerprints(stored, current)
        assert result.has_drift
        assert "package.json" in result.added

    def test_removed(self) -> None:
        stored = [{"path": "package.json", "sha256": "a" * 64}]
        current = []
        result = compare_fingerprints(stored, current)
        assert result.has_drift
        assert "package.json" in result.removed

    def test_summary_no_drift(self) -> None:
        result = compare_fingerprints([], [])
        assert result.summary() == "No drift detected."

    def test_summary_with_drift(self) -> None:
        stored = [{"path": "a", "sha256": "1" * 64}]
        current = [{"path": "b", "sha256": "2" * 64}]
        result = compare_fingerprints(stored, current)
        summary = result.summary()
        assert "added: b" in summary
        assert "removed: a" in summary


class TestCheckDrift:
    def test_drift_detected_on_change(self, fake_project: Path) -> None:
        entries = capture_fingerprints(fake_project)
        stored = fingerprints_to_dict(entries)
        # Modify the manifest.
        (fake_project / "pyproject.toml").write_text("changed", encoding="utf-8")
        result = check_drift(fake_project, stored)
        assert result.has_drift
        assert "pyproject.toml" in result.changed

    def test_no_drift_when_unchanged(self, fake_project: Path) -> None:
        entries = capture_fingerprints(fake_project)
        stored = fingerprints_to_dict(entries)
        result = check_drift(fake_project, stored)
        assert not result.has_drift


# ---------------------------------------------------------------------------
# Scan tests
# ---------------------------------------------------------------------------

class TestScanProject:
    def test_python_project(self, fake_project: Path) -> None:
        result = scan_project(fake_project)
        assert "pyproject.toml" in result.manifests
        assert "Python" in result.detected_languages
        assert "src" in result.top_level_dirs
        assert result.has_tests is True

    def test_fullstack_project(self, fake_multi_project: Path) -> None:
        result = scan_project(fake_multi_project)
        assert "JavaScript/TypeScript" in result.detected_languages
        assert result.has_frontend is True
        assert result.has_specs is True
        assert result.has_ci is True
        assert result.has_readme is True

    def test_empty_project(self, empty_project: Path) -> None:
        result = scan_project(empty_project)
        assert result.manifests == []
        assert result.detected_languages == []
        assert not result.has_specs
        assert not result.has_tests


class TestSuggestDimensions:
    def test_python_project_suggests_base_dims(self, fake_project: Path) -> None:
        scan = scan_project(fake_project)
        dims = suggest_dimensions(scan)
        assert "correctness" in dims
        assert "security" in dims
        assert "ui-ux" not in dims

    def test_frontend_project_suggests_ui_ux(self, fake_multi_project: Path) -> None:
        scan = scan_project(fake_multi_project)
        dims = suggest_dimensions(scan)
        assert "ui-ux" in dims
        assert "frontend-backend" in dims
        assert "spec-compliance" in dims

    def test_empty_project(self, empty_project: Path) -> None:
        scan = scan_project(empty_project)
        dims = suggest_dimensions(scan)
        assert "correctness" in dims
        assert "ui-ux" not in dims


class TestSuggestValidationCommands:
    def test_python_commands(self, fake_project: Path) -> None:
        scan = scan_project(fake_project)
        cmds = suggest_validation_commands(scan)
        assert "python" in cmds
        assert any("ruff" in c for c in cmds["python"])
        assert any("pytest" in c for c in cmds["python"])

    def test_empty_project(self, empty_project: Path) -> None:
        scan = scan_project(empty_project)
        assert suggest_validation_commands(scan) == {}


class TestSuggestCommandWhitelist:
    def test_python_whitelist(self, fake_project: Path) -> None:
        scan = scan_project(fake_project)
        wl = suggest_command_whitelist(scan)
        assert "ruff" in wl
        assert "pytest" in wl

    def test_no_duplicates(self, fake_multi_project: Path) -> None:
        scan = scan_project(fake_multi_project)
        wl = suggest_command_whitelist(scan)
        assert len(wl) == len(set(wl))


# ---------------------------------------------------------------------------
# Generator tests
# ---------------------------------------------------------------------------

class TestGenerateIterateMd:
    def test_contains_partition_markers(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        md = generate_iterate_md(data)
        assert AI_START_MARKER in md
        assert AI_END_MARKER in md
        assert USER_START_MARKER in md
        assert USER_END_MARKER in md

    def test_contains_meta_info(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        md = generate_iterate_md(data)
        assert "{{COMPLETED_AT}}" not in md
        assert "cli" in md
        assert FINGERPRINT_VERSION in md

    def test_contains_tech_stack(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        md = generate_iterate_md(data)
        assert "Python" in md

    def test_contains_dimensions(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        md = generate_iterate_md(data)
        assert "correctness" in md

    def test_no_unreplaced_placeholders(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        md = generate_iterate_md(data)
        assert "{{" not in md
        assert "}}" not in md


class TestGenerateConfigYaml:
    def test_valid_yaml(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        yaml_text = generate_config_yaml(data)
        config = yaml.safe_load(yaml_text)
        assert isinstance(config, dict)
        assert config["dimensions"] == data.dimensions

    def test_contains_onboarding_section(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        yaml_text = generate_config_yaml(data)
        config = yaml.safe_load(yaml_text)
        assert "onboarding" in config
        assert config["onboarding"]["channel"] == "cli"
        assert config["onboarding"]["version"] == FINGERPRINT_VERSION
        assert isinstance(config["onboarding"]["fingerprints"], list)
        assert len(config["onboarding"]["fingerprints"]) == 1

    def test_config_passes_schema(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        yaml_text = generate_config_yaml(data)
        config_path = fake_project / "iterate.config.yaml"
        config_path.write_text(yaml_text, encoding="utf-8")

        schema_path = REPO_ROOT / "config" / "config.schema.json"
        import validate
        errors = validate.validate_config(config_path, schema_path)
        assert errors == [], f"Schema validation errors: {errors}"


class TestWriteOutputs:
    def test_writes_both_files(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        md_path, config_path = write_onboarding_outputs(data, fake_project)
        assert md_path.is_file()
        assert config_path.is_file()
        assert md_path.name == "ITERATE.md"
        assert config_path.name == "iterate.config.yaml"


class TestExtractUserOwnedSection:
    def test_extracts_content(self) -> None:
        md = f"""
# ITERATE.md
{AI_START_MARKER}
AI content
{AI_END_MARKER}
---
{USER_START_MARKER}
## My Conventions
- Use 4 spaces
{USER_END_MARKER}
"""
        result = extract_user_owned_section(md)
        assert "My Conventions" in result
        assert "Use 4 spaces" in result

    def test_returns_default_when_markers_missing(self) -> None:
        result = extract_user_owned_section("no markers here")
        assert "Custom Code Conventions" in result

    def test_returns_default_when_markers_inverted(self) -> None:
        md = f"{USER_END_MARKER}\n{USER_START_MARKER}"
        result = extract_user_owned_section(md)
        assert "Custom Code Conventions" in result


class TestGenerateRefreshedMd:
    def test_preserves_user_content(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        original_md = generate_iterate_md(data)

        # Modify user section in the generated file.
        user_marker_pos = original_md.find(USER_START_MARKER)
        user_end_pos = original_md.find(USER_END_MARKER)
        modified_md = (
            original_md[:user_marker_pos + len(USER_START_MARKER)]
            + "\n## My Custom Rules\n- Never use var\n"
            + original_md[user_end_pos:]
        )

        # Generate refreshed version.
        refreshed = generate_refreshed_md(data, modified_md)

        # User content should be preserved.
        assert "My Custom Rules" in refreshed
        assert "Never use var" in refreshed

    def test_replaces_ai_content(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        original_md = generate_iterate_md(data)

        # Change project description for refresh.
        data.project_description = "Updated description"
        refreshed = generate_refreshed_md(data, original_md)
        assert "Updated description" in refreshed


# ---------------------------------------------------------------------------
# Wizard tests
# ---------------------------------------------------------------------------

class TestParseDimensionSelection:
    def test_valid_selection(self) -> None:
        result = _parse_dimension_selection("1,2,6")
        assert result == ["correctness", "security", "tech-debt"]

    def test_single_number(self) -> None:
        result = _parse_dimension_selection("3")
        assert result == ["performance"]

    def test_empty_string(self) -> None:
        assert _parse_dimension_selection("") == []

    def test_out_of_range(self) -> None:
        assert _parse_dimension_selection("0") == []
        assert _parse_dimension_selection("99") == []

    def test_non_numeric(self) -> None:
        assert _parse_dimension_selection("abc") == []


class TestAskYesNo:
    def test_yes(self) -> None:
        assert _ask_yes_no("test?", lambda _: "y") is True
        assert _ask_yes_no("test?", lambda _: "yes") is True

    def test_no(self) -> None:
        assert _ask_yes_no("test?", lambda _: "n") is False
        assert _ask_yes_no("test?", lambda _: "no") is False

    def test_default_on_empty(self) -> None:
        assert _ask_yes_no("test?", lambda _: "", default=True) is True
        assert _ask_yes_no("test?", lambda _: "", default=False) is False

    def test_retries_on_invalid(self) -> None:
        responses = iter(["maybe", "y"])
        assert _ask_yes_no("test?", lambda _: next(responses)) is True


class TestRunWizard:
    def test_full_flow_python_project(self, fake_project: Path) -> None:
        """Simulate a user going through the full wizard."""
        responses = iter([
            "y",          # gate question: continue
            "y",          # tech stack correct
            "y",          # use suggested validation commands
            "",           # use suggested dimensions (press Enter)
            "",           # target branch: default main
            "",           # review scope: default full
            "y",          # push per round: yes
            "Test project",  # project description
            "",           # code conventions: empty line to finish
            "y",          # confirm and generate
        ])
        data = run_wizard(fake_project, input_func=lambda _: next(responses))
        assert data is not None
        assert data.channel == "cli"
        assert "Python" in data.scan.detected_languages
        assert "correctness" in data.dimensions
        assert data.target_branch == "main"
        assert len(data.fingerprints) == 1

    def test_gate_question_abort(self, fake_project: Path) -> None:
        responses = iter(["n"])  # gate: no
        data = run_wizard(fake_project, input_func=lambda _: next(responses))
        assert data is None

    def test_cancel_at_confirmation(self, fake_project: Path) -> None:
        responses = iter([
            "y",          # gate: continue
            "y",          # tech stack correct
            "y",          # use suggested commands
            "",           # default dimensions
            "",           # default branch
            "",           # default scope
            "y",          # push: yes
            "Desc",       # description
            "",           # conventions: empty
            "n",          # confirm: no
        ])
        data = run_wizard(fake_project, input_func=lambda _: next(responses))
        assert data is None

    def test_manual_command_entry(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # gate: continue
            "y",              # tech stack correct
            "n",              # don't use suggested commands
            "python",         # module name
            "ruff check .",   # command
            "",               # end python commands
            "",               # end modules
            "",               # default dimensions
            "",               # default branch
            "",               # default scope
            "y",              # push: yes
            "Desc",           # description
            "",               # conventions: empty
            "y",              # confirm: yes
        ])
        data = run_wizard(fake_project, input_func=lambda _: next(responses))
        assert data is not None
        assert "python" in data.validation_commands
        assert "ruff check ." in data.validation_commands["python"]

    def test_custom_dimension_selection(self, fake_project: Path) -> None:
        responses = iter([
            "y",          # gate: continue
            "y",          # tech stack correct
            "y",          # use suggested commands
            "1,2,3",      # select dimensions 1,2,3
            "",           # default branch
            "",           # default scope
            "y",          # push: yes
            "Desc",       # description
            "",           # conventions: empty
            "y",          # confirm: yes
        ])
        data = run_wizard(fake_project, input_func=lambda _: next(responses))
        assert data is not None
        assert data.dimensions == ["correctness", "security", "performance"]


# ---------------------------------------------------------------------------
# Refresh tests
# ---------------------------------------------------------------------------

class TestIsOnboardingComplete:
    def test_not_complete(self, empty_project: Path) -> None:
        assert is_onboarding_complete(empty_project) is False

    def test_complete(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        assert is_onboarding_complete(fake_project) is True


class TestCheckOnboardingDrift:
    def test_no_drift(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        drift = check_onboarding_drift(fake_project)
        assert drift is not None
        assert not drift.has_drift

    def test_drift_detected(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        (fake_project / "pyproject.toml").write_text("changed", encoding="utf-8")
        drift = check_onboarding_drift(fake_project)
        assert drift is not None
        assert drift.has_drift
        assert "pyproject.toml" in drift.changed

    def test_no_config_returns_none(self, empty_project: Path) -> None:
        assert check_onboarding_drift(empty_project) is None

    def test_drift_check_disabled(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        # Disable drift check in config.
        config_path = fake_project / "iterate.config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config["onboarding"]["drift_check"] = False
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        assert check_onboarding_drift(fake_project) is None


class TestIncrementalRefresh:
    def test_refresh_preserves_user_sections(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Add user content to ITERATE.md.
        iterate_md = fake_project / "ITERATE.md"
        content = iterate_md.read_text(encoding="utf-8")
        user_start = content.find(USER_START_MARKER)
        user_end = content.find(USER_END_MARKER)
        modified = (
            content[:user_start + len(USER_START_MARKER)]
            + "\n## My Custom Rules\n- Never use var\n"
            + content[user_end:]
        )
        iterate_md.write_text(modified, encoding="utf-8")

        # Perform refresh.
        assert incremental_refresh(fake_project) is True

        # User content preserved.
        refreshed = iterate_md.read_text(encoding="utf-8")
        assert "My Custom Rules" in refreshed
        assert "Never use var" in refreshed

    def test_refresh_updates_fingerprints(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Change manifest and refresh.
        (fake_project / "pyproject.toml").write_text("new content", encoding="utf-8")
        incremental_refresh(fake_project)

        config = load_onboarding_config(fake_project)
        assert config is not None
        new_fp = config["onboarding"]["fingerprints"]
        assert len(new_fp) == 1
        expected_hash = hashlib.sha256(b"new content").hexdigest()
        assert new_fp[0]["sha256"] == expected_hash

    def test_refresh_fails_without_iterate_md(self, empty_project: Path) -> None:
        assert incremental_refresh(empty_project) is False


class TestFullReonboard:
    def test_creates_backup(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Add user content to verify backup.
        iterate_md = fake_project / "ITERATE.md"
        iterate_md.write_text("original content", encoding="utf-8")

        responses = iter([
            "y",          # gate: continue
            "y",          # tech stack correct
            "y",          # use suggested commands
            "",           # default dimensions
            "",           # default branch
            "",           # default scope
            "y",          # push: yes
            "Redone",     # description
            "",           # conventions: empty
            "y",          # confirm: yes
        ])
        result = full_reonboard(fake_project, input_func=lambda _: next(responses))
        assert result is True

        # Backup file exists.
        backups = list(fake_project.glob("ITERATE.md.bak-*"))
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "original content"

    def test_cancelled_returns_false(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        responses = iter(["n"])  # gate: no
        result = full_reonboard(fake_project, input_func=lambda _: next(responses))
        assert result is False

    def test_fails_without_existing(self, empty_project: Path) -> None:
        assert full_reonboard(empty_project) is False


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCLIStatus:
    def test_status_not_onboarded(self, empty_project: Path, capsys) -> None:
        ret = cli_main(["status", "-p", str(empty_project)])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Not onboarded" in captured.out

    def test_status_onboarded_no_drift(self, fake_project: Path, capsys) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        ret = cli_main(["status", "-p", str(fake_project)])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Onboarded" in captured.out
        assert "No drift" in captured.out

    def test_status_with_drift(self, fake_project: Path, capsys) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        (fake_project / "pyproject.toml").write_text("changed", encoding="utf-8")
        ret = cli_main(["status", "-p", str(fake_project)])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Drift" in captured.out

    def test_invalid_project_dir(self, capsys) -> None:
        ret = cli_main(["status", "-p", "/nonexistent/path/xyz"])
        assert ret == 1


class TestCLIOnboard:
    def test_onboard_already_done(self, fake_project: Path, capsys) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        ret = cli_main(["onboard", "-p", str(fake_project)])
        assert ret == 1
        captured = capsys.readouterr()
        assert "already completed" in captured.out


class TestCLIRefresh:
    def test_refresh_not_onboarded(self, empty_project: Path, capsys) -> None:
        ret = cli_main(["refresh", "-p", str(empty_project)])
        assert ret == 1
        captured = capsys.readouterr()
        assert "not yet completed" in captured.out

    def test_refresh_success(self, fake_project: Path, capsys) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        ret = cli_main(["refresh", "-p", str(fake_project)])
        assert ret == 0
        captured = capsys.readouterr()
        assert "complete" in captured.out.lower()


class TestCLIReonboard:
    def test_reonboard_not_onboarded(self, empty_project: Path, capsys) -> None:
        ret = cli_main(["reonboard", "-p", str(empty_project)])
        assert ret == 1


class TestCLIVersion:
    def test_version_flag(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["--version"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "iterate" in captured.out


class TestCLINoCommand:
    def test_no_command_prints_help(self, capsys) -> None:
        ret = cli_main(["-p", "."])
        assert ret == 0
