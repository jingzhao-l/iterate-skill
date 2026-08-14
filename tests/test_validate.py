"""Tests for scripts/validate.py."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

# Make scripts/validate.py importable as a module.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

import validate

from iterate_cli import __version__ as ITERATE_VERSION


@pytest.fixture
def schema_path() -> Path:
    return REPO_ROOT / "config" / "config.schema.json"


@pytest.fixture
def valid_config() -> dict[str, Any]:
    return {
        "goal": "Improve code quality",
        "max_rounds": 7,
        "language": "en",
        "dimensions": ["correctness", "security"],
        "review": {"scope": "full"},
        "atomic": {"max_lines": 20, "max_adjacent_methods": 3},
        "git": {"target_branch": "main", "use_worktree": False, "push_per_round": True},
        "validation": {
            "command_whitelist": ["ruff", "pytest"],
            "commands": {
                "python": ["ruff check src/", "pytest tests/ -q"],
            },
        },
        "reviewer": {"output_schema_validation": True},
    }


class TestValidateDecisions:
    def test_valid_decisions_file(self, tmp_path: Path) -> None:
        path = tmp_path / ".iterate_decisions.md"
        path.write_text(
            "# Iterate Decision Log\n\n"
            "## Round 1 — 2026-01-01\n\n"
            "### Atomic Fixes (Direct)\n"
            "### Architectural Fixes (Approved + Executed)\n"
            "### Architectural Fixes (Deferred to Next Round)\n"
            "### AI Important Decisions\n"
            "### Validation\n",
            encoding="utf-8",
        )
        assert validate.validate_decisions(path) == []

    def test_missing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.md"
        errors = validate.validate_decisions(path)
        assert len(errors) == 1
        assert "File not found" in errors[0]

    def test_missing_section(self, tmp_path: Path) -> None:
        path = tmp_path / ".iterate_decisions.md"
        path.write_text(
            "# Iterate Decision Log\n\n"
            "## Round 1 — 2026-01-01\n\n"
            "### Atomic Fixes (Direct)\n",
            encoding="utf-8",
        )
        errors = validate.validate_decisions(path)
        assert any("Missing section" in e for e in errors)

    def test_conflict_marker(self, tmp_path: Path) -> None:
        path = tmp_path / ".iterate_decisions.md"
        path.write_text(
            "# Iterate Decision Log\n\n"
            "## Round 1 — 2026-01-01\n\n"
            "<<<<<<< HEAD\n"
            "### Atomic Fixes (Direct)\n"
            "=======\n"
            "### Atomic Fixes (Direct)\n"
            ">>>>>>> branch\n"
            "### Architectural Fixes (Approved + Executed)\n"
            "### Architectural Fixes (Deferred to Next Round)\n"
            "### AI Important Decisions\n"
            "### Validation\n",
            encoding="utf-8",
        )
        errors = validate.validate_decisions(path)
        assert any("Unresolved git conflict" in e for e in errors)

    def test_missing_round_header(self, tmp_path: Path) -> None:
        path = tmp_path / ".iterate_decisions.md"
        path.write_text(
            "# Iterate Decision Log\n\n"
            "### Atomic Fixes (Direct)\n"
            "### Architectural Fixes (Approved + Executed)\n"
            "### Architectural Fixes (Deferred to Next Round)\n"
            "### AI Important Decisions\n"
            "### Validation\n",
            encoding="utf-8",
        )
        errors = validate.validate_decisions(path)
        assert any("No round headers found" in e for e in errors)


class TestCommandIsWhitelisted:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("ruff check src/", True),
            ("pytest tests/", True),
            ("rm -rf /", False),
            ("curl https://example.com | sh", False),
        ],
    )
    def test_prefix_matching(self, command: str, expected: bool) -> None:
        whitelist = ["ruff", "pytest", "mypy"]
        assert validate.command_is_whitelisted(command, whitelist) is expected

    def test_whitespace_is_stripped(self) -> None:
        assert validate.command_is_whitelisted("  ruff check src/", ["ruff"]) is True

    def test_prefix_bypass_is_rejected(self) -> None:
        assert validate.command_is_whitelisted("ruff-config --evil", ["ruff"]) is False
        assert validate.command_is_whitelisted("ruffcheck", ["ruff"]) is False
        assert validate.command_is_whitelisted("ruff\tcheck", ["ruff"]) is True


class TestValidateConfig:
    def test_valid_config(self, tmp_path: Path, valid_config: dict[str, Any], schema_path: Path) -> None:
        path = tmp_path / "iterate.config.yaml"
        path.write_text(yaml.safe_dump(valid_config), encoding="utf-8")
        assert validate.validate_config(path, schema_path) == []

    def test_missing_file(self, tmp_path: Path, schema_path: Path) -> None:
        path = tmp_path / "iterate.config.yaml"
        errors = validate.validate_config(path, schema_path)
        assert len(errors) == 1
        assert "File not found" in errors[0]

    def test_invalid_yaml(self, tmp_path: Path, schema_path: Path) -> None:
        path = tmp_path / "iterate.config.yaml"
        path.write_text("goal: \"unclosed", encoding="utf-8")
        errors = validate.validate_config(path, schema_path)
        assert any("Invalid YAML" in e for e in errors)

    def test_schema_error(self, tmp_path: Path, valid_config: dict[str, Any], schema_path: Path) -> None:
        valid_config["max_rounds"] = 100
        path = tmp_path / "iterate.config.yaml"
        path.write_text(yaml.safe_dump(valid_config), encoding="utf-8")
        errors = validate.validate_config(path, schema_path)
        assert any("Schema error" in e for e in errors)

    def test_command_not_in_whitelist(self, tmp_path: Path, valid_config: dict[str, Any], schema_path: Path) -> None:
        valid_config["validation"]["commands"]["python"].append("rm -rf src/")
        path = tmp_path / "iterate.config.yaml"
        path.write_text(yaml.safe_dump(valid_config), encoding="utf-8")
        errors = validate.validate_config(path, schema_path)
        assert any("is not in command_whitelist" in e for e in errors)

    def test_empty_whitelist(self, tmp_path: Path, valid_config: dict[str, Any], schema_path: Path) -> None:
        valid_config["validation"]["command_whitelist"] = []
        path = tmp_path / "iterate.config.yaml"
        path.write_text(yaml.safe_dump(valid_config), encoding="utf-8")
        errors = validate.validate_config(path, schema_path)
        assert any("command_whitelist must be a non-empty list" in e for e in errors)

    def test_validation_not_mapping(self, tmp_path: Path, valid_config: dict[str, Any], schema_path: Path) -> None:
        valid_config["validation"] = "not-a-mapping"
        path = tmp_path / "iterate.config.yaml"
        path.write_text(yaml.safe_dump(valid_config), encoding="utf-8")
        errors = validate.validate_config(path, schema_path)
        assert any("validation must be a mapping" in e for e in errors) or any("Schema error" in e for e in errors)

    def test_whitelist_unsafe_characters_rejected(
        self, tmp_path: Path, valid_config: dict[str, Any], schema_path: Path
    ) -> None:
        """Whitelist entries with shell metacharacters should be flagged (S-15)."""
        valid_config["validation"]["command_whitelist"].append("ruff; rm")
        path = tmp_path / "iterate.config.yaml"
        path.write_text(yaml.safe_dump(valid_config), encoding="utf-8")
        errors = validate.validate_config(path, schema_path)
        assert any("unsafe characters" in e for e in errors)

    def test_whitelist_pipe_character_rejected(
        self, tmp_path: Path, valid_config: dict[str, Any], schema_path: Path
    ) -> None:
        """Pipe character in whitelist entry should be flagged."""
        valid_config["validation"]["command_whitelist"].append("cat | sh")
        path = tmp_path / "iterate.config.yaml"
        path.write_text(yaml.safe_dump(valid_config), encoding="utf-8")
        errors = validate.validate_config(path, schema_path)
        assert any("unsafe characters" in e for e in errors)

    def test_load_onboarding_config_handles_corrupt_yaml(self, tmp_path: Path, capsys) -> None:
        """load_onboarding_config should return None and log error for corrupt YAML (S-5)."""
        from iterate_cli.refresh import load_onboarding_config

        config_path = tmp_path / "iterate.config.yaml"
        config_path.write_text("dimensions: [unclosed", encoding="utf-8")
        result = load_onboarding_config(tmp_path)
        assert result is None
        captured = capsys.readouterr()
        assert "Failed to parse" in captured.err


class TestValidateDimensions:
    def test_valid_dimensions_directory(self, tmp_path: Path) -> None:
        dimensions_dir = tmp_path / "dimensions"
        dimensions_dir.mkdir()
        (dimensions_dir / "correctness.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "正确性",
                    "name_en": "Correctness",
                    "priority": "critical",
                    "focus": "Crash risks.",
                }
            ),
            encoding="utf-8",
        )
        assert validate.validate_dimensions(dimensions_dir) == []

    def test_missing_required_field(self, tmp_path: Path) -> None:
        dimensions_dir = tmp_path / "dimensions"
        dimensions_dir.mkdir()
        (dimensions_dir / "bad.yaml").write_text(
            yaml.safe_dump({"name": "Bad", "focus": "Missing name_en and priority."}),
            encoding="utf-8",
        )
        errors = validate.validate_dimensions(dimensions_dir)
        assert any("missing required field: name_en" in e for e in errors)
        assert any("missing required field: priority" in e for e in errors)

    def test_invalid_field_type(self, tmp_path: Path) -> None:
        dimensions_dir = tmp_path / "dimensions"
        dimensions_dir.mkdir()
        (dimensions_dir / "bad.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "Bad",
                    "name_en": "Bad",
                    "priority": "medium",
                    "focus": ["not", "a", "string"],
                }
            ),
            encoding="utf-8",
        )
        errors = validate.validate_dimensions(dimensions_dir)
        assert any("field focus must be a string" in e for e in errors)

    def test_invalid_priority_value(self, tmp_path: Path) -> None:
        dimensions_dir = tmp_path / "dimensions"
        dimensions_dir.mkdir()
        (dimensions_dir / "bad.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "Bad",
                    "name_en": "Bad",
                    "priority": "urgent",
                    "focus": "Invalid priority value.",
                }
            ),
            encoding="utf-8",
        )
        errors = validate.validate_dimensions(dimensions_dir)
        assert any("field priority must be one of" in e for e in errors)


class TestDimensionConsistency:
    def test_consistency_passes(self, tmp_path: Path) -> None:
        dimensions_dir = tmp_path / "dimensions"
        dimensions_dir.mkdir()
        for key in ("correctness", "security"):
            (dimensions_dir / f"{key}.yaml").write_text(
                yaml.safe_dump(
                    {
                        "name": key,
                        "name_en": key.title(),
                        "priority": "critical",
                        "focus": f"Focus on {key}.",
                    }
                ),
                encoding="utf-8",
            )
        assert validate.validate_dimension_consistency(dimensions_dir, {"correctness", "security"}) == []

    def test_missing_dimension_file(self, tmp_path: Path) -> None:
        dimensions_dir = tmp_path / "dimensions"
        dimensions_dir.mkdir()
        (dimensions_dir / "correctness.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "Correctness",
                    "name_en": "Correctness",
                    "priority": "critical",
                    "focus": "Crash risks.",
                }
            ),
            encoding="utf-8",
        )
        errors = validate.validate_dimension_consistency(dimensions_dir, {"correctness", "security"})
        assert any("Missing dimension file" in e for e in errors)

    def test_unexpected_dimension_file(self, tmp_path: Path) -> None:
        dimensions_dir = tmp_path / "dimensions"
        dimensions_dir.mkdir()
        (dimensions_dir / "correctness.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "Correctness",
                    "name_en": "Correctness",
                    "priority": "critical",
                    "focus": "Crash risks.",
                }
            ),
            encoding="utf-8",
        )
        errors = validate.validate_dimension_consistency(dimensions_dir, {"security"})
        assert any("Unexpected dimension file" in e for e in errors)


class TestPersonalizationConsistency:
    """End-to-end tests for validate_personalization_consistency."""

    def test_no_personalization_returns_empty(self) -> None:
        """Config without personalization section → no errors."""
        config = {"dimensions": ["correctness", "security"]}
        assert validate.validate_personalization_consistency(config) == []

    def test_personalization_not_dict_returns_empty(self) -> None:
        """personalization set to null/string → no errors (graceful skip)."""
        config = {"dimensions": ["correctness"], "personalization": None}
        assert validate.validate_personalization_consistency(config) == []

    def test_no_dimensions_returns_empty(self) -> None:
        """No enabled dimensions → skip consistency checks."""
        config = {
            "dimensions": [],
            "personalization": {"fix_priority_order": ["nonexistent"]},
        }
        assert validate.validate_personalization_consistency(config) == []

    def test_fix_priority_order_with_valid_dimensions(self) -> None:
        """fix_priority_order containing only enabled dimensions → no errors."""
        config = {
            "dimensions": ["correctness", "security", "performance"],
            "personalization": {
                "fix_priority_order": ["security", "correctness", "performance"],
            },
        }
        assert validate.validate_personalization_consistency(config) == []

    def test_fix_priority_order_with_invalid_dimension(self) -> None:
        """fix_priority_order referencing disabled dimension → error."""
        config = {
            "dimensions": ["correctness", "security"],
            "personalization": {
                "fix_priority_order": ["security", "nonexistent-dim"],
            },
        }
        errors = validate.validate_personalization_consistency(config)
        assert len(errors) == 1
        assert "fix_priority_order" in errors[0]
        assert "nonexistent-dim" in errors[0]

    def test_dimension_focus_with_valid_dimension(self) -> None:
        """dimension_focus referencing enabled dimension → no errors."""
        config = {
            "dimensions": ["correctness", "security"],
            "personalization": {
                "dimension_focus": [
                    {"dimension": "security", "focus": "SQL injection"},
                ],
            },
        }
        assert validate.validate_personalization_consistency(config) == []

    def test_dimension_focus_with_invalid_dimension(self) -> None:
        """dimension_focus referencing disabled dimension → error."""
        config = {
            "dimensions": ["correctness"],
            "personalization": {
                "dimension_focus": [
                    {"dimension": "performance", "focus": "N+1 queries"},
                ],
            },
        }
        errors = validate.validate_personalization_consistency(config)
        assert len(errors) == 1
        assert "dimension_focus" in errors[0]
        assert "performance" in errors[0]

    def test_known_intentional_with_valid_dimension(self) -> None:
        """known_intentional referencing enabled dimension → no errors."""
        config = {
            "dimensions": ["correctness", "tech-debt"],
            "personalization": {
                "known_intentional": [
                    {"file": "db/queries.py", "line": 42, "dimension": "tech-debt", "reason": "intentional"},
                ],
            },
        }
        assert validate.validate_personalization_consistency(config) == []

    def test_known_intentional_with_invalid_dimension(self) -> None:
        """known_intentional referencing disabled dimension → error with index."""
        config = {
            "dimensions": ["correctness"],
            "personalization": {
                "known_intentional": [
                    {"file": "db/queries.py", "line": 42, "dimension": "tech-debt", "reason": "intentional"},
                ],
            },
        }
        errors = validate.validate_personalization_consistency(config)
        assert len(errors) == 1
        assert "known_intentional[0]" in errors[0]
        assert "tech-debt" in errors[0]

    def test_multiple_errors_across_categories(self) -> None:
        """Errors in all three categories are reported together."""
        config = {
            "dimensions": ["correctness"],
            "personalization": {
                "fix_priority_order": ["bad-dim-1"],
                "dimension_focus": [{"dimension": "bad-dim-2", "focus": "x"}],
                "known_intentional": [
                    {"file": "f.py", "line": 1, "dimension": "bad-dim-3", "reason": "r"},
                ],
            },
        }
        errors = validate.validate_personalization_consistency(config)
        assert len(errors) == 3
        assert any("fix_priority_order" in e for e in errors)
        assert any("dimension_focus" in e for e in errors)
        assert any("known_intentional[0]" in e for e in errors)

    def test_end_to_end_validate_config_with_consistent_personalization(
        self, tmp_path: Path, schema_path: Path
    ) -> None:
        """Full validate_config() accepts consistent personalization."""
        config = {
            "goal": "test",
            "max_rounds": 3,
            "language": "en",
            "dimensions": ["correctness", "security"],
            "review": {"scope": "full"},
            "atomic": {"max_lines": 20, "max_adjacent_methods": 3},
            "git": {"target_branch": "main", "use_worktree": False, "push_per_round": True},
            "validation": {
                "command_whitelist": ["ruff"],
                "commands": {"python": ["ruff check src/"]},
            },
            "reviewer": {"output_schema_validation": True},
            "personalization": {
                "version": "1.0",
                "fix_priority_order": ["security", "correctness"],
                "dimension_focus": [{"dimension": "security", "focus": "SQLi"}],
                "known_intentional": [
                    {"file": "f.py", "line": 1, "dimension": "correctness", "reason": "ok"},
                ],
            },
        }
        config_path = tmp_path / "iterate.config.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        errors = validate.validate_config(config_path, schema_path)
        assert errors == []

    def test_end_to_end_validate_config_with_inconsistent_personalization(
        self, tmp_path: Path, schema_path: Path
    ) -> None:
        """Full validate_config() reports inconsistent personalization dimensions."""
        config = {
            "goal": "test",
            "max_rounds": 3,
            "language": "en",
            "dimensions": ["correctness"],
            "review": {"scope": "full"},
            "atomic": {"max_lines": 20, "max_adjacent_methods": 3},
            "git": {"target_branch": "main", "use_worktree": False, "push_per_round": True},
            "validation": {
                "command_whitelist": ["ruff"],
                "commands": {"python": ["ruff check src/"]},
            },
            "reviewer": {"output_schema_validation": True},
            "personalization": {
                "version": "1.0",
                "fix_priority_order": ["security"],  # security not in dimensions
            },
        }
        config_path = tmp_path / "iterate.config.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        errors = validate.validate_config(config_path, schema_path)
        assert any("fix_priority_order" in e and "security" in e for e in errors)


def _build_minimal_source(tmp_path: Path) -> Path:
    """Create a minimal skill source tree for install tests."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text("skill", encoding="utf-8")
    (source / "config").mkdir()
    (source / "config" / "iterate.config.yaml").write_text(
        yaml.safe_dump({"goal": "test", "dimensions": ["correctness"]}),
        encoding="utf-8",
    )
    (source / "config" / "config.schema.json").write_text("{}", encoding="utf-8")
    (source / "config" / "dimensions.yaml").write_text("correctness:", encoding="utf-8")
    (source / "config" / "dimensions").mkdir()
    (source / "config" / "dimensions" / "correctness.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "正确性",
                "name_en": "Correctness",
                "priority": "critical",
                "focus": "Crash risks.",
            }
        ),
        encoding="utf-8",
    )
    (source / "scripts").mkdir()
    (source / "scripts" / "validate.py").write_text(
        "def validate_config(path, schema_path=None, dimensions_dir=None): return []\n",
        encoding="utf-8",
    )
    (source / "scripts" / "requirements.txt").write_text("reqs", encoding="utf-8")
    (source / "templates").mkdir()
    (source / "templates" / "iterate-decisions.template.md").write_text(
        "template", encoding="utf-8"
    )
    # v2.0.0: CLI onboarding system files are now in REQUIRED_FILES,
    # so the minimal source must include stubs for them.
    (source / "iterate_cli").mkdir()
    (source / "iterate_cli" / "__init__.py").write_text(
        '"""iterate CLI package."""\n', encoding="utf-8"
    )
    (source / "pyproject.toml").write_text(
        '[project]\nname = "iterate-skill"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    (source / "templates" / "ITERATE.template.md").write_text(
        "# ITERATE template\n", encoding="utf-8"
    )
    (source / "templates" / "onboarding-playbook.md").write_text(
        "# Onboarding playbook\n", encoding="utf-8"
    )
    return source


