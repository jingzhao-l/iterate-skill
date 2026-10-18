"""Tests for the ``.githooks/pre-push`` gate.

The hook is a shell script, so it is exercised as a subprocess: the real file is
copied into a throwaway repository's ``.git/hooks/`` and run with a synthesized
ref list on stdin, exactly the way ``git push`` would feed it.

Two independent gates are covered:

  * the **author-identity gate**, which refuses to let a commit reach ``main``
    whose author email this repo does not own. GitHub credits commits by author
    email, so a stray identity permanently adds a stranger to the contributor
    list — and undoing that later means rewriting history plus every tag,
    release and npm provenance link built on top of it. That is unrecoverable
    after the fact, which is the whole reason the gate lives here.
  * the **lint gate**, which fails closed when ``ruff check`` cannot pass (or
    cannot be run at all), so a push cannot turn ``main`` red.

The lint half is isolated from the real codebase with a stub ``scripts/check.sh``
so these tests stay fast and only assert the *dispatch* contract (which exit
codes are forwarded and which messages are surfaced), not the lint verdict
itself — that is what CI and ``tests/test_check_sh.py``'s neighbours cover.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / ".githooks" / "pre-push"
NULL_SHA = "0" * 40

# An identity this repo legitimately owns, and one it does not.
OWN_EMAIL = "ET_lin@outlook.com"
FOREIGN_EMAIL = "someone-else@users.noreply.github.com"


@pytest.fixture
def owned_email_in_hook() -> str:
    """The identity the checked-in hook allowlist lets through."""
    source = HOOK.read_text(encoding="utf-8")
    marker = "ALLOWED_AUTHOR_EMAILS="
    assert marker in source, "the hook no longer declares ALLOWED_AUTHOR_EMAILS"
    line = next(line for line in source.splitlines() if marker in line)
    value = line.split("=", 1)[1].strip().strip('"').strip("'")
    return value


@pytest.fixture
def repo(tmp_path: Path, owned_email_in_hook: str) -> Path:
    """A bare-minimum git repository that the hook can be pointed at.

    ``scripts/check.sh`` is a stub whose exit code the test controls, so the
    lint half never touches the real tree. The hook's allowlist is rewritten to
    name exactly one owner identity, which makes the foreign-identity case
    deterministic regardless of which allowlist the repo ships with.
    """
    work = tmp_path / "repo"
    work.mkdir()

    def git(args: list[str], env: dict[str, str] | None = None) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=work,
            env=env,
            capture_output=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr.decode()
        return proc.stdout.decode().strip()

    git(["init", "-q", "-b", "main"])
    git(["config", "user.email", OWN_EMAIL])
    git(["config", "user.name", "owner"])

    scripts = work / "scripts"
    scripts.mkdir()
    (scripts / "check.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    os.chmod(scripts / "check.sh", 0o755)
    (work / "README.md").write_text("repo\n", encoding="utf-8")
    git(["add", "scripts/check.sh", "README.md"])
    git(["commit", "-q", "-m", "initial"])

    # Point the hook's allowlist at a single known owner so the tests do not
    # depend on the identities the repository happens to ship with.
    install_hook(work, owner_email=OWN_EMAIL)
    return work


def install_hook(work: Path, owner_email: str) -> Path:
    """Copy the real hook into ``work/.git/hooks/pre-push`` with the given owner."""
    hooks = work / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    source = HOOK.read_text(encoding="utf-8")
    marker = "ALLOWED_AUTHOR_EMAILS="
    lines = source.splitlines()
    patched = []
    for line in lines:
        if marker in line:
            patched.append(f'{marker}"{owner_email}"')
        else:
            patched.append(line)
    hook = hooks / "pre-push"
    hook.write_text("\n".join(patched) + "\n", encoding="utf-8")
    os.chmod(hook, 0o755)
    return hook


def git(work: Path, args: list[str], **overrides: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "owner",
        "GIT_COMMITTER_NAME": "owner",
        **overrides,
    }
    proc = subprocess.run(
        ["git", *args], cwd=work, env=env, capture_output=True, check=False
    )
    assert proc.returncode == 0, proc.stderr.decode()
    return proc.stdout.decode().strip()


def commit_at(work: Path, message: str, author_email: str) -> str:
    """Add a file and commit it as ``author_email``; return the new sha."""
    path = work / f"change-{len(list(work.iterdir()))}.txt"
    path.write_text(message, encoding="utf-8")
    kwargs = {"GIT_AUTHOR_EMAIL": author_email, "GIT_COMMITTER_EMAIL": author_email}
    git(work, ["add", path.name], **kwargs)
    git(work, ["commit", "-q", "-m", message], **kwargs)
    return git(work, ["rev-parse", "HEAD"])


def head(work: Path) -> str:
    return git(work, ["rev-parse", "HEAD"])


def run_hook(
    work: Path,
    refs: str,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the installed hook with ``refs`` on stdin, as ``git push`` would."""
    hook = work / ".git" / "hooks" / "pre-push"
    return subprocess.run(
        ["bash", str(hook)],
        cwd=work,
        input=refs,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )


