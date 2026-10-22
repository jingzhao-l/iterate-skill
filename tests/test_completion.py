"""Tests for ``iterate completion`` — generated bash/zsh/fish completion.

The script is generated from the live argparse parser (not a hand-maintained
list), so these tests pin both the user contract and the parser coupling:

* every real subcommand appears in every shell's script;
* per-command options appear where they are valid, hidden options do not;
* fixed choices and path arguments get value/``_files``/``_directories`` rules;
* the generated scripts are syntactically valid for the shells installed here;
* ``--json`` and unknown shells are usage errors that still honour the global
  one-JSON-document contract.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iterate_cli import cli
from iterate_cli.cli import main as cli_main
from iterate_cli.completion import (
    SHELLS,
    render_completion,
    validate_script_syntax,
)


def _commands() -> list[str]:
    return list(cli._subcommands(cli._build_parser()))


def _render(shell: str) -> str:
    return render_completion(shell, cli._build_parser())


class TestScriptContent:
    @pytest.mark.parametrize("shell", SHELLS)
    def test_every_command_is_completed(self, shell: str) -> None:
        script = _render(shell)
        for command in _commands():
            assert command in script, (shell, command)

    @pytest.mark.parametrize("shell", SHELLS)
    def test_new_report_feature_is_completed(self, shell: str) -> None:
        script = _render(shell)
        assert "report" in script

    def test_bash_completes_options_and_value_choices(self) -> None:
        script = _render("bash")

        assert "complete -F _iterate_completion iterate" in script
        assert "--strict" in script
        assert '_iterate_complete_dirs' in script
        assert "init:--language" in script
        assert 'compgen -W "zh en"' in script
        assert "import) _iterate_complete_files" in script

    def test_bash_omits_hidden_and_inapplicable_options(self) -> None:
        script = _render("bash")

        # `onboard --json` is rejected by the CLI, so it must not be offered.
        onboard_line = next(
            line for line in script.splitlines() if line.strip().startswith("onboard)")
        )
        assert "--json" not in onboard_line
        # ... while `doctor --json` is valid.
        doctor_line = next(
            line for line in script.splitlines() if line.strip().startswith("doctor)")
        )
        assert "--json" in doctor_line

    def test_zsh_uses_the_native_completion_framework(self) -> None:
        script = _render("zsh")

        assert script.startswith("#compdef iterate")
        assert "_describe -t commands" in script
        assert "compdef _iterate iterate" in script
        assert "init:--language" in script
        assert "_values 'value' zh en" in script
        assert "_directories" in script

    def test_fish_registers_subcommands_and_required_args(self) -> None:
        script = _render("fish")

        assert "complete -c iterate" in script
        assert "-a onboard" in script
        assert "-l project" in script
        assert "-r" in script
        assert "-a 'zh en'" in script

    def test_fish_does_not_disable_file_completion_globally(self) -> None:
        script = _render("fish")

        # A bare `complete -c iterate -f` would suppress files for every
        # command, including `iterate import <bundle>`.
        assert "complete -c iterate -f\n" not in script


class TestShellValidity:
    @pytest.mark.parametrize("shell", SHELLS)
    def test_generated_script_parses(self, shell: str) -> None:
        import shutil

        if shutil.which(shell) is None:
            pytest.skip(f"{shell} not installed")
        script = _render(shell)
        assert validate_script_syntax(shell, script) is None


class TestCliContract:
    def test_prints_script_to_stdout(self, capsys) -> None:
        capsys.readouterr()

        code = cli_main(["completion", "bash"])

        out = capsys.readouterr().out
        assert code == 0
        assert out.startswith("# bash completion for iterate")

    def test_works_outside_a_project(self, tmp_path: Path, capsys) -> None:
        capsys.readouterr()

        code = cli_main(
            ["completion", "zsh", "-p", str(tmp_path / "does-not-exist")]
        )

        assert code == 0
        assert "#compdef iterate" in capsys.readouterr().out

    def test_unknown_shell_is_a_usage_error(self, capsys) -> None:
        capsys.readouterr()

        with pytest.raises(SystemExit) as excinfo:
            cli_main(["completion", "powershell"])

        assert excinfo.value.code == 2
        assert "invalid choice" in capsys.readouterr().err

    def test_json_is_refused_with_one_document(self, capsys) -> None:
        capsys.readouterr()

        code = cli_main(["--json", "completion", "bash"])

        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert code == 2
        assert "not supported" in payload["error"]
        assert "not supported" in captured.err

    def test_help_topic_exists(self, capsys) -> None:
        capsys.readouterr()

        code = cli_main(["help", "completion"])

        out = capsys.readouterr().out
        assert code == 0
        assert "usage: iterate completion" in out
        assert "bash" in out and "zsh" in out and "fish" in out

    def test_install_hint_never_pollutes_redirected_stdout(
        self, monkeypatch, capsys
    ) -> None:
        """`iterate completion zsh > _iterate` must produce only the script.

        stderr still points at the terminal in that invocation, so the hint
        must be written to stderr — tui.hint writes to stdout.
        """
        monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
        capsys.readouterr()

        code = cli_main(["completion", "bash"])

        captured = capsys.readouterr()
        assert code == 0
        assert captured.out.startswith("# bash completion for iterate")
        assert captured.out.count("# bash completion for iterate") == 1
        assert "Install:" in captured.err
