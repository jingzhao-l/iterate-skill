"""Tests for ``iterate init`` — prompt-free onboarding from scan defaults.

The interactive wizard is the only historical way to produce the two
onboarding artifacts, which made "set up iterate" impossible from CI, a shell
script, or another skill (all of them would block on prompts). ``init`` fills
that gap while keeping the contract of the existing commands:

* the generated files are the same shape the wizard writes (parsed by the same
  generator, accepted by ``iterate doctor``);
* re-running is safe (an initialized project is reported, never rewritten);
* a non-interactive caller must say ``--yes`` (usage error otherwise), and
  ``--json`` always puts exactly one document on stdout;
* an existing ITERATE.md is only rewritten when its USER-OWNED markers make
  preserving hand edits possible.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iterate_cli import cli
from iterate_cli.cli import main as cli_main
from iterate_cli.generator import has_valid_user_owned_markers

CONFIG = "iterate.config.yaml"
MD = "ITERATE.md"


def _make_python_project(root: Path) -> Path:
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / ".github" / "workflows").mkdir(parents=True)
    return root


def _load(root: Path) -> dict:
    return yaml.safe_load((root / CONFIG).read_text(encoding="utf-8"))


def _run(root: Path, *extra: str) -> int:
    return cli_main(["init", "-p", str(root), "--no-banner", *extra])


class TestFreshProject:
    def test_yes_writes_both_artifacts_with_scan_defaults(
        self, tmp_path: Path, capsys
    ) -> None:
        _make_python_project(tmp_path)
        capsys.readouterr()

        code = _run(tmp_path, "--yes")

        out = capsys.readouterr().out
        assert code == 0
        assert "initialized" in out.lower()
        assert (tmp_path / MD).is_file()
        config = _load(tmp_path)
        assert config["onboarding"]["channel"] == "cli"
        assert config["onboarding"]["fingerprints"]
        assert "correctness" in config["dimensions"]
        assert config["validation"]["commands"]["python"]
        assert config["validation"]["command_whitelist"]
        # Every persisted dimension set only references enabled dimensions.
        enabled = set(config["dimensions"])
        for spec in config["dimension_sets"].values():
            assert set(spec["dimensions"]) <= enabled

    def test_generated_files_pass_doctor(self, tmp_path: Path, capsys) -> None:
        _make_python_project(tmp_path)
        capsys.readouterr()
        _run(tmp_path, "--yes")
        capsys.readouterr()

        code = cli_main(["doctor", "-p", str(tmp_path), "--no-banner"])

        assert code == 0
        assert "healthy" in capsys.readouterr().out.lower()

    def test_json_emits_one_document_with_plan(
        self, tmp_path: Path, capsys
    ) -> None:
        _make_python_project(tmp_path)
        capsys.readouterr()

        code = _run(tmp_path, "--yes", "--json")

        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["ok"] is True
        assert payload["initialized"] is True
        assert payload["written"] == [MD, CONFIG]
        assert payload["detected_languages"] == ["Python"]
        assert payload["dimensions"]
        assert payload["validation_commands"]["python"]
        assert payload["target_branch"] == "main"
        assert payload["language"] == "en"

    def test_empty_directory_initializes_with_defaults(
        self, tmp_path: Path, capsys
    ) -> None:
        """No manifest is a normal project, not a failure worth blocking on."""
        capsys.readouterr()

        code = _run(tmp_path, "--yes", "--json")

        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["initialized"] is True
        assert payload["detected_languages"] == []
        config = _load(tmp_path)
        assert config["dimensions"]
        assert config["validation"]["commands"] == {}


class TestFlags:
    def test_language_branch_and_goal_overrides(
        self, tmp_path: Path, capsys
    ) -> None:
        capsys.readouterr()

        code = _run(
            tmp_path,
            "--yes",
            "--language",
            "zh",
            "--target-branch",
            "develop",
            "--goal",
            "Ship it",
        )

        assert code == 0
        config = _load(tmp_path)
        assert config["language"] == "zh"
        assert config["git"]["target_branch"] == "develop"
        assert config["goal"] == "Ship it"

    def test_empty_goal_is_a_usage_error(self, tmp_path: Path, capsys) -> None:
        capsys.readouterr()

        code = _run(tmp_path, "--yes", "--goal", "   ")

        assert code == 2
        assert "must not be empty" in capsys.readouterr().err
        assert not (tmp_path / CONFIG).exists()

    def test_dry_run_writes_nothing(self, tmp_path: Path, capsys) -> None:
        _make_python_project(tmp_path)
        capsys.readouterr()

        code = _run(tmp_path, "--dry-run", "--json")

        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["dry_run"] is True
        assert payload["would_write"] == [MD, CONFIG]
        assert not (tmp_path / CONFIG).exists()
        assert not (tmp_path / MD).exists()


class TestNonInteractiveContract:
    def test_without_yes_on_non_tty_is_a_usage_error(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: False)
        capsys.readouterr()

        code = _run(tmp_path)

        assert code == 2
        assert "--yes" in capsys.readouterr().err
        assert not (tmp_path / CONFIG).exists()

    def test_json_without_yes_is_a_usage_error_with_one_document(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)
        capsys.readouterr()

        code = _run(tmp_path, "--json")

        payload = json.loads(capsys.readouterr().out)
        assert code == 2
        assert payload["ok"] is False
        assert "--yes" in payload["error"]
        assert not (tmp_path / CONFIG).exists()

    def test_tty_confirmation_can_cancel(self, tmp_path: Path, capsys, monkeypatch) -> None:
        monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)
        monkeypatch.setattr(cli, "_confirm", lambda *a, **k: False)
        capsys.readouterr()

        code = _run(tmp_path)

        assert code == 1
        assert "Cancelled" in capsys.readouterr().out
        assert not (tmp_path / CONFIG).exists()

    def test_tty_confirmation_defaults_to_yes(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)

        def fake_confirm(question: str, *args, **kwargs) -> bool:
            # The prompt must state the default the user gets by pressing Enter.
            assert kwargs.get("default") is True
            return True

        monkeypatch.setattr(cli, "_confirm", fake_confirm)
        capsys.readouterr()

        assert _run(tmp_path) == 0
        assert (tmp_path / CONFIG).is_file()


class TestIdempotencyAndSafety:
    def test_second_run_reports_and_leaves_files_untouched(
        self, tmp_path: Path, capsys
    ) -> None:
        _make_python_project(tmp_path)
        capsys.readouterr()
        _run(tmp_path, "--yes")
        before = (tmp_path / CONFIG).read_bytes()
        md_before = (tmp_path / MD).read_bytes()
        capsys.readouterr()

        code = _run(tmp_path, "--yes", "--json")

        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["initialized"] is False
        assert payload["already_initialized"] is True
        assert (tmp_path / CONFIG).read_bytes() == before
        assert (tmp_path / MD).read_bytes() == md_before

    def test_unparseable_config_is_never_overwritten(
        self, tmp_path: Path, capsys
    ) -> None:
        (tmp_path / CONFIG).write_text("goal: [unclosed\n", encoding="utf-8")
        capsys.readouterr()

        code = _run(tmp_path, "--yes")

        assert code == 1
        assert "could not be parsed" in capsys.readouterr().err
        assert (tmp_path / CONFIG).read_text(encoding="utf-8") == "goal: [unclosed\n"

    def test_iterate_md_without_markers_is_refused(
        self, tmp_path: Path, capsys
    ) -> None:
        (tmp_path / MD).write_text("# Hand written, no markers\n", encoding="utf-8")
        capsys.readouterr()

        code = _run(tmp_path, "--yes")

        assert code == 1
        assert "USER-OWNED" in capsys.readouterr().err
        assert not (tmp_path / CONFIG).exists()
        assert (tmp_path / MD).read_text(encoding="utf-8") == "# Hand written, no markers\n"

    def test_existing_user_section_is_preserved(self, tmp_path: Path, capsys) -> None:
        (tmp_path / MD).write_text(
            "# Project\n\n<!-- ITERATE:USER-OWNED:START -->\nkeep me\n"
            "<!-- ITERATE:USER-OWNED:END -->\n",
            encoding="utf-8",
        )
        capsys.readouterr()

        code = _run(tmp_path, "--yes")

        assert code == 0
        content = (tmp_path / MD).read_text(encoding="utf-8")
        assert has_valid_user_owned_markers(content)
        assert "keep me" in content
        assert (tmp_path / CONFIG).is_file()

    def test_write_failure_rolls_back_both_artifacts(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        """A failed config write must not leave a freshly written ITERATE.md."""
        from iterate_cli import generator

        real_atomic_write = generator.atomic_write

        def failing_write(path: Path, content: str, *args, **kwargs) -> None:
            if path.name == CONFIG:
                raise OSError("disk full")
            real_atomic_write(path, content, *args, **kwargs)

        monkeypatch.setattr(generator, "atomic_write", failing_write)
        capsys.readouterr()

        code = _run(tmp_path, "--yes")

        assert code == 1
        assert "disk full" in capsys.readouterr().err
        assert not (tmp_path / CONFIG).exists()
        assert not (tmp_path / MD).exists()
