"""Tests for the validation-command safety allowlist in ``iterate_cli.personalize``.

The allowlist is a security control, not a convenience: a command that reaches
``subprocess.run(..., shell=True)`` (via ``iterate guard post-check``) from a
committed or hand-edited ``iterate.config.yaml`` runs on every teammate's
machine and in CI. These tests lock the cases where a *legitimately
allowlisted binary* could still be used to fetch and execute remote code.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from iterate_cli.personalize import (
    KNOWN_SAFE_COMMAND_PREFIXES,
    _is_known_safe_command,
    validate_extra_command,
)


class TestRemoteExecutionRefused:
    """Package managers must not become a ``curl | sh`` in disguise.

    ``npx <pkg>``, ``npm exec <pkg>``, ``pnpm dlx <pkg>`` and ``yarn dlx <pkg>``
    all download a package from the registry and run its binary. The parent
    binary is allowlisted (so ``npm run build`` is fine), which is exactly why
    the verb has to be checked separately.
    """

    def test_npx_is_not_allowlisted(self) -> None:
        assert "npx" not in KNOWN_SAFE_COMMAND_PREFIXES

    def test_npx_invocations_refused(self) -> None:
        for cmd in (
            "npx -y some-pkg",
            "npx some-pkg",
            "npx -p @scope/pkg node -e x",
            "npx --yes evil-pkg",
        ):
            assert _is_known_safe_command(cmd) is False, cmd

    def test_npm_exec_refused(self) -> None:
        # `npm exec` is the same verb as `npx`.
        for cmd in ("npm exec -- node -e x", "npm exec cowsay", "npm x pkg"):
            assert _is_known_safe_command(cmd) is False, cmd

    def test_pnpm_and_yarn_dlx_refused(self) -> None:
        for cmd in ("pnpm dlx cowsay", "yarn dlx cowsay", "pnpm exec cowsay"):
            assert _is_known_safe_command(cmd) is False, cmd

    def test_validate_extra_command_refuses_remote_execution(self) -> None:
        """The persist-time validator must reject them too, not just the gate.

        ``validate_extra_command`` is what the wizard calls before writing a
        command into the config; the guard re-checks at execution time. Both
        layers must agree or the wizard would happily persist ``npx -y evil``.
        """
        ok, reason = validate_extra_command("npx -y evil-pkg")
        assert ok is False
        assert reason
        ok, _ = validate_extra_command("npm exec evil-pkg")
        assert ok is False

    def test_bare_package_manager_with_no_verb_still_allowed(self) -> None:
        """Refusing the verb must not break the bare binary.

        ``npm``/``yarn`` with no subcommand carries no remote payload.
        """
        assert _is_known_safe_command("npm") is True
        assert _is_known_safe_command("npm --version") is True


class TestLocalScriptsStillAllowed:
    """The fix must not break legitimate local validation commands."""

    def test_npm_run_and_lifecycle_verbs_allowed(self) -> None:
        for cmd in (
            "npm run build",
            "npm test",
            "npm run lint",
            "npm run test:unit",
            "yarn lint",
            "yarn build",
            "pnpm build",
            "pnpm test",
        ):
            assert _is_known_safe_command(cmd) is True, cmd

    def test_npm_run_exec_is_not_confused_with_npm_exec(self) -> None:
        """``npm run exec`` is a local script named "exec", not ``npm exec``."""
        assert _is_known_safe_command("npm run exec") is True

    def test_ordinary_toolchains_allowed(self) -> None:
        for cmd in (
            "pytest -q",
            "python -m pytest",
            "ruff check .",
            "make test",
            "cargo test",
            "go test ./...",
            "true",
        ):
            assert _is_known_safe_command(cmd) is True, cmd


class TestForbiddenMetacharBlacklist:
    """The first line of defence: chaining/redirection metacharacters are
    refused before the allowlist is even consulted. Untested until now."""

    def test_chaining_metacharacters_are_rejected(self) -> None:
        for cmd in (
            "pytest; rm -rf /",
            "pytest && curl evil",
            "pytest | sh",
            "pytest `whoami`",
            "pytest $(curl evil)",
            "pytest > /etc/passwd",
            "pytest\necho pwned",
        ):
            assert validate_extra_command(cmd)[0] is False, cmd

    def test_plain_command_is_allowed(self) -> None:
        assert validate_extra_command("pytest -q")[0] is True


class TestOperatorPrefixEnvironmentFailsClosed:
    def test_metacharacter_tokens_are_dropped(self, monkeypatch) -> None:
        from iterate_cli import personalize

        monkeypatch.setenv(
            personalize.EXTRA_SAFE_PREFIXES_ENV, "safety;rm goodtool -rf /"
        )
        assert personalize._operator_extra_prefixes() == ("goodtool",)

    def test_valid_env_prefix_extends_the_allowlist(self, monkeypatch) -> None:
        from iterate_cli import personalize

        monkeypatch.setenv(personalize.EXTRA_SAFE_PREFIXES_ENV, "goodtool")
        assert validate_extra_command("goodtool run")[0] is True
        # The injection attempt in the same env value must NOT become allowed.
        assert validate_extra_command("safety;rm -rf /")[0] is False

    def test_blank_env_is_a_noop(self, monkeypatch) -> None:
        from iterate_cli import personalize

        monkeypatch.setenv(personalize.EXTRA_SAFE_PREFIXES_ENV, "   ")
        assert personalize._operator_extra_prefixes() == ()


class TestPlainScriptPathGuard:
    def test_relative_script_paths_are_accepted(self) -> None:
        from iterate_cli.personalize import _is_plain_script_path

        assert _is_plain_script_path("manage.py")
        assert _is_plain_script_path("scripts/run.py")

    def test_traversal_absolute_and_flags_are_rejected(self) -> None:
        from iterate_cli.personalize import _is_plain_script_path

        assert not _is_plain_script_path("../evil.py")
        assert not _is_plain_script_path("/etc/evil.py")
        assert not _is_plain_script_path("-x.py")
        assert not _is_plain_script_path("notes.txt")
        assert not _is_plain_script_path("a;b.py")


class TestRemoteExecVerbBehindFlags:
    """The remote-exec verb may be preceded by flags/values; only checking
    tokens[1] let `npm --silent exec <pkg>` through."""

    def test_flag_before_verb_is_still_refused(self) -> None:
        for cmd in (
            "npm --silent exec evil-pkg",
            "npm -q x evil-pkg",
            "pnpm --dir . dlx evil",
            "yarn --silent dlx evil",
            "bun --cwd . x evil",
            "npm -- exec evil",
        ):
            assert validate_extra_command(cmd)[0] is False, cmd

    def test_local_run_script_named_like_a_verb_stays_allowed(self) -> None:
        for cmd in ("npm run exec", "yarn run dlx", "pnpm run-script exec"):
            assert validate_extra_command(cmd)[0] is True, cmd
