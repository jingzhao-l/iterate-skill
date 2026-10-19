"""Tests for command discoverability: ``iterate help`` and "did you mean".

Two gaps are covered here.

1. ``iterate help`` did not exist. A typo produced argparse's full usage wall
   and exit 2, so the only way to learn the command list was to remember
   ``--help`` — and ``iterate help`` (the spelling most CLIs answer to) failed
   as an *invalid command*.

2. A mistyped command produced ``invalid choice: 'statu' (choose from …)``:
   the problem but never the fix, and on a narrow terminal the fix scrolls off.
   The suggestion is now appended to the human message *and* carried in the
   ``--json`` failure document.

The exit-code and JSON contracts are asserted explicitly, because both are
documented promises (``SKILL.md`` / ``iterate --help``): usage errors are exit
2, and a ``--json`` failure still puts exactly one JSON document on stdout.
"""

from __future__ import annotations

import json

import pytest

from iterate_cli import cli
from iterate_cli.cli import main as cli_main

# ---------------------------------------------------------------------------
# iterate help
# ---------------------------------------------------------------------------


class TestHelpCommand:
    def test_bare_help_prints_the_overview_and_returns_0(self, capsys) -> None:
        capsys.readouterr()
        code = cli_main(["help"])

        out = capsys.readouterr().out
        assert code == 0
        assert "usage: iterate" in out

    def test_help_is_listed_as_a_command(self, capsys) -> None:
        """Discovering the help command must not require already knowing it."""
        capsys.readouterr()
        cli_main(["help"])

        assert "help" in capsys.readouterr().out

    def test_help_for_one_command_prints_that_command(self, capsys) -> None:
        capsys.readouterr()
        code = cli_main(["help", "doctor"])

        out = capsys.readouterr().out
        assert code == 0
        assert "usage: iterate doctor" in out
        assert "--fix" in out

    def test_help_for_every_command_succeeds(self, capsys) -> None:
        """Any documented command must be describable through `help <cmd>`."""
        parser = cli._build_parser()
        for name in cli._subcommands(parser):
            capsys.readouterr()
            code = cli_main(["help", name])
            assert code == 0, name
            assert f"usage: iterate {name}" in capsys.readouterr().out, name

    def test_help_works_outside_a_project_directory(self, tmp_path, capsys) -> None:
        """`help` asks about the CLI, so a nonexistent -p must not matter."""
        capsys.readouterr()
        code = cli_main(["help", "-p", str(tmp_path / "does-not-exist")])

        assert code == 0
        assert "usage: iterate" in capsys.readouterr().out

    def test_unknown_topic_is_a_usage_error_with_a_suggestion(self, capsys) -> None:
        capsys.readouterr()
        code = cli_main(["help", "doctro"])

        err = capsys.readouterr().err
        assert code == 2
        assert "did you mean 'doctor'" in err

    def test_unknown_topic_without_a_close_match_lists_the_command(self, capsys) -> None:
        capsys.readouterr()
        code = cli_main(["help", "zzzzzz"])

        err = capsys.readouterr().err
        assert code == 2
        assert "iterate help" in err

    def test_json_help_is_refused_but_still_emits_one_document(self, capsys) -> None:
        capsys.readouterr()
        code = cli_main(["--json", "help"])

        captured = capsys.readouterr()
        assert code == 2
        # stdout: exactly one JSON document (the documented --json contract).
        payload = json.loads(captured.out)
        assert "not supported" in payload["error"]
        # stderr: the same message for a human.
        assert "not supported" in captured.err


# ---------------------------------------------------------------------------
# "did you mean" for a mistyped command
# ---------------------------------------------------------------------------