class TestInstallScript:
    def test_dry_run_lists_files(self, tmp_path: Path) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        from install import main as install_main

        assert (
            install_main(
                ["install", "--ai", "trae", "--target", str(target), "--dry-run"],
                source=source,
            )
            == 0
        )
        assert not (target / ".trae").exists()

    def test_legacy_invocation_dry_run(self, tmp_path: Path) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        from install import main as install_main

        assert (
            install_main(
                ["--ai", "trae", "--target", str(target), "--dry-run"], source=source
            )
            == 0
        )
        assert not (target / ".trae").exists()

    def test_install_copies_files(self, tmp_path: Path) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        from install import main as install_main

        assert (
            install_main(["install", "--ai", "claude", "--target", str(target)], source=source)
            == 0
        )
        assert (target / ".claude" / "skills" / "iterate" / "SKILL.md").exists()
        assert (
            target / ".claude" / "skills" / "iterate" / "config" / "dimensions" / "correctness.yaml"
        ).exists()

    def test_install_all_creates_multiple_folders(self, tmp_path: Path) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        from install import main as install_main

        assert install_main(["install", "--ai", "all", "--target", str(target)], source=source) == 0
        assert (target / ".trae" / "skills" / "iterate").exists()
        assert (target / ".claude" / "skills" / "iterate").exists()


