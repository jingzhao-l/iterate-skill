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

        from install import main as install_main
        import install

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

        from install import main as install_main
        import install

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

        from install import main as install_main
        import install

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

        from install import main as install_main
        import install

        monkeypatch.setattr(install, "_fetch_latest_release_info", lambda _token: None)

        assert install_main(["update", "--target", str(target)], source=source) == 1

    def test_update_downloads_release_source(self, tmp_path: Path, monkeypatch) -> None:
        source = _build_minimal_source(tmp_path)
        target = tmp_path / "target"
        target.mkdir()

        from install import main as install_main
        import install

        release_parent = tmp_path / "release"
        release_parent.mkdir()
        release_source = _build_minimal_source(release_parent)
        (release_source / "SKILL.md").write_text("released-skill", encoding="utf-8")

        monkeypatch.setattr(
            install,
            "_fetch_latest_release_info",
            lambda _token: {"tag": "v1.2.3", "tarball_url": "https://example.com/release.tar.gz"},
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
        assert meta.get("version") == "1.0.0"

    def test_skill_md_body_is_non_empty(self) -> None:
        text = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
        parts = text.split("---", 2)
        assert len(parts) == 3
        assert len(parts[2].strip()) > 100