class TestCommandTypoSuggestions:
    def test_a_near_miss_is_named(self, capsys) -> None:
        capsys.readouterr()
        with pytest.raises(SystemExit) as excinfo:
            cli_main(["statu"])

        err = capsys.readouterr().err
        assert excinfo.value.code == 2
        assert "did you mean 'status'" in err

    @pytest.mark.parametrize(
        ("typo", "expected"),
        [
            ("statu", "status"),
            ("configt", "config"),
            ("showw", "show"),
            ("onbard", "onboard"),
            ("docotr", "doctor"),
        ],
    )
    def test_close_typos_map_to_the_intended_command(
        self, typo: str, expected: str, capsys
    ) -> None:
        capsys.readouterr()
        with pytest.raises(SystemExit):
            cli_main([typo])

        assert f"did you mean '{expected}'" in capsys.readouterr().err

    def test_a_nonsense_token_does_not_guess(self, capsys) -> None:
        """A wrong guess is worse than none: the user follows it."""
        capsys.readouterr()
        with pytest.raises(SystemExit):
            cli_main(["qwertyuiop"])

        err = capsys.readouterr().err
        assert "did you mean" not in err
        # The original argparse diagnosis must survive untouched.
        assert "invalid choice" in err

    def test_usage_error_still_lists_the_valid_choices(self, capsys) -> None:
        """The suggestion is additive: the full choice list stays available."""
        capsys.readouterr()
        with pytest.raises(SystemExit):
            cli_main(["statu"])

        err = capsys.readouterr().err
        assert "choose from" in err
        assert "invariant" in err

    def test_json_failure_carries_the_suggestion(self, capsys) -> None:
        capsys.readouterr()
        with pytest.raises(SystemExit):
            cli_main(["statu", "--json"])

        payload = json.loads(capsys.readouterr().out)
        assert payload["error"] == "invalid usage"
        assert payload["did_you_mean"] == "status"

    def test_json_failure_omits_the_key_when_there_is_no_suggestion(
        self, capsys
    ) -> None:
        capsys.readouterr()
        with pytest.raises(SystemExit):
            cli_main(["qwertyuiop", "--json"])

        payload = json.loads(capsys.readouterr().out)
        assert payload["error"] == "invalid usage"
        assert "did_you_mean" not in payload

    def test_nested_choice_typos_are_suggested_too(self, capsys) -> None:
        """The subparsers inherit the behaviour (`guard`/`fingerprint` actions)."""
        capsys.readouterr()
        with pytest.raises(SystemExit):
            cli_main(["fingerprint", "verfy"])

        assert "did you mean 'verify'" in capsys.readouterr().err

    def test_guard_action_typo_is_suggested(self, capsys) -> None:
        capsys.readouterr()
        with pytest.raises(SystemExit):
            cli_main(["guard", "precheck"])

        assert "did you mean 'pre-check'" in capsys.readouterr().err

    def test_a_valid_command_is_never_reported_as_a_typo(self, tmp_path, capsys) -> None:
        capsys.readouterr()
        code = cli_main(["scan", "--json", "-p", str(tmp_path), "--no-banner"])

        assert code == 0
        assert "did you mean" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Unit-level pieces
# ---------------------------------------------------------------------------


class TestSuggestionHelper:
    def test_did_you_mean_returns_none_below_the_cutoff(self) -> None:
        assert cli._did_you_mean("zzzzzz", ["status", "show"]) is None

    def test_did_you_mean_picks_the_closest(self) -> None:
        assert cli._did_you_mean("stat", ["status", "show", "scan"]) == "status"

    def test_suggestion_is_parsed_from_a_quoted_choices_message(self) -> None:
        """Python ≤3.12 quotes each choice; 3.13 dropped the quotes."""
        message = (
            "argument command: invalid choice: 'statu' "
            "(choose from 'status', 'show', 'scan')"
        )
        assert cli._suggestion_from_usage_error(message) == "status"

    def test_suggestion_is_parsed_from_an_unquoted_choices_message(self) -> None:
        message = (
            "argument command: invalid choice: 'statu' "
            "(choose from status, show, scan)"
        )
        assert cli._suggestion_from_usage_error(message) == "status"

    def test_non_choice_errors_pass_through_without_a_suggestion(self) -> None:
        assert cli._suggestion_from_usage_error("unrecognized arguments: --nope") is None

    def test_last_suggestion_does_not_leak_into_the_next_parse(self, capsys) -> None:
        """The slot is module state; a fresh parser must clear it."""
        capsys.readouterr()
        with pytest.raises(SystemExit):
            cli_main(["statu", "--json"])

        cli._build_parser()
        assert cli._PENDING_USAGE_SUGGESTION is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
