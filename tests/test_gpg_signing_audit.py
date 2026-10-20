"""Regression tests for ``tools/gpg-signing.sh audit`` target filtering.

``cmd_audit`` validates its target arguments via ``require_known_targets "$@"``
but used to consume every target row anyway (``targets_filtered`` with no
arguments), so ``gpg-signing.sh audit GlassPane`` silently audited all five
repos — the arguments were validated then discarded. These tests drive the
real script with a fake ``gh`` on ``PATH`` that records which workflow URLs
were requested, and assert only the requested repo is queried.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "gpg-signing.sh"

#: Body containing the silent-skip expression the audit exists to catch.
#: ``GH_SIGNING_FAIL_REPO`` makes one repo's reads fail with a non-404 error and
#: ``GH_SIGNING_ALL_404`` makes every read report the file as absent.
_FAKE_GH = """#!/usr/bin/env bash
# Record every invocation so the test can assert which repos were queried.
printf '%s\\n' "$*" >> "$GH_SIGNING_LOG"
url="$2"
repo=""
wf=""
case "$url" in
  repos/jingzhao-l/*/contents/.github/workflows/*)
    rest="${url#repos/jingzhao-l/}"
    repo="${rest%%/contents/*}"
    wf="${rest##*/}"
    ;;
esac
if [ -n "${GH_SIGNING_ALL_404:-}" ]; then
  printf 'gh: Not Found (HTTP 404)\\n' >&2
  exit 1
fi
if [ -n "${GH_SIGNING_FAIL_REPO:-}" ] && [ "$repo" = "$GH_SIGNING_FAIL_REPO" ]; then
  printf 'gh: Server Error (HTTP 502)\\n' >&2
  exit 1
fi
if [ "$repo" = "glasspane-harness" ] && [ "$wf" = "release.yml" ]; then
  printf '        if: ${{ secrets.GPG_PRIVATE_KEY != %s }}\\n' "''" | base64
else
  printf 'name: noop\\n' | base64
fi
"""

#: ``seed`` must hand the passphrase to gpg on stdin, never in argv.
_FAKE_GPG = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$GPG_SIGNING_ARGV_LOG"
cat >/dev/null
printf -- '-----BEGIN PGP PRIVATE KEY BLOCK-----\\nfake\\n-----END PGP PRIVATE KEY BLOCK-----\\n'
"""

_FAKE_SECURITY = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$SECURITY_ARGV_LOG"
"""


@pytest.fixture()
def audit_env(tmp_path: Path) -> dict[str, str]:
    """Return an environment with a fake ``gh`` that logs requested repos."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(_FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["GH_SIGNING_LOG"] = str(log)
    return env


def _run_audit(env: dict[str, str], *targets: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "audit", *targets],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _logged_invocations(env: dict[str, str]) -> list[str]:
    log = Path(env["GH_SIGNING_LOG"])
    if not log.exists():
        return []
    return [line for line in log.read_text(encoding="utf-8").splitlines() if line]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
