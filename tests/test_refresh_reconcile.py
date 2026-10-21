"""Unit tests for validation-tooling reconciliation during incremental refresh.

Covers ``iterate_cli.refresh._reconcile_validation_suggestions``: the function
additively augments validation commands and command-whitelist prefixes for
languages newly detected since the last onboarding, while preserving (and never
removing) existing operator configuration.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from iterate_cli.generator import DEFAULT_LANGUAGE
from iterate_cli.refresh import (
    _build_refresh_data,
    _build_refreshed_config,
    _diff_stats,
    _reconcile_validation_suggestions,
    incremental_refresh,
    load_onboarding_config,
    preview_refresh,
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

    def test_empty_whitelist_resolved_immediately(self) -> None:
        """An empty/invalid whitelist resolves to suggestions in ONE pass.

        (Replaces the old `reconcile_whitelist=False` "intent" behaviour:
        `_resolve_validation_config` now flags `[]` and uses suggestions
        right away, so consecutive refreshes never flip.)"""
        scan = _python_scan()
        commands, whitelist = _reconcile_validation_suggestions({}, [], scan)
        assert "python" in commands
        assert "ruff" in whitelist

    def test_commands_still_reconciled_with_empty_seed(self) -> None:
        """Command reconcile works even when the seed whitelist is empty."""
        scan = _python_scan()
        commands, whitelist = _reconcile_validation_suggestions({}, [], scan)
        assert "python" in commands
        assert whitelist  # suggestions appended


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
    """An empty command_whitelist (schema-invalid, minItems 1) is resolved to
    scan suggestions immediately and a warning is shown — never persisted as
    ``[]``, and never silently deferred to the next refresh (the old
    one-round-then-refill flip)."""

    def test_empty_whitelist_refilled_with_warning(
        self, tmp_path: Path, capsys
    ) -> None:
        config = {
            "dimensions": ["correctness"],
            "onboarding": {"channel": "cli"},
            "validation": {"commands": {}, "command_whitelist": []},
        }
        data = _build_refresh_data(
            tmp_path, ScanResult(detected_languages=[], manifests=[]), config
        )
        # Resolved to the base suggestions right away (no "preserve until
        # next refresh" deferral).
        assert data.command_whitelist == ["python", "python3"]
        new_config = _build_refreshed_config(config, data)
        assert new_config["validation"]["command_whitelist"] == ["python", "python3"]
        captured = capsys.readouterr()
        assert "command_whitelist is empty or not a list" in captured.out + captured.err

    def test_second_refresh_is_stable(self, tmp_path: Path) -> None:
        """Two consecutive refreshes converge (no whitelist flip-flop)."""
        config = {
            "dimensions": ["correctness"],
            "onboarding": {"channel": "cli"},
            "validation": {"commands": {}, "command_whitelist": []},
        }
        scan = ScanResult(detected_languages=[], manifests=[])
        first = _build_refresh_data(tmp_path, scan, config)
        config2 = _build_refreshed_config(config, first)
        second = _build_refresh_data(tmp_path, scan, config2)
        assert first.command_whitelist == second.command_whitelist

    def test_non_string_whitelist_entries_are_filtered_not_fatal(
        self, tmp_path: Path, capsys
    ) -> None:
        """`[["pytest"]]` used to crash refresh with TypeError."""
        config = {
            "dimensions": ["correctness"],
            "onboarding": {"channel": "cli"},
            "validation": {
                "commands": {"python": ["pytest -q"]},
                "command_whitelist": [["pytest"], 123, "ruff", "  "],
            },
        }
        data = _build_refresh_data(tmp_path, _python_scan(), config)

        # The surviving string entry is kept (and the freshly-suggested
        # prefixes for the detected stack are appended); nothing non-string
        # reaches the schema or crashes `set(...)`.
        assert "ruff" in data.command_whitelist
        assert all(isinstance(entry, str) and entry for entry in data.command_whitelist)
        assert "non-string or empty entries" in capsys.readouterr().err

    def test_on_is_coerced_to_true(self, tmp_path: Path) -> None:
        """Wizard accepts `on`; refresh must not rewrite it to False."""
        config = {
            "dimensions": ["correctness"],
            "onboarding": {"channel": "cli"},
            "validation": {"commands": {}, "command_whitelist": ["python"]},
            "git": {"push_per_round": "on"},
        }
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.push_per_round is True

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

class TestBuildRefreshDataNormalizesHandEditedScalars:
    """A hand-edited config holding schema-invalid scalars must round-trip.

    refresh rebuilds and REWRITES iterate.config.yaml, so an invalid value
    that survives a refresh keeps failing `iterate doctor` forever. Each case
    below used to be written back verbatim.
    """

    def _config(self, **overrides) -> dict:
        config = {
            "dimensions": ["correctness"],
            "onboarding": {"channel": "cli"},
            "validation": {"commands": {}, "command_whitelist": []},
        }
        config.update(overrides)
        return config

    def test_null_target_branch_falls_back_to_default(self, tmp_path) -> None:
        config = self._config(git={"target_branch": None})
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.target_branch == "main"
        assert isinstance(data.target_branch, str) and data.target_branch.strip()

    def test_blank_target_branch_falls_back(self, tmp_path) -> None:
        config = self._config(git={"target_branch": "   "})
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.target_branch == "main"

    def test_non_string_target_branch_falls_back(self, tmp_path) -> None:
        config = self._config(git={"target_branch": 42})
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.target_branch == "main"

    def test_non_enum_review_scope_falls_back(self, tmp_path) -> None:
        config = self._config(review={"scope": "everything"})
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.review_scope in ("changed-only", "full")

    def test_null_review_scope_falls_back(self, tmp_path) -> None:
        config = self._config(review={"scope": None})
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.review_scope in ("changed-only", "full")

    def test_valid_review_scope_preserved(self, tmp_path) -> None:
        config = self._config(review={"scope": "full"})
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.review_scope == "full"

    def test_string_push_per_round_is_coerced_not_truthy(self, tmp_path) -> None:
        """`push_per_round: "no"` must not round-trip as a truthy string.

        Secure-by-default: a non-bool is coerced, and only canonical false
        forms stay false.
        """
        config = self._config(git={"push_per_round": "no"})
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.push_per_round is False

    def test_int_one_push_per_round_is_true(self, tmp_path) -> None:
        config = self._config(git={"push_per_round": 1})
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.push_per_round is True

    def test_bool_false_is_authoritative(self, tmp_path) -> None:
        config = self._config(git={"push_per_round": False})
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.push_per_round is False

    def test_non_zh_en_language_falls_back(self, tmp_path) -> None:
        config = self._config(language="fr")
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.language == DEFAULT_LANGUAGE

    def test_non_string_language_falls_back(self, tmp_path) -> None:
        config = self._config(language=42)
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.language == DEFAULT_LANGUAGE

    def test_valid_language_preserved(self, tmp_path) -> None:
        config = self._config(language="en")
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.language == "en"

    def test_string_dimensions_not_iterated_char_by_char(self, tmp_path) -> None:
        """`dimensions: "correctness"` must not become ['c','o','r',...]."""
        config = self._config(dimensions="correctness")
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.dimensions
        assert all(len(d) > 1 for d in data.dimensions)

    def test_non_string_dimension_elements_dropped(self, tmp_path) -> None:
        config = self._config(dimensions=["correctness", 123, "  ", None])
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.dimensions == ["correctness", "123"]

    def test_all_invalid_dimension_elements_fall_back_to_scan(
        self, tmp_path
    ) -> None:
        config = self._config(dimensions=[None, "", "  "])
        data = _build_refresh_data(tmp_path, _python_scan(), config)
        assert data.dimensions  # suggestions, not an empty/invalid list


class TestRefreshPreservesHandWrittenConfig:
    """A no-op refresh must not rewrite (and thereby de-comment) the config.

    ``yaml.safe_dump`` cannot round-trip comments, so the old byte comparison
    always saw a difference and rewrote the file on every refresh — silently
    deleting every guidance comment the operator had added.
    """

    def _onboarded_config(self) -> dict:
        return {
            "dimensions": ["correctness"],
            "onboarding": {
                "channel": "cli",
                "drift_check": False,
                "completed_at": "2026-08-01T00:00:00Z",
            },
        }

    def _normalized_project(self, tmp_path: Path) -> Path:
        project = _write_project(tmp_path, self._onboarded_config())
        # First refresh normalizes the config (adds validation, fingerprints…).
        assert incremental_refresh(project) is True
        # That normalization legitimately rewrote the file; drop its backup so
        # the tests below observe only what the second refresh does.
        for stale in project.glob(f"{CONFIG_YAML}.refresh-*"):
            stale.unlink()
        return project

    def test_noop_refresh_keeps_comments(self, tmp_path: Path) -> None:
        project = self._normalized_project(tmp_path)
        config_path = project / CONFIG_YAML
        annotated = (
            "# Operator note: keep this line for the on-call runbook.\n"
            + config_path.read_text(encoding="utf-8")
        )
        config_path.write_text(annotated, encoding="utf-8")

        assert incremental_refresh(project) is True

        after = config_path.read_text(encoding="utf-8")
        assert "# Operator note: keep this line for the on-call runbook." in after

    def test_noop_refresh_does_not_create_backup(self, tmp_path: Path) -> None:
        project = self._normalized_project(tmp_path)
        config_path = project / CONFIG_YAML
        config_path.write_text(
            "# note\n" + config_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

        assert incremental_refresh(project) is True

        backups = list(project.glob(f"{CONFIG_YAML}.refresh-*"))
        assert backups == []

    def test_preview_reports_no_config_change_for_comment_only_diff(
        self, tmp_path: Path
    ) -> None:
        project = self._normalized_project(tmp_path)
        config_path = project / CONFIG_YAML
        config_path.write_text(
            "# note\n" + config_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

        preview = preview_refresh(project)
        assert preview["ok"] is True
        assert preview["config_changed"] is False

    def test_real_value_change_still_creates_backup(self, tmp_path: Path) -> None:
        project = self._normalized_project(tmp_path)
        config_path = project / CONFIG_YAML
        config = load_onboarding_config(project)
        assert config is not None
        # An invalid language is corrected to the default by refresh, which is
        # a real value change (and therefore a rewrite).
        config["language"] = "fr"
        config_path.write_text(
            "# note\n" + yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        assert incremental_refresh(project) is True

        assert load_onboarding_config(project)["language"] == "en"
        backups = list(project.glob(f"{CONFIG_YAML}.refresh-*"))
        assert len(backups) == 1
        # The backup preserves the pre-refresh document, comments included.
        assert "# note" in backups[0].read_text(encoding="utf-8")


class TestDimensionSetsOnDropIsVisible:
    """A hand-written dimension_set that normalize drops must be announced.

    refresh REWRITES the config, so a silent drop deleted the operator's
    entry on the next `iterate refresh` with exit 0 and no output.
    """

    def test_refresh_warns_about_dropped_set(self, tmp_path, capsys) -> None:
        from iterate_cli.scan import ScanResult

        config = {
            "dimensions": ["correctness"],
            "onboarding": {"channel": "cli"},
            "validation": {"commands": {}, "command_whitelist": []},
            "dimension_sets": {
                "frontend": {"dimensions": ["ui-ux"]},
                "broken": "not-a-mapping",
            },
        }
        data = _build_refresh_data(
            tmp_path, ScanResult(detected_languages=[], manifests=[]), config
        )
        captured = capsys.readouterr()
        assert "broken" in captured.out + captured.err
        assert "dimension_sets" in captured.out + captured.err
        # The valid entry survives.
        assert "frontend" in data.dimension_sets
        assert "broken" not in data.dimension_sets

    def test_no_warning_when_all_sets_valid(self, tmp_path, capsys) -> None:
        from iterate_cli.scan import ScanResult

        config = {
            "dimensions": ["correctness"],
            "onboarding": {"channel": "cli"},
            "validation": {"commands": {}, "command_whitelist": []},
            "dimension_sets": {"frontend": {"dimensions": ["ui-ux"]}},
        }
        _build_refresh_data(
            tmp_path, ScanResult(detected_languages=[], manifests=[]), config
        )
        captured = capsys.readouterr()
        assert "dimension_sets" not in captured.out + captured.err
