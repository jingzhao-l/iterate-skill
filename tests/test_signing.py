"""Tests for the MANDATORY release-signature policy (``iterate_cli.signing``).

Two layers:

* the pure policy (``enforce_signature_policy``) — every branch, including the
  ``ITERATE_ALLOW_UNSIGNED`` override and the rule that a BAD signature is never
  bypassed;
* a real ``gpg`` round-trip (skipped when gpg is absent) proving that
  verification actually accepts a good signature and rejects a tampered
  artifact/signature, rather than only exercising the policy plumbing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from iterate_cli import signing
from iterate_cli.signing import (
    ALLOW_UNSIGNED_ENV,
    ITERATE_SIGNING_PUBLIC_KEY,
    SIGNING_KEY_FINGERPRINT,
    allow_unsigned,
    enforce_signature_policy,
    verify_detached_signature,
)

GPG = shutil.which("gpg")


# ---------------------------------------------------------------------------
# allow_unsigned()
# ---------------------------------------------------------------------------


class TestAllowUnsignedEnv:
    def test_default_is_disabled(self, monkeypatch) -> None:
        monkeypatch.delenv(ALLOW_UNSIGNED_ENV, raising=False)
        assert allow_unsigned() is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " YES ", "True"])
    def test_explicit_truthy_value_enables(self, monkeypatch, value: str) -> None:
        monkeypatch.setenv(ALLOW_UNSIGNED_ENV, value)
        assert allow_unsigned() is True

    @pytest.mark.parametrize(
        "value",
        ["", "   ", "0", "false", "FALSE", "no", "off", "maybe", "yesplease"],
    )
    def test_non_truthy_value_does_not_enable(self, monkeypatch, value: str) -> None:
        """A bare truthiness test treated every non-empty value as an opt-out,
        so the intuitive ``ITERATE_ALLOW_UNSIGNED=0`` ("keep signatures
        mandatory") silently DISABLED signature enforcement — the exact opposite
        of the operator's intent, and a silent downgrade of the authenticity
        gate. Only explicit truthy values count."""
        monkeypatch.setenv(ALLOW_UNSIGNED_ENV, value)
        assert allow_unsigned() is False, f"{value!r} must not enable the override"

    def test_unset_variable_does_not_enable(self, monkeypatch) -> None:
        monkeypatch.delenv(ALLOW_UNSIGNED_ENV, raising=False)
        assert allow_unsigned() is False


# ---------------------------------------------------------------------------
# enforce_signature_policy()
# ---------------------------------------------------------------------------


class TestEnforceSignaturePolicy:
    def test_missing_signature_is_refused(self, tmp_path: Path) -> None:
        ok, detail = enforce_signature_policy(
            tmp_path / "a.tar.gz", None, allow_unsigned_override=False
        )
        assert ok is False
        assert "UNSIGNED" in detail

    def test_missing_signature_with_override_proceeds(self, tmp_path: Path) -> None:
        ok, detail = enforce_signature_policy(
            tmp_path / "a.tar.gz", None, allow_unsigned_override=True
        )
        assert ok is True
        assert ALLOW_UNSIGNED_ENV in detail

    def test_gpg_unavailable_is_refused_without_override(self, tmp_path: Path) -> None:
        artifact = tmp_path / "a.tar.gz"
        artifact.write_bytes(b"payload")
        sig = tmp_path / "a.tar.gz.asc"
        sig.write_text("-----BEGIN PGP SIGNATURE-----\n", encoding="utf-8")
        ok, detail = enforce_signature_policy(
            artifact,
            sig,
            allow_unsigned_override=False,
            gpg_bin="definitely-not-a-real-gpg-binary",
        )
        assert ok is False
        assert "cannot verify" in detail

    def test_gpg_unavailable_with_override_proceeds_with_warning_detail(
        self, tmp_path: Path
    ) -> None:
        artifact = tmp_path / "a.tar.gz"
        artifact.write_bytes(b"payload")
        sig = tmp_path / "a.tar.gz.asc"
        sig.write_text("-----BEGIN PGP SIGNATURE-----\n", encoding="utf-8")
        ok, detail = enforce_signature_policy(
            artifact,
            sig,
            allow_unsigned_override=True,
            gpg_bin="definitely-not-a-real-gpg-binary",
        )
        assert ok is True
        assert "NOT verified" in detail

    @pytest.mark.skipif(GPG is None, reason="gpg not installed")
    def test_bad_signature_is_refused_even_with_override(self, tmp_path: Path) -> None:
        """The override covers "cannot check", never "check failed"."""
        artifact = tmp_path / "a.tar.gz"
        artifact.write_bytes(b"payload")
        sig = tmp_path / "a.tar.gz.asc"
        sig.write_text(
            "-----BEGIN PGP SIGNATURE-----\n\nnot-a-signature\n"
            "-----END PGP SIGNATURE-----\n",
            encoding="utf-8",
        )
        ok, detail = enforce_signature_policy(
            artifact, sig, allow_unsigned_override=True
        )
        assert ok is False
        assert "FAILED" in detail or "failed" in detail
        assert ALLOW_UNSIGNED_ENV in detail  # tells the user it will not help here


# ---------------------------------------------------------------------------
# VALIDSIG fingerprint comparison + agent teardown (no real gpg required)
# ---------------------------------------------------------------------------

_FPR_A = "AAAABBBBCCCCDDDDEEEEFFFF0000111122223333"
_FPR_B = "BBBBCCCCDDDDEEEEFFFF00001111222233334444"


def _fake_gpg_run(verify_stdout: str, *, verify_rc: int = 0, fingerprints=(_FPR_A,)):
    """Fake ``subprocess.run`` dispatching import / list-keys / verify / gpgconf."""
    calls: list[list[str]] = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        if "--import" in argv:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if "--list-keys" in argv:
            body = "".join(f"fpr:::::::::{f}:\n" for f in fingerprints)
            return subprocess.CompletedProcess(argv, 0, body, "")
        if "--verify" in argv:
            return subprocess.CompletedProcess(argv, verify_rc, verify_stdout, "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    return run, calls


def _status_for(fingerprint: str) -> str:
    return (
        "[GNUPG:] NEWSIG\n"
        "[GNUPG:] GOODSIG DEADBEEF Someone <x@example.invalid>\n"
        f"[GNUPG:] VALIDSIG {fingerprint} 2026-01-01 1 0 4 0 1 8 00 {fingerprint}\n"
    )


class TestValidsigFingerprintEnforcement:
    def _paths(self, tmp_path: Path) -> tuple[Path, Path]:
        artifact = tmp_path / "a.bin"
        artifact.write_bytes(b"payload\n")
        signature = tmp_path / "a.bin.asc"
        signature.write_text("sig\n", encoding="utf-8")
        return artifact, signature

    def test_matching_fingerprint_verifies_and_disables_key_retrieval(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        artifact, signature = self._paths(tmp_path)
        run, calls = _fake_gpg_run(_status_for(_FPR_A), fingerprints=(_FPR_A,))
        monkeypatch.setattr(signing.subprocess, "run", run)

        status, detail = verify_detached_signature(
            artifact, signature, gpg_bin="/usr/bin/gpg"
        )
        assert status == "verified", detail
        verify_argv = next(a for a in calls if "--verify" in a)
        assert "--no-auto-key-retrieve" in verify_argv

    def test_valid_signature_from_another_key_is_rejected(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        """Exit 0 + GOODSIG is not enough: VALIDSIG must be the pinned key.

        A gpg that reports a GOOD signature under a NON-pinned fingerprint
        (e.g. an auto-retrieved or pre-seeded key) must be refused.
        """
        artifact, signature = self._paths(tmp_path)
        run, _calls = _fake_gpg_run(_status_for(_FPR_B), fingerprints=(_FPR_A,))
        monkeypatch.setattr(signing.subprocess, "run", run)

        status, _detail = verify_detached_signature(
            artifact, signature, gpg_bin="/usr/bin/gpg"
        )
        assert status == "invalid"

    def test_goodsig_without_validsig_is_rejected(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        artifact, signature = self._paths(tmp_path)
        run, _calls = _fake_gpg_run(
            "[GNUPG:] GOODSIG DEADBEEF X\n", fingerprints=(_FPR_A,)
        )
        monkeypatch.setattr(signing.subprocess, "run", run)

        status, _detail = verify_detached_signature(
            artifact, signature, gpg_bin="/usr/bin/gpg"
        )
        assert status == "invalid"


class TestGpgAgentTeardown:
    def _paths(self, tmp_path: Path) -> tuple[Path, Path]:
        artifact = tmp_path / "a.bin"
        artifact.write_bytes(b"payload\n")
        signature = tmp_path / "a.bin.asc"
        signature.write_text("sig\n", encoding="utf-8")
        return artifact, signature

    def test_verification_kills_the_throwaway_agent(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        artifact, signature = self._paths(tmp_path)
        run, calls = _fake_gpg_run(_status_for(_FPR_A), fingerprints=(_FPR_A,))
        monkeypatch.setattr(signing.subprocess, "run", run)
        monkeypatch.setattr(
            signing.shutil,
            "which",
            lambda name: "/usr/bin/gpgconf" if name == "gpgconf" else None,
        )

        verify_detached_signature(artifact, signature, gpg_bin="/usr/bin/gpg")
        assert any("--kill" in a and "gpg-agent" in a for a in calls), calls

    def test_kill_gpg_agent_never_raises(self, monkeypatch, tmp_path: Path) -> None:
        def boom(*args, **kwargs):
            raise OSError("gpgconf exploded")

        monkeypatch.setattr(signing.subprocess, "run", boom)
        monkeypatch.setattr(signing.shutil, "which", lambda name: "/usr/bin/gpgconf")
        signing._kill_gpg_agent("/usr/bin/gpg", tmp_path, 5)  # must not raise


# ---------------------------------------------------------------------------
# Real gpg round-trip
# ---------------------------------------------------------------------------


@pytest.fixture
def gnupg_home_factory():
    """Factory for throwaway GNUPGHOMEs under a SHORT path.

    gpg places its agent socket at ``<GNUPGHOME>/S.gpg-agent``; pytest's
    ``tmp_path`` is deep enough on macOS to exceed the ~104-char unix-socket
    limit, which makes gpg fail with "File name too long" before it can even
    generate a key. Every directory created here is removed at test teardown.
    """
    created: list[Path] = []

    def make() -> Path:
        home = Path(tempfile.mkdtemp(prefix="ig-"))
        os.chmod(home, 0o700)
        created.append(home)
        return home

    yield make
    for home in created:
        shutil.rmtree(home, ignore_errors=True)


def _generate_test_key(home: Path) -> str:
    """Create a throwaway key in ``home``; return the armored public key."""
    env = {**os.environ, "GNUPGHOME": str(home)}
    generated = subprocess.run(
        [
            "gpg", "--homedir", str(home), "--batch", "--pinentry-mode", "loopback",
            "--passphrase", "", "--quick-generate-key",
            "Iterate Test <test@example.invalid>", "rsa2048", "sign", "0",
        ],
        env=env, capture_output=True, text=True, timeout=120, check=False,
    )
    assert generated.returncode == 0, f"key generation failed: {generated.stderr}"
    exported = subprocess.run(
        ["gpg", "--homedir", str(home), "--armor", "--export", "test@example.invalid"],
        env=env, check=True, capture_output=True, timeout=60,
    ).stdout.decode("utf-8")
    return exported


def _sign(home: Path, artifact: Path, out: Path) -> None:
    env = {**os.environ, "GNUPGHOME": str(home)}
    signed = subprocess.run(
        [
            "gpg", "--homedir", str(home), "--batch", "--pinentry-mode", "loopback",
            "--passphrase", "", "--armor", "--detach-sign", "--output", str(out),
            str(artifact),
        ],
        env=env, capture_output=True, text=True, timeout=60, check=False,
    )
    assert signed.returncode == 0, f"signing failed: {signed.stderr}"


@pytest.mark.skipif(GPG is None, reason="gpg not installed")
class TestRealGpgRoundTrip:
    def test_good_signature_verifies(self, tmp_path: Path, gnupg_home_factory) -> None:
        home = gnupg_home_factory()
        public_key = _generate_test_key(home)
        artifact = tmp_path / "artifact.bin"
        artifact.write_bytes(b"hello iterate\n")
        signature = tmp_path / "artifact.bin.asc"
        _sign(home, artifact, signature)

        status, detail = verify_detached_signature(
            artifact, signature, public_key=public_key
        )
        assert status == "verified", detail

    def test_tampered_artifact_is_invalid(self, tmp_path: Path, gnupg_home_factory) -> None:
        home = gnupg_home_factory()
        public_key = _generate_test_key(home)
        artifact = tmp_path / "artifact.bin"
        artifact.write_bytes(b"hello iterate\n")
        signature = tmp_path / "artifact.bin.asc"
        _sign(home, artifact, signature)
        artifact.write_bytes(b"hello iterate TAMPERED\n")

        status, _detail = verify_detached_signature(
            artifact, signature, public_key=public_key
        )
        assert status == "invalid"

    def test_signature_from_another_key_is_invalid(self, tmp_path: Path, gnupg_home_factory) -> None:
        """A valid signature made by a DIFFERENT key must not pass: only the
        pinned key is imported, so gpg cannot even find the signer."""
        home_a = gnupg_home_factory()
        home_b = gnupg_home_factory()
        _generate_test_key(home_a)
        public_key_b = _generate_test_key(home_b)
        artifact = tmp_path / "artifact.bin"
        artifact.write_bytes(b"hello\n")
        signature = tmp_path / "artifact.bin.asc"
        _sign(home_a, artifact, signature)

        status, _detail = verify_detached_signature(
            artifact, signature, public_key=public_key_b
        )
        assert status == "invalid"

    def test_policy_accepts_a_verified_signature(self, tmp_path: Path, gnupg_home_factory) -> None:
        home = gnupg_home_factory()
        public_key = _generate_test_key(home)
        artifact = tmp_path / "artifact.bin"
        artifact.write_bytes(b"hello\n")
        signature = tmp_path / "artifact.bin.asc"
        _sign(home, artifact, signature)

        ok, detail = enforce_signature_policy(
            artifact,
            signature,
            allow_unsigned_override=False,
            gpg_bin=str(GPG),
        )
        # The shipped policy uses the PINNED key, so a throwaway key cannot
        # pass it — assert the refusal is the "invalid" one, not a plumbing
        # error, and that the real verifier accepted it with its own key.
        assert ok is False and "FAILED" in detail
        assert verify_detached_signature(
            artifact, signature, public_key=public_key
        )[0] == "verified"


# ---------------------------------------------------------------------------
# Pinned constants
# ---------------------------------------------------------------------------


class TestPinnedKey:
    def test_fingerprint_is_the_expected_release_signer(self) -> None:
        assert SIGNING_KEY_FINGERPRINT == "0929EA31DF4F7429F63FC53189D88B1D043A1298"

    def test_public_key_is_a_wellformed_armored_block(self) -> None:
        assert ITERATE_SIGNING_PUBLIC_KEY.startswith(
            "-----BEGIN PGP PUBLIC KEY BLOCK-----"
        )
        assert ITERATE_SIGNING_PUBLIC_KEY.rstrip().endswith(
            "-----END PGP PUBLIC KEY BLOCK-----"
        )

    @pytest.mark.skipif(GPG is None, reason="gpg not installed")
    def test_pinned_key_imports_and_has_the_expected_fingerprint(
        self, tmp_path: Path, gnupg_home_factory
    ) -> None:
        """Guards against a hand-edit that corrupts the embedded key."""
        home = gnupg_home_factory()
        key_path = tmp_path / "pub.asc"
        key_path.write_text(ITERATE_SIGNING_PUBLIC_KEY, encoding="utf-8")
        env = {**os.environ, "GNUPGHOME": str(home)}
        subprocess.run(
            ["gpg", "--batch", "--quiet", "--import", str(key_path)],
            env=env, check=True, capture_output=True, timeout=60,
        )
        listing = subprocess.run(
            ["gpg", "--list-keys", "--with-colons"],
            env=env, check=True, capture_output=True, timeout=60,
        ).stdout.decode("utf-8")
        fingerprints = [
            line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:")
        ]
        assert SIGNING_KEY_FINGERPRINT in fingerprints