class TestArrowSelectState:
    """Unit tests for the arrow-key multi-select state machine."""

    def test_default_all_selected(self) -> None:
        from install import _ArrowSelectState

        state = _ArrowSelectState(["a", "b", "c"])
        assert state.result == ["a", "b", "c"]
        assert state.rows == ["a", "b", "c", None]

    def test_default_none_selected(self) -> None:
        from install import _ArrowSelectState

        state = _ArrowSelectState(["a", "b"], default_all=False)
        assert state.result == []

    def test_move_wraps(self) -> None:
        from install import _ArrowSelectState

        state = _ArrowSelectState(["a", "b"])
        state.move(1)
        assert state.index == 1
        state.move(1)  # wraps onto the Done row
        assert state.index == 2
        state.move(-1)
        assert state.index == 1

    def test_toggle_current(self) -> None:
        from install import _ArrowSelectState

        state = _ArrowSelectState(["a", "b"], default_all=False)
        state.toggle_current()
        assert state.result == ["a"]
        state.toggle_current()
        assert state.result == []

    def test_toggle_on_done_row_finishes(self) -> None:
        from install import _ArrowSelectState

        state = _ArrowSelectState(["a", "b"])
        state.index = 2  # Done row
        state.toggle_current()
        assert state.finished is True

    def test_cancel_clears_and_finishes(self) -> None:
        from install import _ArrowSelectState

        state = _ArrowSelectState(["a", "b"])
        state.cancel()
        assert state.finished is True
        assert state.result == []

    def test_result_sorted(self) -> None:
        from install import _ArrowSelectState

        state = _ArrowSelectState(["b", "a"])
        assert state.result == ["a", "b"]

    def test_read_arrow_key_decodes(self) -> None:
        import io

        from install import _read_arrow_key

        assert _read_arrow_key(io.StringIO("\x1b[A")) == "up"
        assert _read_arrow_key(io.StringIO("\x1b[B")) == "down"
        assert _read_arrow_key(io.StringIO(" ")) == "toggle"
        assert _read_arrow_key(io.StringIO("\r")) == "toggle"
        assert _read_arrow_key(io.StringIO("q")) == "cancel"
        assert _read_arrow_key(io.StringIO("x")) is None

    def test_render_arrow_select_marks_selected(self) -> None:
        from install import _ArrowSelectState, _render_arrow_select

        state = _ArrowSelectState(["a", "b"], default_all=False)
        rendered = _render_arrow_select(state, "title")
        assert "○" in rendered
        assert "◉" not in rendered
        state.toggle_current()  # select "a"
        rendered = _render_arrow_select(state, "title")
        assert "◉" in rendered
        assert "Done" in rendered

    def test_preselected_only_when_provided(self) -> None:
        from install import _ArrowSelectState

        # Only the preselected option starts selected.
        state = _ArrowSelectState(["a", "b", "c"], preselected={"a"})
        assert state.result == ["a"]

        # Unknown options in the preselected set are ignored.
        state = _ArrowSelectState(["a", "b", "c"], preselected={"a", "x"})
        assert state.result == ["a"]

        # default_all is ignored when preselected is provided.
        state = _ArrowSelectState(["a", "b", "c"], default_all=True, preselected={"b"})
        assert state.result == ["b"]


