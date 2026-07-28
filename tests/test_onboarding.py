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
from iterate_cli.personalize import (
    DimensionFocusOverride,
    KnownIntentional,
    PersonalizationData,
    RiskArea,
    load_personalization_from_config,
    merge_personalization_into_config,
    run_personalize_wizard,
    save_personalization_to_config,
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
            "n",          # personalization offer: no
        ])
        data = run_wizard(fake_project, input_func=lambda _: next(responses))
        assert data is not None
        assert data.channel == "cli"
        assert "Python" in data.scan.detected_languages
        assert "correctness" in data.dimensions
        assert data.target_branch == "main"
        assert len(data.fingerprints) == 1
        assert data.personalization is None

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
            "n",              # personalization offer: no
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
            "n",          # personalization offer: no
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

        # Returning user flow: update basic config, then decline personalization.
        responses = iter([
            "y",          # update basic config: yes
            "y",          # tech stack correct
            "y",          # use suggested commands
            "",           # default dimensions
            "",           # default branch
            "",           # default scope
            "y",          # push: yes
            "Redone",     # description
            "",           # conventions: empty
            "y",          # confirm: yes
            "n",          # personalization offer: no
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

        # Returning user flow: say yes to update basic config, cancel at confirmation.
        responses = iter([
            "y",          # update basic config: yes
            "y",          # tech stack correct
            "y",          # use suggested commands
            "",           # default dimensions
            "",           # default branch
            "",           # default scope
            "y",          # push: yes
            "Desc",       # description
            "",           # conventions: empty
            "n",          # confirm: no (cancel)
        ])
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


class TestReturningUserFlow:
    """Tests for the multi-path wizard when ITERATE.md already exists."""

    def test_skip_basic_keep_existing_config(self, fake_project: Path) -> None:
        """Returning user declines basic update and personalization."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        responses = iter([
            "n",          # update basic config: no (use existing)
            "n",          # personalization: no
        ])
        result = run_wizard(fake_project, input_func=lambda _: next(responses))
        assert result is not None
        assert result.channel == "cli"
        assert "correctness" in result.dimensions

    def test_update_basic_config(self, fake_project: Path) -> None:
        """Returning user updates basic config."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        responses = iter([
            "y",          # update basic config: yes
            "y",          # tech stack correct
            "y",          # use suggested commands
            "",           # default dimensions
            "develop",    # target branch: develop
            "",           # default scope
            "n",          # push: no
            "Updated",    # description
            "",           # conventions: empty
            "y",          # confirm: yes
            "n",          # personalization: no
        ])
        result = run_wizard(fake_project, input_func=lambda _: next(responses))
        assert result is not None
        assert result.target_branch == "develop"
        assert result.push_per_round is False

    def test_returning_user_with_personalization(self, fake_project: Path) -> None:
        """Returning user declines basic update but accepts personalization."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        responses = iter([
            "n",          # update basic config: no
            "y",          # personalization: yes
            "y",          # start personalization
            # Step 1: protected paths
            "a",          # add
            "legacy/**",  # path
            "s",          # skip
            # Step 2: risk areas
            "s",          # skip
            # Step 3: known intentional
            "s",          # skip
            # Step 4: dimension focus
            "s",          # skip
            # Step 5: fix priority order
            "",           # skip (empty)
            # Step 6: forbidden fixes
            "s",          # skip
            # Step 7: iterate notes
            "s",          # skip
            # Step 8: code conventions
            "s",          # skip
            # Step 9: extra validation commands
            "s",          # skip
            "y",          # confirm save
        ])
        result = run_wizard(fake_project, input_func=lambda _: next(responses))
        assert result is not None
        assert result.personalization is not None
        assert "legacy/**" in result.personalization.protected_paths


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


# ---------------------------------------------------------------------------
# PersonalizationData model tests
# ---------------------------------------------------------------------------


def _build_personalization_data() -> PersonalizationData:
    """Build a PersonalizationData with all fields populated."""
    return PersonalizationData(
        protected_paths=["legacy/**", "vendor/**"],
        risk_areas=[
            RiskArea(path="src/auth/", reason="认证模块需审批"),
            RiskArea(path="src/crypto/", reason="加密模块敏感"),
        ],
        known_intentional=[
            KnownIntentional(
                file="db/queries.py", line=42, dimension="tech-debt",
                reason="使用 any 是性能优化",
            ),
            KnownIntentional(
                file="legacy/handlers.py", line=0, dimension="style-tests",
                reason="遗留代码不强制风格",
            ),
        ],
        dimension_focus=[
            DimensionFocusOverride(dimension="security", focus="SQL 注入历史事故"),
        ],
        fix_priority_order=["security", "correctness", "performance"],
        forbidden_fixes=["try-catch 吞错", "# noqa"],
        iterate_notes=["不要修改迁移文件", "测试数据库在 CI 中自动创建"],
        code_conventions=["使用 4 空格缩进", "函数名用 snake_case"],
        extra_validation_commands={"python": ["bandit -r src/"]},
    )


class TestPersonalizationDataModel:
    def test_is_empty_true(self) -> None:
        data = PersonalizationData()
        assert data.is_empty() is True

    def test_is_empty_false_with_protected_paths(self) -> None:
        data = PersonalizationData(protected_paths=["src/"])
        assert data.is_empty() is False

    def test_is_empty_false_with_extra_commands(self) -> None:
        data = PersonalizationData(extra_validation_commands={"python": ["test"]})
        assert data.is_empty() is False

    def test_to_config_dict_has_structured_fields(self) -> None:
        data = _build_personalization_data()
        d = data.to_config_dict()
        assert d["protected_paths"] == ["legacy/**", "vendor/**"]
        assert len(d["risk_areas"]) == 2
        assert d["risk_areas"][0] == {"path": "src/auth/", "reason": "认证模块需审批"}
        assert len(d["known_intentional"]) == 2
        assert d["known_intentional"][0]["file"] == "db/queries.py"
        assert d["known_intentional"][0]["line"] == 42
        assert d["dimension_focus"][0] == {
            "dimension": "security", "focus": "SQL 注入历史事故",
        }
        assert d["fix_priority_order"] == ["security", "correctness", "performance"]
        assert d["forbidden_fixes"] == ["try-catch 吞错", "# noqa"]

    def test_to_config_dict_excludes_free_form_fields(self) -> None:
        data = _build_personalization_data()
        d = data.to_config_dict()
        # iterate_notes and code_conventions are free-form, not in config dict
        assert "iterate_notes" not in d
        assert "code_conventions" not in d
        assert "extra_validation_commands" not in d

    def test_to_user_md_sections_empty(self) -> None:
        data = PersonalizationData()
        assert data.to_user_md_sections().strip() == ""

    def test_to_user_md_sections_with_conventions(self) -> None:
        data = PersonalizationData(code_conventions=["Use 4 spaces", "snake_case"])
        md = data.to_user_md_sections()
        assert "Custom Code Conventions" in md
        assert "Use 4 spaces" in md
        assert "snake_case" in md

    def test_to_user_md_sections_with_protected_paths(self) -> None:
        data = PersonalizationData(protected_paths=["legacy/**"])
        md = data.to_user_md_sections()
        assert "Restricted" in md
        assert "Protected" in md
        assert "legacy/**" in md

    def test_to_user_md_sections_with_risk_areas(self) -> None:
        data = PersonalizationData(
            risk_areas=[RiskArea(path="src/auth/", reason="sensitive")],
        )
        md = data.to_user_md_sections()
        assert "Risk Areas" in md
        assert "src/auth/" in md
        assert "sensitive" in md

    def test_to_user_md_sections_with_iterate_notes(self) -> None:
        data = PersonalizationData(iterate_notes=["Don't touch migrations"])
        md = data.to_user_md_sections()
        assert "Iterate Notes" in md
        assert "Don't touch migrations" in md

    def test_to_user_md_sections_with_known_intentional(self) -> None:
        data = PersonalizationData(
            known_intentional=[
                KnownIntentional(
                    file="db/queries.py", line=42, dimension="tech-debt",
                    reason="intentional any",
                ),
            ],
        )
        md = data.to_user_md_sections()
        assert "Known Intentional" in md
        assert "db/queries.py:42" in md
        assert "tech-debt" in md

    def test_to_user_md_sections_known_intentional_whole_file(self) -> None:
        """Line 0 should show just the file path, not file:0."""
        data = PersonalizationData(
            known_intentional=[
                KnownIntentional(
                    file="legacy/handlers.py", line=0, dimension="style-tests",
                    reason="legacy code",
                ),
            ],
        )
        md = data.to_user_md_sections()
        assert "legacy/handlers.py" in md
        assert "legacy/handlers.py:0" not in md

    def test_to_user_md_sections_with_forbidden_fixes(self) -> None:
        data = PersonalizationData(forbidden_fixes=["# noqa", "try-catch 吞错"])
        md = data.to_user_md_sections()
        assert "Forbidden Fixes" in md
        assert "# noqa" in md


# ---------------------------------------------------------------------------
# Load / save / merge tests
# ---------------------------------------------------------------------------


class TestLoadPersonalizationFromConfig:
    def test_load_empty_config(self) -> None:
        data = load_personalization_from_config({})
        assert data.is_empty() is True

    def test_load_config_without_personalization(self) -> None:
        config = {"dimensions": ["correctness"], "goal": "test"}
        data = load_personalization_from_config(config)
        assert data.is_empty() is True

    def test_load_full_config(self) -> None:
        config = {
            "personalization": {
                "protected_paths": ["legacy/**"],
                "risk_areas": [{"path": "src/auth/", "reason": "sensitive"}],
                "known_intentional": [
                    {"file": "db.py", "line": 10, "dimension": "security", "reason": "ok"},
                ],
                "dimension_focus": [
                    {"dimension": "security", "focus": "SQL injection"},
                ],
                "fix_priority_order": ["security", "correctness"],
                "forbidden_fixes": ["# noqa"],
                "extra_validation_commands": {"python": ["bandit -r src/"]},
            },
        }
        data = load_personalization_from_config(config)
        assert data.protected_paths == ["legacy/**"]
        assert len(data.risk_areas) == 1
        assert data.risk_areas[0].path == "src/auth/"
        assert data.risk_areas[0].reason == "sensitive"
        assert len(data.known_intentional) == 1
        assert data.known_intentional[0].file == "db.py"
        assert data.known_intentional[0].line == 10
        assert data.known_intentional[0].dimension == "security"
        assert len(data.dimension_focus) == 1
        assert data.dimension_focus[0].dimension == "security"
        assert data.fix_priority_order == ["security", "correctness"]
        assert data.forbidden_fixes == ["# noqa"]
        assert data.extra_validation_commands == {"python": ["bandit -r src/"]}

    def test_load_partial_config(self) -> None:
        config = {
            "personalization": {
                "protected_paths": ["vendor/**"],
            },
        }
        data = load_personalization_from_config(config)
        assert data.protected_paths == ["vendor/**"]
        assert data.risk_areas == []
        assert data.forbidden_fixes == []

    def test_load_skips_malformed_entries(self) -> None:
        config = {
            "personalization": {
                "risk_areas": [
                    {"path": "ok/", "reason": "fine"},
                    "not a dict",
                    {"reason": "missing path"},
                ],
                "known_intentional": [
                    {"file": "ok.py", "line": 1, "dimension": "security", "reason": "ok"},
                    "not a dict",
                    {"line": 5},
                ],
                "dimension_focus": [
                    {"dimension": "security", "focus": "ok"},
                    "not a dict",
                    {"focus": "missing dim"},
                ],
            },
        }
        data = load_personalization_from_config(config)
        assert len(data.risk_areas) == 1
        assert len(data.known_intentional) == 1
        assert len(data.dimension_focus) == 1

    def test_load_extra_validation_commands_non_list_skipped(self) -> None:
        config = {
            "personalization": {
                "extra_validation_commands": {
                    "python": "not a list",
                    "swift": ["swift build"],
                },
            },
        }
        data = load_personalization_from_config(config)
        assert "python" not in data.extra_validation_commands
        assert data.extra_validation_commands["swift"] == ["swift build"]


class TestMergePersonalizationIntoConfig:
    def test_merge_creates_personalization_section(self) -> None:
        config = {"goal": "test", "dimensions": ["correctness"]}
        data = PersonalizationData(protected_paths=["legacy/**"])
        result = merge_personalization_into_config(config, data)
        assert "personalization" in result
        assert result["personalization"]["protected_paths"] == ["legacy/**"]

    def test_merge_preserves_other_fields(self) -> None:
        config = {"goal": "test", "dimensions": ["correctness"]}
        data = _build_personalization_data()
        result = merge_personalization_into_config(config, data)
        assert result["goal"] == "test"
        assert result["dimensions"] == ["correctness"]

    def test_merge_extra_commands_into_validation(self) -> None:
        config = {
            "validation": {
                "commands": {"python": ["pytest"]},
                "command_whitelist": ["pytest"],
            },
        }
        data = PersonalizationData(
            extra_validation_commands={"python": ["bandit -r src/"], "swift": ["swift build"]},
        )
        result = merge_personalization_into_config(config, data)
        assert "bandit -r src/" in result["validation"]["commands"]["python"]
        assert "pytest" in result["validation"]["commands"]["python"]
        assert result["validation"]["commands"]["swift"] == ["swift build"]

    def test_merge_extra_commands_no_duplicates(self) -> None:
        config = {
            "validation": {
                "commands": {"python": ["pytest", "ruff check src/"]},
            },
        }
        data = PersonalizationData(
            extra_validation_commands={"python": ["ruff check src/", "mypy src/"]},
        )
        result = merge_personalization_into_config(config, data)
        cmds = result["validation"]["commands"]["python"]
        assert cmds.count("ruff check src/") == 1
        assert "mypy src/" in cmds
        assert "pytest" in cmds

    def test_merge_does_not_mutate_original(self) -> None:
        config = {"goal": "test"}
        data = PersonalizationData(protected_paths=["legacy/**"])
        result = merge_personalization_into_config(config, data)
        assert "personalization" not in config
        assert "personalization" in result

    def test_merge_creates_validation_section_if_missing(self) -> None:
        config = {"goal": "test"}
        data = PersonalizationData(
            extra_validation_commands={"python": ["bandit -r src/"]},
        )
        result = merge_personalization_into_config(config, data)
        assert "validation" in result
        assert result["validation"]["commands"]["python"] == ["bandit -r src/"]


class TestSavePersonalizationToConfig:
    def test_save_writes_personalization_section(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        personalization = PersonalizationData(protected_paths=["legacy/**"])
        save_personalization_to_config(fake_project, personalization)

        config = yaml.safe_load(
            (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        )
        assert config["personalization"]["protected_paths"] == ["legacy/**"]

    def test_save_preserves_other_config_fields(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        personalization = PersonalizationData(forbidden_fixes=["# noqa"])
        save_personalization_to_config(fake_project, personalization)

        config = yaml.safe_load(
            (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        )
        assert config["goal"] == "Improve code quality and maintainability"
        assert "correctness" in config["dimensions"]
        assert config["onboarding"]["channel"] == "cli"

    def test_save_raises_on_missing_config(self, empty_project: Path) -> None:
        with pytest.raises(FileNotFoundError):
            save_personalization_to_config(
                empty_project, PersonalizationData(protected_paths=["x"]),
            )

    def test_save_roundtrip(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        original = _build_personalization_data()
        save_personalization_to_config(fake_project, original)

        config = yaml.safe_load(
            (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        )
        loaded = load_personalization_from_config(config)

        assert loaded.protected_paths == original.protected_paths
        assert len(loaded.risk_areas) == len(original.risk_areas)
        assert loaded.risk_areas[0].path == original.risk_areas[0].path
        assert loaded.forbidden_fixes == original.forbidden_fixes
        assert loaded.fix_priority_order == original.fix_priority_order

    def test_save_merges_extra_commands(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Original config has python commands from scan.
        personalization = PersonalizationData(
            extra_validation_commands={"python": ["bandit -r src/"]},
        )
        save_personalization_to_config(fake_project, personalization)

        config = yaml.safe_load(
            (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        )
        python_cmds = config["validation"]["commands"]["python"]
        assert "bandit -r src/" in python_cmds
        # Original commands from scan should still be there.
        assert any("pytest" in c for c in python_cmds)


# ---------------------------------------------------------------------------
# Personalize wizard tests
# ---------------------------------------------------------------------------


class TestRunPersonalizeWizard:
    def test_cancel_at_start(self, fake_project: Path) -> None:
        responses = iter(["n"])  # start personalization? no
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is None

    def test_full_flow_all_skip(self, fake_project: Path) -> None:
        """User starts but skips every step, then confirms empty data."""
        responses = iter([
            "y",    # start personalization
            "s",    # step 1: skip protected paths
            "s",    # step 2: skip risk areas
            "s",    # step 3: skip known intentional
            "s",    # step 4: skip dimension focus
            "",     # step 5: skip fix priority (empty)
            "s",    # step 6: skip forbidden fixes
            "s",    # step 7: skip iterate notes
            "s",    # step 8: skip code conventions
            "s",    # step 9: skip extra validation commands
            "y",    # confirm save (even though empty)
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert result.is_empty() is True

    def test_cancel_at_confirmation(self, fake_project: Path) -> None:
        """User fills some data but cancels at final confirmation."""
        responses = iter([
            "y",          # start personalization
            # Step 1: protected paths
            "a",          # add
            "legacy/**",  # path
            "s",          # skip
            # Step 2-9: skip all
            "s", "s", "s", "", "s", "s", "s", "s", "s",
            "n",          # confirm save: no
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is None

    def test_add_protected_paths(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            # Step 1: protected paths
            "a",              # add
            "legacy/**",      # path
            "a",              # add another
            "vendor/**",      # path
            "s",              # skip
            # Step 2-9: skip all
            "s", "s", "s", "", "s", "s", "s", "s", "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert result.protected_paths == ["legacy/**", "vendor/**"]

    def test_add_and_remove_protected_path(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            # Step 1: protected paths
            "a",              # add
            "legacy/**",      # path
            "a",              # add
            "vendor/**",      # path
            "r",              # remove
            "1",              # remove first (legacy/**)
            "s",              # skip
            # Step 2-9: skip all
            "s", "s", "s", "", "s", "s", "s", "s", "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert result.protected_paths == ["vendor/**"]

    def test_add_risk_areas(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            # Step 1: skip
            "s",
            # Step 2: risk areas
            "a",              # add
            "src/auth/",      # path
            "认证模块需审批",  # reason
            "s",              # skip
            # Step 3-9: skip all
            "s", "s", "", "s", "s", "s", "s", "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert len(result.risk_areas) == 1
        assert result.risk_areas[0].path == "src/auth/"
        assert result.risk_areas[0].reason == "认证模块需审批"

    def test_add_risk_area_empty_path_cancels(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            "s",              # step 1: skip
            # Step 2: risk areas
            "a",              # add
            "",               # empty path → cancels add
            "s",              # skip
            # Step 3-9: skip all
            "s", "s", "", "s", "s", "s", "s", "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert result.risk_areas == []

    def test_add_risk_area_default_reason(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            "s",              # step 1: skip
            # Step 2: risk areas
            "a",              # add
            "src/auth/",      # path
            "",               # empty reason → uses default
            "s",              # skip
            # Step 3-9: skip all
            "s", "s", "", "s", "s", "s", "s", "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert len(result.risk_areas) == 1
        assert "未说明" in result.risk_areas[0].reason or "unspecified" in result.risk_areas[0].reason

    def test_add_known_intentional(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            "s", "s",         # skip steps 1-2
            # Step 3: known intentional
            "a",              # add
            "db/queries.py",  # file
            "42",             # line
            "6",              # dimension number (tech-debt)
            "使用 any 是性能优化",  # reason
            "s",              # skip
            # Step 4-9: skip all
            "s", "", "s", "s", "s", "s", "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert len(result.known_intentional) == 1
        assert result.known_intentional[0].file == "db/queries.py"
        assert result.known_intentional[0].line == 42
        assert result.known_intentional[0].dimension == "tech-debt"

    def test_add_known_intentional_whole_file(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            "s", "s",         # skip steps 1-2
            # Step 3: known intentional
            "a",              # add
            "legacy/handlers.py",  # file
            "",               # empty line → 0 (whole file)
            "5",              # dimension number (style-tests)
            "遗留代码不强制风格",  # reason
            "s",              # skip
            # Step 4-9: skip all
            "s", "", "s", "s", "s", "s", "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert result.known_intentional[0].line == 0
        assert result.known_intentional[0].dimension == "style-tests"

    def test_add_known_intentional_invalid_line_defaults_zero(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            "s", "s",         # skip steps 1-2
            # Step 3: known intentional
            "a",              # add
            "db.py",          # file
            "abc",            # invalid line → defaults to 0
            "1",              # dimension number (correctness)
            "ok",             # reason
            "s",              # skip
            # Step 4-9: skip all
            "s", "", "s", "s", "s", "s", "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert result.known_intentional[0].line == 0

    def test_add_dimension_focus(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            "s", "s", "s",    # skip steps 1-3
            # Step 4: dimension focus
            "a",              # add
            "2",              # dimension number (security)
            "SQL 注入历史事故",  # focus
            "s",              # skip
            # Step 5-9: skip all
            "", "s", "s", "s", "s", "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert len(result.dimension_focus) == 1
        assert result.dimension_focus[0].dimension == "security"
        assert result.dimension_focus[0].focus == "SQL 注入历史事故"

    def test_add_dimension_focus_empty_focus_cancels(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            "s", "s", "s",    # skip steps 1-3
            # Step 4: dimension focus
            "a",              # add
            "2",              # dimension number (security)
            "",               # empty focus → cancels
            "s",              # skip
            # Step 5-9: skip all
            "", "s", "s", "s", "s", "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert result.dimension_focus == []

    def test_fix_priority_order(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            "s", "s", "s", "s",  # skip steps 1-4
            # Step 5: fix priority order
            "2,1,3",          # security, correctness, performance
            "y",              # confirm new order
            # Step 6-9: skip all
            "s", "s", "s", "s", "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert result.fix_priority_order == ["security", "correctness", "performance"]

    def test_fix_priority_order_invalid_keeps_empty(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            "s", "s", "s", "s",  # skip steps 1-4
            # Step 5: fix priority order
            "abc",            # invalid input
            # Step 6-9: skip all
            "s", "s", "s", "s", "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert result.fix_priority_order == []

    def test_add_forbidden_fixes(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            "s", "s", "s", "s", "",  # skip steps 1-5
            # Step 6: forbidden fixes
            "a",              # add
            "# noqa",         # value
            "a",              # add
            "try-catch 吞错",  # value
            "s",              # skip
            # Step 7-9: skip all
            "s", "s", "s", "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert result.forbidden_fixes == ["# noqa", "try-catch 吞错"]

    def test_add_iterate_notes(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            "s", "s", "s", "s", "", "s",  # skip steps 1-6
            # Step 7: iterate notes
            "a",              # add
            "不要修改迁移文件",  # value
            "s",              # skip
            # Step 8-9: skip all
            "s", "s", "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert "不要修改迁移文件" in result.iterate_notes

    def test_add_code_conventions(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            "s", "s", "s", "s", "", "s", "s",  # skip steps 1-7
            # Step 8: code conventions
            "a",              # add
            "使用 4 空格缩进",  # value
            "s",              # skip
            # Step 9: skip
            "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert "使用 4 空格缩进" in result.code_conventions

    def test_add_extra_validation_commands(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            "s", "s", "s", "s", "", "s", "s", "s",  # skip steps 1-8
            # Step 9: extra validation commands
            "a",              # add
            "python",         # module
            "bandit -r src/", # command
            "a",              # add another
            "python",         # module
            "safety check",   # command
            "s",              # skip
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert "python" in result.extra_validation_commands
        assert "bandit -r src/" in result.extra_validation_commands["python"]
        assert "safety check" in result.extra_validation_commands["python"]

    def test_add_validation_command_duplicate_skipped(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            "s", "s", "s", "s", "", "s", "s", "s",  # skip steps 1-8
            # Step 9: extra validation commands
            "a",              # add
            "python",         # module
            "bandit -r src/", # command
            "a",              # add same
            "python",         # module
            "bandit -r src/", # same command
            "s",              # skip
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert result.extra_validation_commands["python"].count("bandit -r src/") == 1

    def test_add_validation_command_empty_module_skipped(self, fake_project: Path) -> None:
        responses = iter([
            "y",              # start personalization
            "s", "s", "s", "s", "", "s", "s", "s",  # skip steps 1-8
            # Step 9: extra validation commands
            "a",              # add
            "",               # empty module → skipped
            "s",              # skip
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert result.extra_validation_commands == {}

    def test_edit_existing_data(self, fake_project: Path) -> None:
        """Load existing personalization and add to it."""
        existing = PersonalizationData(
            protected_paths=["legacy/**"],
            forbidden_fixes=["# noqa"],
        )
        responses = iter([
            "y",              # start personalization
            # Step 1: protected paths (has 1 existing)
            "a",              # add
            "vendor/**",      # path
            "s",              # skip
            # Step 2-5: skip
            "s", "s", "s", "",
            # Step 6: forbidden fixes (has 1 existing)
            "a",              # add
            "try-catch 吞错",  # value
            "s",              # skip
            # Step 7-9: skip
            "s", "s", "s",
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project,
            input_func=lambda _: next(responses),
            existing=existing,
        )
        assert result is not None
        assert result.protected_paths == ["legacy/**", "vendor/**"]
        assert result.forbidden_fixes == ["# noqa", "try-catch 吞错"]

    def test_full_flow_all_categories(self, fake_project: Path) -> None:
        """Fill all 9 categories in one wizard run."""
        responses = iter([
            "y",                          # start personalization
            # Step 1: protected paths
            "a", "legacy/**", "s",
            # Step 2: risk areas
            "a", "src/auth/", "sensitive", "s",
            # Step 3: known intentional
            "a", "db.py", "10", "2", "intentional", "s",
            # Step 4: dimension focus
            "a", "2", "SQL injection focus", "s",
            # Step 5: fix priority order
            "2,1", "y",
            # Step 6: forbidden fixes
            "a", "# noqa", "s",
            # Step 7: iterate notes
            "a", "Don't touch migrations", "s",
            # Step 8: code conventions
            "a", "Use 4 spaces", "s",
            # Step 9: extra validation commands
            "a", "python", "bandit -r src/", "s",
            "y",  # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert result.protected_paths == ["legacy/**"]
        assert len(result.risk_areas) == 1
        assert len(result.known_intentional) == 1
        assert len(result.dimension_focus) == 1
        assert result.fix_priority_order == ["security", "correctness"]
        assert result.forbidden_fixes == ["# noqa"]
        assert len(result.iterate_notes) == 1
        assert len(result.code_conventions) == 1
        assert "python" in result.extra_validation_commands


# ---------------------------------------------------------------------------
# CLI personalize subcommand tests
# ---------------------------------------------------------------------------


class TestCLIPersonalize:
    def test_personalize_not_onboarded(self, empty_project: Path, capsys) -> None:
        ret = cli_main(["personalize", "-p", str(empty_project)])
        assert ret == 1
        captured = capsys.readouterr()
        assert "not yet completed" in captured.out.lower() or "onboard" in captured.out.lower()

    def test_personalize_no_config(self, fake_project: Path, capsys) -> None:
        """ITERATE.md exists but config.yaml missing."""
        (fake_project / "ITERATE.md").write_text("content", encoding="utf-8")
        ret = cli_main(["personalize", "-p", str(fake_project)])
        assert ret == 1

    def test_personalize_success(self, fake_project: Path) -> None:
        """Personalize via CLI with mock input (call _cmd_personalize directly)."""
        from iterate_cli.cli import _cmd_personalize

        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Mock run_personalize_wizard to return pre-built data
        # instead of trying to inject input through the CLI.
        mock_personalization = PersonalizationData(
            protected_paths=["legacy/**"],
            code_conventions=["Use snake_case"],
        )

        import iterate_cli.personalize as personalize_module
        original_func = personalize_module.run_personalize_wizard
        personalize_module.run_personalize_wizard = lambda *args, **kwargs: mock_personalization

        try:
            ret = _cmd_personalize(fake_project)
        finally:
            personalize_module.run_personalize_wizard = original_func

        assert ret == 0

        # Verify config has personalization section.
        config = yaml.safe_load(
            (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        )
        assert "personalization" in config
        assert "legacy/**" in config["personalization"]["protected_paths"]

        # Verify ITERATE.md has user-owned content.
        iterate_md = (fake_project / "ITERATE.md").read_text(encoding="utf-8")
        assert "legacy/**" in iterate_md
        assert "Protected" in iterate_md or "Restricted" in iterate_md


# ---------------------------------------------------------------------------
# Generator with personalization tests
# ---------------------------------------------------------------------------


class TestGeneratorWithPersonalization:
    def test_generate_config_with_personalization(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        data.personalization = PersonalizationData(
            protected_paths=["legacy/**"],
            forbidden_fixes=["# noqa"],
            fix_priority_order=["security", "correctness"],
        )
        yaml_text = generate_config_yaml(data)
        config = yaml.safe_load(yaml_text)
        assert "personalization" in config
        assert config["personalization"]["protected_paths"] == ["legacy/**"]
        assert config["personalization"]["forbidden_fixes"] == ["# noqa"]
        assert config["personalization"]["fix_priority_order"] == ["security", "correctness"]

    def test_generate_config_without_personalization(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        yaml_text = generate_config_yaml(data)
        config = yaml.safe_load(yaml_text)
        # personalization section should not be present if no data
        assert "personalization" not in config or config["personalization"] == {
            "protected_paths": [],
            "risk_areas": [],
            "known_intentional": [],
            "dimension_focus": [],
            "fix_priority_order": [],
            "forbidden_fixes": [],
        }

    def test_generate_iterate_md_with_personalization(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        data.personalization = PersonalizationData(
            protected_paths=["legacy/**"],
            code_conventions=["Use 4 spaces"],
            iterate_notes=["Don't touch migrations"],
        )
        md = generate_iterate_md(data)
        assert "legacy/**" in md
        assert "Use 4 spaces" in md
        assert "Don't touch migrations" in md

    def test_generate_iterate_md_without_personalization(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        md = generate_iterate_md(data)
        # Default user-owned section should be present
        assert USER_START_MARKER in md
        assert USER_END_MARKER in md

    def test_config_with_personalization_passes_schema(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        data.personalization = _build_personalization_data()
        # Add 'bandit' to whitelist since extra_validation_commands adds it.
        data.command_whitelist = list(data.command_whitelist) + ["bandit"]
        yaml_text = generate_config_yaml(data)
        config_path = fake_project / "iterate.config.yaml"
        config_path.write_text(yaml_text, encoding="utf-8")

        schema_path = REPO_ROOT / "config" / "config.schema.json"
        import validate
        errors = validate.validate_config(config_path, schema_path)
        assert errors == [], f"Schema validation errors: {errors}"

    def test_write_outputs_with_personalization(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        data.personalization = PersonalizationData(
            protected_paths=["legacy/**"],
            code_conventions=["Use snake_case"],
        )
        md_path, config_path = write_onboarding_outputs(data, fake_project)
        assert md_path.is_file()
        assert config_path.is_file()

        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert config["personalization"]["protected_paths"] == ["legacy/**"]

        md = md_path.read_text(encoding="utf-8")
        assert "legacy/**" in md
        assert "snake_case" in md
