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
if [ "$repo" = "glasspane-harness" ] && [ "$wf" = "release.yml" ]; then
  printf '        if: ${{ secrets.GPG_PRIVATE_KEY != %s }}\\n' "''" | base64
else
  printf 'name: noop\\n' | base64
fi
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