class TestMultiSelectPreselect:
    def test_prompt_multi_select_preselects_only_detected(self) -> None:
        from install import _prompt_multi_select

        inputs = iter([""])  # just press Enter to confirm
        result = _prompt_multi_select(["a", "b", "c"], lambda _: next(inputs), preselected={"a"})
        assert result == ["a"]

    def test_prompt_multi_select_no_preselect_selects_all_by_default(self) -> None:
        from install import _prompt_multi_select

        inputs = iter([""])
        result = _prompt_multi_select(["a", "b"], lambda _: next(inputs))
        assert result == ["a", "b"]


class TestInteractiveSelectionPreselect:
    def test_preselects_only_detected_tools(self, tmp_path, monkeypatch) -> None:
        from install import Path as IPath
        from install import interactive_select_assistants

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        (fake_home / ".trae" / "skills").mkdir(parents=True)
        (fake_home / ".cursor" / "skills").mkdir(parents=True)

        monkeypatch.setattr(IPath, "home", lambda: fake_home)
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        inputs = iter([""])  # just press Enter to confirm
        result = interactive_select_assistants(fake_home, lambda _: next(inputs))
        assert "trae" in result
        assert "cursor" in result
        assert "claude" not in result  # not detected -> not pre-selected


class TestInstallCancelExitCode:
    def test_cancel_returns_nonzero(self, tmp_path: Path, monkeypatch) -> None:
        from install import install_command

        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        monkeypatch.setattr("install.interactive_select_assistants", lambda *a, **k: [])
        # No assistants selected -> installation cancelled -> non-zero exit.
        assert (
            install_command(None, target, False, source, False, False, input) == 1
        )


