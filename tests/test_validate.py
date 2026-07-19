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

import validate


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
                "vm": ["ruff check src/", "pytest tests/ -q"],
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
        valid_config["validation"]["commands"]["vm"].append("rm -rf src/")
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
