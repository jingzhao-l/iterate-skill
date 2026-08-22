"""Unit tests for validation-tooling reconciliation during incremental refresh.

Covers ``iterate_cli.refresh._reconcile_validation_suggestions``: the function
additively augments validation commands and command-whitelist prefixes for
languages newly detected since the last onboarding, while preserving (and never
removing) existing operator configuration.
"""

from __future__ import annotations

from iterate_cli.refresh import _reconcile_validation_suggestions
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