class TestAuditTargetFiltering:
    def test_single_target_audits_only_that_repo(self, audit_env: dict[str, str]) -> None:
        # Pre-fix, ``audit GlassPane`` queried every target, hit the
        # glasspane-harness silent-skip, and exited 1. Asserting exit 0 and a
        # GlassPane-only invocation log pins the fix in both directions.
        result = _run_audit(audit_env, "GlassPane")
        assert result.returncode == 0, result.stdout + result.stderr
        invocations = _logged_invocations(audit_env)
        assert invocations, "fake gh was never called"
        assert all("jingzhao-l/GlassPane/" in line for line in invocations), invocations
        assert not any("glasspane-harness" in line for line in invocations)

    def test_single_target_still_finds_its_own_violation(
        self, audit_env: dict[str, str]
    ) -> None:
        result = _run_audit(audit_env, "glasspane-harness")
        assert result.returncode == 1, result.stdout + result.stderr
        invocations = _logged_invocations(audit_env)
        assert invocations
        assert all("glasspane-harness" in line for line in invocations), invocations

    def test_multiple_targets_are_honoured(
        self, audit_env: dict[str, str]
    ) -> None:
        result = _run_audit(audit_env, "GlassPane", "glasspane-harness")
        assert result.returncode == 1, result.stdout + result.stderr
        invocations = _logged_invocations(audit_env)
        joined = "\n".join(invocations)
        assert "jingzhao-l/GlassPane/" in joined
        assert "glasspane-harness" in joined
        # The other three targets must not have been swept in.
        assert "iterate-skill" not in joined
        assert "iterate-harness" not in joined
        assert "iterate-plugin" not in joined

    def test_no_targets_defaults_to_all(self, audit_env: dict[str, str]) -> None:
        result = _run_audit(audit_env)
        # glasspane-harness carries the violation, so the full sweep exits 1.
        assert result.returncode == 1, result.stdout + result.stderr
        joined = "\n".join(_logged_invocations(audit_env))
        for repo in ("GlassPane", "iterate-skill", "iterate-harness", "iterate-plugin"):
            assert f"jingzhao-l/{repo}/" in joined


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
class TestAuditFailsClosed:
    """An audit that cannot read a workflow must not report success."""

    def test_non_404_read_error_fails_the_audit(self, audit_env: dict[str, str]) -> None:
        audit_env["GH_SIGNING_FAIL_REPO"] = "GlassPane"
        result = _run_audit(audit_env, "GlassPane")
        assert result.returncode == 1, result.stdout + result.stderr
        assert "could not read workflow" in result.stdout
        assert "audit: passed" not in result.stdout

    def test_only_404_is_treated_as_an_absent_workflow(
        self, audit_env: dict[str, str]
    ) -> None:
        # Every read 404s. That is a legitimate skip per file, but zero
        # inspected workflows means the target list is wrong or the repo moved —
        # reporting a pass there is exactly the fail-open bug this pins.
        audit_env["GH_SIGNING_ALL_404"] = "1"
        result = _run_audit(audit_env, "GlassPane")
        assert result.returncode == 1, result.stdout + result.stderr
        assert "no release workflows were inspected" in result.stdout
        assert "audit: passed" not in result.stdout

    def test_a_clean_read_still_passes_and_reports_coverage(
        self, audit_env: dict[str, str]
    ) -> None:
        result = _run_audit(audit_env, "GlassPane")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "audit: passed (2 workflow(s) inspected)" in result.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
class TestInstallValidatesTargets:
    def test_unknown_target_exits_before_touching_the_keychain(
        self, audit_env: dict[str, str]
    ) -> None:
        result = subprocess.run(
            ["bash", str(SCRIPT), "install", "definitely-not-a-repo"],
            capture_output=True,
            text=True,
            env=audit_env,
            check=False,
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "unknown target" in result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
class TestSeedKeepsThePassphraseOffArgv:
    def test_passphrase_is_piped_to_gpg_on_stdin(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for name, body in (("gpg", _FAKE_GPG), ("security", _FAKE_SECURITY)):
            path = bin_dir / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        gpg_log = tmp_path / "gpg.argv"
        security_log = tmp_path / "security.argv"
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        env["GPG_SIGNING_ARGV_LOG"] = str(gpg_log)
        env["SECURITY_ARGV_LOG"] = str(security_log)

        result = subprocess.run(
            ["bash", str(SCRIPT), "seed"],
            input="correct horse battery staple\n",
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        gpg_argv = gpg_log.read_text(encoding="utf-8")
        assert "--passphrase-fd 0" in gpg_argv
        assert "--passphrase " not in gpg_argv
        assert "correct horse battery staple" not in gpg_argv
        # `security` has no stdin form for -w; that exposure is documented in
        # the script, and pinning it here catches an accidental second leak.
        security_argv = security_log.read_text(encoding="utf-8")
        assert "correct horse battery staple" in security_argv
