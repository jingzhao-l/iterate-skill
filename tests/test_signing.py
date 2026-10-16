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

    def test_non_empty_value_enables(self, monkeypatch) -> None:
        monkeypatch.setenv(ALLOW_UNSIGNED_ENV, "1")
        assert allow_unsigned() is True

    def test_blank_value_is_not_an_opt_out(self, monkeypatch) -> None:
        monkeypatch.setenv(ALLOW_UNSIGNED_ENV, "   ")
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
