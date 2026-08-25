"""Unit tests for validation-tooling reconciliation during incremental refresh.

Covers ``iterate_cli.refresh._reconcile_validation_suggestions``: the function
additively augments validation commands and command-whitelist prefixes for
languages newly detected since the last onboarding, while preserving (and never
removing) existing operator configuration.
"""

from __future__ import annotations

from pathlib import Path

from iterate_cli.refresh import (
    _build_refresh_data,
    _reconcile_validation_suggestions,
)
from iterate_cli.scan import ScanResult


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