class TestConfigCommand:
    def test_config_init_copies_master(self, tmp_path: Path) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        from install import main as install_main

        assert install_main(["config", "--init", "--target", str(target)], source=source) == 0
        assert (target / "iterate.config.yaml").exists()

    def test_config_set_nested_value(self, tmp_path: Path) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        from install import main as install_main

        assert install_main(["config", "--init", "--target", str(target)], source=source) == 0
        assert (
            install_main(
                [
                    "config",
                    "--target",
                    str(target),
                    "--set",
                    "goal=New goal",
                    "--set",
                    "max_rounds=10",
                    "--set",
                    "review.scope=changed-only",
                ],
                source=source,
            )
            == 0
        )
        config = yaml.safe_load((target / "iterate.config.yaml").read_text(encoding="utf-8"))
        assert config["goal"] == "New goal"
        assert config["max_rounds"] == 10
        assert config["review"]["scope"] == "changed-only"

    def test_config_set_list_value(self, tmp_path: Path) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        from install import main as install_main

        assert install_main(["config", "--init", "--target", str(target)], source=source) == 0
        assert (
            install_main(
                [
                    "config",
                    "--target",
                    str(target),
                    "--set",
                    "dimensions=[correctness, security]",
                ],
                source=source,
            )
            == 0
        )
        config = yaml.safe_load((target / "iterate.config.yaml").read_text(encoding="utf-8"))
        assert config["dimensions"] == ["correctness", "security"]

    def test_config_set_invalid_value_is_reverted(self, tmp_path: Path, monkeypatch) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        import install
        from install import main as install_main

        assert install_main(["config", "--init", "--target", str(target)], source=source) == 0
        original_text = (target / "iterate.config.yaml").read_text(encoding="utf-8")

        def fake_validate(_target: Path, _source: Path) -> list[str]:
            return ["max_rounds exceeds allowed range"]

        monkeypatch.setattr(install, "_validate_project_config", fake_validate)

        assert (
            install_main(
                ["config", "--target", str(target), "--set", "max_rounds=99"],
                source=source,
            )
            == 1
        )
        assert (target / "iterate.config.yaml").read_text(encoding="utf-8") == original_text

    def test_config_list_prints_yaml(self, tmp_path: Path, capsys) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        from install import main as install_main

        assert install_main(["config", "--init", "--target", str(target)], source=source) == 0
        assert install_main(["config", "--list", "--target", str(target)], source=source) == 0
        captured = capsys.readouterr()
        assert "goal: test" in captured.out

    def test_config_init_refuses_overwrite(self, tmp_path: Path) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()
        (target / "iterate.config.yaml").write_text("existing: true", encoding="utf-8")

        from install import main as install_main

        assert install_main(["config", "--init", "--target", str(target)], source=source) == 1


