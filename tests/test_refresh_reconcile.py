"""Unit tests for validation-tooling reconciliation during incremental refresh.

Covers ``iterate_cli.refresh._reconcile_validation_suggestions``: the function
additively augments validation commands and command-whitelist prefixes for
languages newly detected since the last onboarding, while preserving (and never
removing) existing operator configuration.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from iterate_cli.refresh import (
    _build_refresh_data,
    _build_refreshed_config,
    _diff_stats,
    _reconcile_validation_suggestions,
    incremental_refresh,
    load_onboarding_config,
)
from iterate_cli.scan import ScanResult

CONFIG_YAML = "iterate.config.yaml"
ITERATE_MD = "ITERATE.md"


def _python_scan() -> ScanResult:
    return ScanResult(detected_languages=["Python"], manifests=["pyproject.toml"])


class TestReconcileValidationSuggestions:
    def test_adds_commands_and_whitelist_for_new_stack(self) -> None:
        """A fresh stack with no existing config gets suggested tooling."""
        scan = _python_scan()
        commands, whitelist = _reconcile_validation_suggestions({}, [], scan)
        assert "python" in commands
        assert commands["python"]  # non-empty suggested command list
        assert "ruff" in whitelist
        assert "mypy" in whitelist

    def test_preserves_existing_customised_commands(self) -> None:
        """Existing commands are kept verbatim; only missing modules added."""
        scan = ScanResult(
            detected_languages=["Python", "JavaScript/TypeScript"],
            manifests=["pyproject.toml", "package.json"],
        )
        commands, _ = _reconcile_validation_suggestions(
            {"python": ["pytest --custom-py"]}, [], scan
        )
        # Existing (possibly customised) module is untouched.
        assert commands["python"] == ["pytest --custom-py"]
        # Newly-detected language is added.
        assert "typescript" in commands

    def test_does_not_duplicate_whitelist_prefixes(self) -> None:
        """Already-present prefixes are not re-added on refresh."""
        scan = _python_scan()
        _, whitelist = _reconcile_validation_suggestions(
            {}, ["python", "pytest"], scan
        )
        assert whitelist.count("python") == 1
        assert whitelist.count("pytest") == 1
        # Missing prefixes are appended.
        assert "ruff" in whitelist

    def test_reconcile_whitelist_false_preserves_empty_intent(self) -> None:
        """Operator's deliberate empty whitelist is respected."""
        scan = _python_scan()
        _, whitelist = _reconcile_validation_suggestions(
            {}, [], scan, reconcile_whitelist=False
        )
        assert whitelist == []

    def test_commands_still_reconciled_when_whitelist_preserved(self) -> None:
        """Disabling whitelist reconciliation does not disable command reconcile."""
        scan = _python_scan()
        commands, whitelist = _reconcile_validation_suggestions(
            {}, [], scan, reconcile_whitelist=False
        )
        assert "python" in commands
        assert whitelist == []


class TestBuildRefreshDataPreservesReviewer:
    """_build_refresh_data must carry reviewer tuning through a refresh so a
    customised evidence gate / coverage check / chunk size is never reset."""

    def test_preserves_customised_reviewer_fields(self, tmp_path: Path) -> None:
        config = {
            "goal": "g",
            "dimensions": ["correctness"],
            "reviewer": {
                "output_schema_validation": False,
                "evidence_validation": False,
                "coverage_validation": False,
                "scope_chunk_size": 10,
            },
            "onboarding": {"channel": "cli", "drift_ignore": []},
            "validation": {"commands": {}, "command_whitelist": []},
        }
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.output_schema_validation is False
        assert data.evidence_validation is False
        assert data.coverage_validation is False
        assert data.scope_chunk_size == 10

    def test_defaults_when_reviewer_absent(self, tmp_path: Path) -> None:
        config = {
            "dimensions": ["correctness"],
            "onboarding": {"channel": "cli"},
            "validation": {"commands": {}, "command_whitelist": []},
        }
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.output_schema_validation is True
        assert data.evidence_validation is True
        assert data.coverage_validation is True
        assert data.scope_chunk_size == 25

    def test_survives_non_dict_reviewer(self, tmp_path: Path) -> None:
        config = {
            "dimensions": ["correctness"],
            "reviewer": "oops",
            "onboarding": {"channel": "cli"},
            "validation": {"commands": {}, "command_whitelist": []},
        }
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.evidence_validation is True
        assert data.scope_chunk_size == 25