def main_ref(local_sha: str, remote_sha: str) -> str:
    return f"refs/heads/main {local_sha} refs/heads/main {remote_sha}\n"


class TestAuthorGate:
    def test_allowed_author_is_let_through(self, repo: Path) -> None:
        proc = run_hook(repo, main_ref(head(repo), NULL_SHA))
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_foreign_author_is_blocked(self, repo: Path) -> None:
        commit_at(repo, "foreign", FOREIGN_EMAIL)
        proc = run_hook(repo, main_ref(head(repo), NULL_SHA))
        assert proc.returncode != 0, "a foreign author must not reach main"
        combined = proc.stdout + proc.stderr
        assert FOREIGN_EMAIL in combined, "the offending identity must be shown"
        assert "pre-push" in combined

    def test_only_what_is_being_pushed_is_scanned(self, repo: Path) -> None:
        """A foreign commit that is NOT in the pushed range must not block.

        The gate scans ``remote_sha..local_sha``; a foreign commit already on
        the remote (or never in the range at all) is not part of this push and
        must not be re-litigated, or every incremental push would be refused for
        history the operator cannot change.
        """
        allowed = commit_at(repo, "allowed", OWN_EMAIL)
        # A foreign commit that stays OUTSIDE the pushed range: reset away, so
        # the range remote..local contains only the allowed commit.
        foreign = commit_at(repo, "foreign", FOREIGN_EMAIL)
        assert foreign != allowed
        git(repo, ["reset", "--hard", allowed])
        proc = run_hook(repo, main_ref(head(repo), allowed))
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_allowlist_is_read_from_the_hook(self, repo: Path) -> None:
        """The second, separately-owned identity the repo ships with also passes."""
        second = "41898282+github-actions[bot]@users.noreply.github.com"
        install_hook(repo, owner_email=f"{OWN_EMAIL},{second}")
        commit_at(repo, "bot", second)
        proc = run_hook(repo, main_ref(head(repo), NULL_SHA))
        assert proc.returncode == 0, proc.stdout + proc.stderr


class TestScopeAndEscapeHatches:
    def test_non_main_ref_is_not_gated(self, repo: Path) -> None:
        """The author and lint gates exist only for main; a feature branch
        push must not be blocked."""
        commit_at(repo, "foreign", FOREIGN_EMAIL)
        refs = f"refs/heads/topic {head(repo)} refs/heads/topic {NULL_SHA}\n"
        proc = run_hook(repo, refs)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_skip_env_bypasses_both_gates(self, repo: Path) -> None:
        proc = run_hook(repo, main_ref(head(repo), NULL_SHA), env={"SKIP_PREPUSH": "1"})
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_empty_ref_list_exits_cleanly(self, repo: Path) -> None:
        proc = run_hook(repo, "")
        assert proc.returncode == 0, proc.stdout + proc.stderr


class TestLintGate:
    def _stub_check(self, repo: Path, code: int) -> None:
        check = repo / "scripts" / "check.sh"
        check.write_text(f"#!/usr/bin/env bash\nexit {code}\n", encoding="utf-8")
        os.chmod(check, 0o755)

    def test_clean_lint_passes(self, repo: Path) -> None:
        self._stub_check(repo, 0)
        proc = run_hook(repo, main_ref(head(repo), NULL_SHA))
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_lint_failure_blocks(self, repo: Path) -> None:
        self._stub_check(repo, 1)
        proc = run_hook(repo, main_ref(head(repo), NULL_SHA))
        assert proc.returncode != 0, "a failing lint must block the push"
        combined = proc.stdout + proc.stderr
        assert "check.sh --lint-only" in combined or "ruff" in combined, (
            "the remedy must tell the operator how to fix the lint"
        )

    def test_lint_unverifiable_is_distinct_and_blocks(self, repo: Path) -> None:
        """Exit 3 means 'ruff is not installed here', which is NOT 'your code
        fails lint'. The message must say so, otherwise an operator whose local
        ruff is missing is told to fix code that is fine."""
        self._stub_check(repo, 3)
        proc = run_hook(repo, main_ref(head(repo), NULL_SHA))
        assert proc.returncode != 0, "an unverifiable lint must still block"
        combined = proc.stdout + proc.stderr
        assert "--no-verify" in combined, "the operator must be shown the escape hatch"
        assert "could not be verified" in combined

    def test_missing_check_script_is_not_a_failure(self, repo: Path) -> None:
        """A checkout that predates the gate has no ``scripts/check.sh``. It
        must be let through with a note — blocking it would strand an older
        clone with no way out."""
        os.remove(repo / "scripts" / "check.sh")
        proc = run_hook(repo, main_ref(head(repo), NULL_SHA))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "absent" in (proc.stdout + proc.stderr)