class TestForceAndGlobal:
    def test_install_without_force_skips_existing(self, tmp_path: Path, capsys) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        from install import main as install_main

        assert install_main(["install", "--ai", "trae", "--target", str(target)], source=source) == 0
        (target / ".trae" / "skills" / "iterate" / "SKILL.md").write_text(
            "modified", encoding="utf-8"
        )
        assert (
            install_main(["install", "--ai", "trae", "--target", str(target)], source=source) == 0
        )
        captured = capsys.readouterr()
        assert "Skipped (already exists, use --force)" in captured.out
        assert (target / ".trae" / "skills" / "iterate" / "SKILL.md").read_text(
            encoding="utf-8"
        ) == "modified"

    def test_install_with_force_overwrites(self, tmp_path: Path) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        from install import main as install_main

        assert install_main(["install", "--ai", "trae", "--target", str(target)], source=source) == 0
        (target / ".trae" / "skills" / "iterate" / "SKILL.md").write_text(
            "modified", encoding="utf-8"
        )
        assert (
            install_main(
                ["install", "--ai", "trae", "--target", str(target), "--force"], source=source
            )
            == 0
        )
        assert (target / ".trae" / "skills" / "iterate" / "SKILL.md").read_text(
            encoding="utf-8"
        ) == "skill"

    def test_global_install_uses_home(self, tmp_path: Path, monkeypatch) -> None:
        source = _build_minimal_source(tmp_path)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        from install import main as install_main

        assert (
            install_main(["install", "--ai", "claude", "--global"], source=source) == 0
        )
        assert (fake_home / ".claude" / "skills" / "iterate" / "SKILL.md").exists()