def _write_project(tmp_path: Path, config: dict) -> Path:
    """Create an onboarded project under tmp_path with ITERATE.md + config."""
    project = tmp_path / "proj"
    project.mkdir(parents=True)
    (project / ITERATE_MD).write_text(
        "# Project\n\n<!-- ITERATE:USER-OWNED:START -->\nmanual\n<!-- ITERATE:USER-OWNED:END -->\n",
        encoding="utf-8",
    )
    (project / CONFIG_YAML).write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    # A real manifest so the scan detects the stack.
    (project / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    return project


class TestIncrementalRefreshPersistsReconciledData:
    """Regression: reconciled validation/dimension-set data must be persisted.

    ``_build_refresh_data`` additively reconciles validation commands,
    command-whitelist and dimension-sets with a freshly-detected stack, but
    ``_build_refreshed_config`` previously only wrote back fingerprints — so
    ``incremental_refresh`` regenerated ITERATE.md advertising the reconciled
    tooling while leaving the config stale, driving config and docs apart.
    """

    def _base_config(self) -> dict:
        return {
            "dimensions": ["correctness"],
            "onboarding": {
                "channel": "cli",
                "drift_check": False,
                "completed_at": "2026-08-01T00:00:00Z",
            },
        }

    def test_persists_reconciled_whitelist_and_commands(self, tmp_path: Path) -> None:
        project = _write_project(tmp_path, self._base_config())
        assert incremental_refresh(project) is True

        config = load_onboarding_config(project)
        assert config is not None
        validation = config.get("validation")
        assert isinstance(validation, dict)
        # Newly-detected Python stack's suggested commands + prefixes are now
        # actually written into the config (previously dropped).
        assert "python" in validation["commands"]
        assert isinstance(validation["command_whitelist"], list)
        assert "ruff" in validation["command_whitelist"]

    def test_persists_reconciled_dimension_sets(self, tmp_path: Path) -> None:
        project = _write_project(tmp_path, self._base_config())
        assert incremental_refresh(project) is True

        config = load_onboarding_config(project)
        assert config is not None
        # dimension_sets reflect the merged suggestion, not an empty drop.
        assert isinstance(config.get("dimension_sets"), dict)
        assert config["dimension_sets"]  # non-empty merged presets

    def test_refreshed_config_syncs_reconciled_fields(self, tmp_path: Path) -> None:
        """Directly verify _build_refreshed_config carries the reconciled data."""
        config = self._base_config()
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        new_config = _build_refreshed_config(config, data)
        assert new_config["validation"]["commands"].get("python")
        assert "ruff" in new_config["validation"]["command_whitelist"]
        assert new_config["dimension_sets"]
        assert new_config["reasoning_effort"] == data.reasoning_effort
        # Preserved user fields are untouched.
        assert new_config["dimensions"] == ["correctness"]

    def test_preserves_existing_customised_commands_on_refresh(
        self, tmp_path: Path
    ) -> None:
        config = self._base_config()
        config["validation"] = {
            "commands": {"python": ["pytest --custom"]},
            "command_whitelist": ["python"],
        }
        project = _write_project(tmp_path, config)
        assert incremental_refresh(project) is True

        new_config = load_onboarding_config(project)
        assert new_config is not None
        # Customised command is preserved verbatim, not overwritten.
        assert new_config["validation"]["commands"]["python"] == ["pytest --custom"]


class TestDiffStats:
    """_diff_stats must count changed lines without diff-header false positives."""

    def test_no_change_returns_zeroes(self) -> None:
        assert _diff_stats("same\nbody\n", "same\nbody\n") == {
            "added": 0,
            "removed": 0,
            "changed": 0,
        }

    def test_counts_content_lines_mistaken_for_headers(self) -> None:
        """Content lines that start with '--'/'++' collided with the '--- ' /
        '+++ ' file-header skip in the old unified-diff parser and were dropped
        from the counts. SequenceMatcher length arithmetic has no such
        ambiguity."""
        before = "start\n-- book keeping\nend\n"
        after = "start\nend\n++ added note\n"
        stats = _diff_stats(before, after)
        assert stats["removed"] == 1  # the '-- book keeping' line
        assert stats["added"] == 1  # the '++ added note' line
        assert stats["changed"] == 2

    def test_totals_match_actual_delta(self) -> None:
        before = "\n".join(f"line{n}" for n in range(10))
        after = "\n".join(f"line{n}" for n in range(7)) + "\nbrand new"
        stats = _diff_stats(before, after)
        assert stats["added"] == 1
        assert stats["removed"] == 3
        assert stats["changed"] == 4


class TestBuildRefreshedConfigEmptyWhitelist:
    """A cleared command_whitelist is dropped, not persisted as [].

    The schema requires command_whitelist to be non-empty when present
    (minItems 1), so writing ``command_whitelist: []`` would keep the refreshed
    config schema-invalid. An operator-cleared whitelist is expressed by
    omitting the key (mirroring personalize's merge)."""

    def test_empty_whitelist_drops_key(self, tmp_path: Path) -> None:
        config = {
            "dimensions": ["correctness"],
            "onboarding": {"channel": "cli"},
            "validation": {"commands": {}, "command_whitelist": []},
        }
        data = _build_refresh_data(
            tmp_path, ScanResult(detected_languages=[], manifests=[]), config
        )
        assert data.command_whitelist == []
        new_config = _build_refreshed_config(config, data)
        assert "command_whitelist" not in new_config["validation"]

    def test_non_empty_whitelist_kept(self, tmp_path: Path) -> None:
        config = {
            "dimensions": ["correctness"],
            "onboarding": {"channel": "cli"},
            "validation": {
                "commands": {"python": ["pytest -q"]},
                "command_whitelist": ["pytest", "ruff"],
            },
        }
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        new_config = _build_refreshed_config(config, data)
        assert "ruff" in new_config["validation"]["command_whitelist"]