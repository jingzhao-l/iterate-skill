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

from iterate_cli.personalize import (  # noqa: E402
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