class TestUninstallCommand:
    def test_uninstall_removes_files(self, tmp_path: Path) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        from install import main as install_main

        assert install_main(["install", "--ai", "trae", "--target", str(target)], source=source) == 0
        assert (target / ".trae" / "skills" / "iterate").exists()
        assert (
            install_main(["uninstall", "--ai", "trae", "--target", str(target), "--yes"], source=source)
            == 0
        )
        assert not (target / ".trae" / "skills" / "iterate").exists()

    def test_uninstall_global(self, tmp_path: Path, monkeypatch) -> None:
        source = _build_minimal_source(tmp_path)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        from install import main as install_main

        assert install_main(["install", "--ai", "trae", "--global"], source=source) == 0
        assert (fake_home / ".trae" / "skills" / "iterate").exists()
        assert (
            install_main(["uninstall", "--ai", "trae", "--global", "--yes"], source=source) == 0
        )
        assert not (fake_home / ".trae" / "skills" / "iterate").exists()

    def test_uninstall_without_yes_prompts_and_cancels(self, tmp_path: Path, monkeypatch) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        from install import main as install_main

        assert install_main(["install", "--ai", "trae", "--target", str(target)], source=source) == 0
        monkeypatch.setattr("builtins.input", lambda _prompt: "n")
        assert install_main(["uninstall", "--ai", "trae", "--target", str(target)], source=source) == 0
        assert (target / ".trae" / "skills" / "iterate").exists()


class TestUpdateCommand:
    def test_update_detects_installed_assistants(self, tmp_path: Path, monkeypatch) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        import install
        from install import main as install_main

        monkeypatch.setattr(install, "_fetch_latest_release_info", lambda _token: None)

        assert install_main(["install", "--ai", "trae", "--target", str(target)], source=source) == 0
        (target / ".trae" / "skills" / "iterate" / "SKILL.md").write_text(
            "modified", encoding="utf-8"
        )
        assert install_main(["update", "--target", str(target)], source=source) == 0
        assert (target / ".trae" / "skills" / "iterate" / "SKILL.md").read_text(
            encoding="utf-8"
        ) == "modified"

    def test_update_with_force_refreshes_files(self, tmp_path: Path, monkeypatch) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        import install
        from install import main as install_main

        monkeypatch.setattr(install, "_fetch_latest_release_info", lambda _token: None)

        assert install_main(["install", "--ai", "trae", "--target", str(target)], source=source) == 0
        (target / ".trae" / "skills" / "iterate" / "SKILL.md").write_text(
            "modified", encoding="utf-8"
        )
        assert (
            install_main(["update", "--ai", "trae", "--target", str(target), "--force"], source=source)
            == 0
        )
        assert (target / ".trae" / "skills" / "iterate" / "SKILL.md").read_text(
            encoding="utf-8"
        ) == "skill"

    def test_update_without_installation_fails(self, tmp_path: Path, monkeypatch) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        import install
        from install import main as install_main

        monkeypatch.setattr(install, "_fetch_latest_release_info", lambda _token: None)

        assert install_main(["update", "--target", str(target)], source=source) == 1

    def test_update_downloads_release_source(self, tmp_path: Path, monkeypatch) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        import install
        from install import main as install_main

        release_parent = tmp_path / "release"
        release_parent.mkdir()
        release_source = _build_minimal_source(release_parent)
        (release_source / "SKILL.md").write_text("released-skill", encoding="utf-8")

        monkeypatch.setattr(
            install,
            "_fetch_latest_release_info",
            lambda _token: {
                "tag": "v1.2.3",
                "tarball_url": "https://example.com/release.tar.gz",
                "checksum_url": "https://example.com/SHA256SUMS.txt",
            },
        )
        monkeypatch.setattr(
            install, "_download_release_source", lambda _url, _checksum_url, _token: release_source
        )

        assert install_main(["install", "--ai", "trae", "--target", str(target)], source=source) == 0
        assert (target / ".trae" / "skills" / "iterate" / "SKILL.md").read_text(encoding="utf-8") == "skill"
        assert (
            install_main(["update", "--ai", "trae", "--target", str(target), "--force", "--yes"], source=source)
            == 0
        )
        assert (target / ".trae" / "skills" / "iterate" / "SKILL.md").read_text(
            encoding="utf-8"
        ) == "released-skill"


class TestValidateCommand:
    def test_validate_passes(self, tmp_path: Path) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        from install import main as install_main

        assert install_main(["config", "--init", "--target", str(target)], source=source) == 0
        assert install_main(["validate", "--target", str(target)], source=source) == 0

    def test_validate_fails_when_missing(self, tmp_path: Path) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        from install import main as install_main

        assert install_main(["validate", "--target", str(target)], source=source) == 1


class TestParseValue:
    def test_explicit_booleans(self) -> None:
        from install import parse_value

        assert parse_value("true") is True
        assert parse_value("false") is False

    def test_yaml_boolean_aliases_are_strings(self) -> None:
        from install import parse_value

        assert parse_value("yes") == "yes"
        assert parse_value("no") == "no"
        assert parse_value("on") == "on"

    def test_lists_and_strings(self) -> None:
        from install import parse_value

        assert parse_value("[a, b]") == ["a", "b"]
        assert parse_value("plain") == "plain"


class TestLegacyArgParser:
    def test_legacy_install_parses_known_options(self) -> None:
        from install import parse_legacy_args

        namespace = parse_legacy_args(["--ai", "trae", "--target", "/tmp/foo"])
        assert namespace is not None
        assert namespace.ai == "trae"
        assert str(namespace.target) == "/tmp/foo"
        assert namespace.command == "install"

    def test_legacy_parser_ignores_unknown_positional(self) -> None:
        from install import parse_legacy_args

        assert parse_legacy_args(["--ai", "trae", "config"]) is None


class TestMain:
    def test_config_subcommand(self, tmp_path: Path, valid_config: dict[str, Any], schema_path: Path) -> None:
        path = tmp_path / "iterate.config.yaml"
        path.write_text(yaml.safe_dump(valid_config), encoding="utf-8")
        assert validate.main(["config", str(path), str(schema_path)]) == 0

    def test_decisions_subcommand(self, tmp_path: Path) -> None:
        path = tmp_path / ".iterate_decisions.md"
        path.write_text(
            "# Iterate Decision Log\n\n"
            "## Round 1 — 2026-01-01\n\n"
            "### Atomic Fixes (Direct)\n"
            "### Architectural Fixes (Approved + Executed)\n"
            "### Architectural Fixes (Deferred to Next Round)\n"
            "### AI Important Decisions\n"
            "### Validation\n",
            encoding="utf-8",
        )
        assert validate.main(["decisions", str(path)]) == 0

    def test_unknown_command(self) -> None:
        assert validate.main(["unknown", "foo"]) == 1

    def test_missing_arguments(self) -> None:
        assert validate.main([]) == 1


class TestSkillMarkdownFile:
    def test_skill_md_exists(self) -> None:
        assert (REPO_ROOT / "SKILL.md").exists()

    def test_skill_md_has_valid_frontmatter(self) -> None:
        text = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
        assert text.startswith("---")
        _, frontmatter, _ = text.split("---", 2)
        meta = yaml.safe_load(frontmatter)
        assert isinstance(meta, dict)
        assert meta.get("name") == "iterate"
        assert isinstance(meta.get("description"), str)
        assert meta.get("description")
        assert meta.get("version") == ITERATE_VERSION

    def test_skill_md_body_is_non_empty(self) -> None:
        text = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
        parts = text.split("---", 2)
        assert len(parts) == 3
        assert len(parts[2].strip()) > 100
