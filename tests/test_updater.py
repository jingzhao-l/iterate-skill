"""Unit tests for ``iterate_cli/updater`` (``iterate update``).

Everything network/subprocess/filedescriptor-touching is injected, so the
suite runs offline and hermetic (tmp_path only, no real downloads, no real
git/pip calls).
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from iterate_cli import __version__, updater
from iterate_cli.updater import (
    CHECKSUMS_ASSET_NAME,
    INSTALL_METHOD_PIP,
    INSTALL_METHOD_SOURCE,
    OPTIONAL_RELEASE_PATHS,
    RELEASE_API_URL,
    REQUIRED_RELEASE_PATHS,
    TARBALL_ASSET_NAME,
    UpdateOutcome,
    UpdateResult,
    compare_versions,
    detect_assistant_dirs,
    detect_install_method,
    download_verified_release,
    fetch_latest_release,
    normalize_version,
    parse_checksums,
    run_update,
    source_checkout_root,
    update_assistant_dir,
    update_cli_package,
)

# ---------------------------------------------------------------------------
# Fixtures / builders (offline release simulation)
# ---------------------------------------------------------------------------


def _release_payload(tag: str = "v9.9.9") -> bytes:
    payload = {
        "tag_name": tag,
        "name": f"iterate-skill {tag}",
        "assets": [
            {
                "name": TARBALL_ASSET_NAME,
                "browser_download_url": "https://example.invalid/iterate-skill.tar.gz",
            },
            {
                "name": CHECKSUMS_ASSET_NAME,
                "browser_download_url": "https://example.invalid/SHA256SUMS.txt",
            },
        ],
    }
    return json.dumps(payload).encode("utf-8")


def build_release_tree(root: Path, *, include_optional: bool = True) -> Path:
    """Materialize a minimal release source tree with all REQUIRED paths."""
    source = root / "iterate-skill"
    for relative in REQUIRED_RELEASE_PATHS + (OPTIONAL_RELEASE_PATHS if include_optional else []):
        entry = source / relative
        if relative in {"iterate_cli", "config/dimensions"}:
            entry.mkdir(parents=True, exist_ok=True)
            (entry / "placeholder.txt").write_text("x\n", encoding="utf-8")
        else:
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.write_text(f"content of {relative}\n", encoding="utf-8")

    # Iterate_cli must be importable-looking for the copy to survive; also add
    # a harness/ dir only in the source? No — the release never ships harness.
    (source / "iterate_cli" / "__init__.py").write_text("# test\n", encoding="utf-8")
    return source


def tar_wrap(source: Path, top_name: str = "iterate-skill") -> bytes:
    """``git archive --prefix=<top>/``-style tarball of ``source``."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(source, arcname=top_name)
    return buf.getvalue()


def make_fetch(
    tarball: bytes | None = None,
    checksums: bytes | None = None,
    tag: str = "v9.9.9",
) -> tuple[updater._Fetched, dict[str, bytes]]:
    """Return ``(fetcher, url->body map)`` simulating the GitHub API + assets."""
    urls: dict[str, bytes] = {RELEASE_API_URL: _release_payload(tag)}
    tarball_url = "https://example.invalid/iterate-skill.tar.gz"
    checksum_url = "https://example.invalid/SHA256SUMS.txt"
    if tarball is not None:
        urls[tarball_url] = tarball
    if checksums is not None:
        urls[checksum_url] = checksums

    def fetch(url: str, *, timeout: float, headers: dict[str, str]) -> updater._Fetched:
        if url not in urls:
            return updater._Fetched(status=404, body=b"not found")
        return updater._Fetched(status=200, body=urls[url])

    return fetch, urls


def make_ok_fetch(root: Path) -> updater._Fetched:
    """Build a fully self-consistent offline release (tar + checksums)."""
    source = build_release_tree(root)
    tarball = tar_wrap(source)
    checksums = hashlib.sha256(tarball).hexdigest()
    checksums_body = f"{checksums}  {TARBALL_ASSET_NAME}\n".encode()
    fetch, _ = make_fetch(tarball=tarball, checksums=checksums_body)
    return fetch


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("v3.3.1", "3.3.1"),
        ("3.3.1", "3.3.1"),
        ("release/2.0.0-rc1", "2.0.0"),
        ("v3.3", None),
        ("", None),
        (None, None),
        (12345, None),
        ("build abc 1.2.3xyz", "1.2.3"),
    ],
)
def test_normalize_version(raw, expected) -> None:
    assert normalize_version(raw) == expected


def test_compare_versions() -> None:
    assert compare_versions("3.3.1", "3.3.1") == 0
    assert compare_versions("3.3.1", "3.4.0") == 1
    assert compare_versions("3.4.0", "3.3.1") == -1
    assert compare_versions("3.10.0", "3.9.9") == -1  # 3.9.9 < 3.10.0
    assert compare_versions("3.9.9", "3.10.0") == 1
    assert compare_versions("3.3.1", "3.4") == 1  # 3.4 == 3.4.0 > 3.3.1
    assert compare_versions("3.3.1", "3.3.1.1") == 0  # trailing extra segment ignored


# ---------------------------------------------------------------------------
# Release discovery (fetch_latest_release)
# ---------------------------------------------------------------------------


def test_fetch_latest_release_ok() -> None:
    fetch, _ = make_fetch()
    release, error = fetch_latest_release(fetch=fetch)
    assert error is None
    assert release is not None
    assert release.tag == "9.9.9"
    assert release.tarball_url.endswith(TARBALL_ASSET_NAME)
    assert release.checksum_url.endswith(CHECKSUMS_ASSET_NAME)


def test_fetch_latest_release_missing_version() -> None:
    def fetch(url: str, *, timeout: float, headers: dict[str, str]):
        return updater._Fetched(status=200, body=b'{"assets": []}')

    release, error = fetch_latest_release(fetch=fetch)
    assert release is None
    assert "missing" in (error or "").lower()


def test_fetch_latest_release_missing_tarball_asset() -> None:
    payload = json.dumps({"tag_name": "v9.9.9", "assets": []}).encode()

    def fetch(url: str, *, timeout: float, headers: dict[str, str]):
        return updater._Fetched(status=200, body=payload)

    release, error = fetch_latest_release(fetch=fetch)
    assert release is None
    assert "no iterate-skill.tar.gz asset" in (error or "")


def test_fetch_latest_release_invalid_json() -> None:
    def fetch(url: str, *, timeout: float, headers: dict[str, str]):
        return updater._Fetched(status=200, body=b"<html>not json</html>")

    release, error = fetch_latest_release(fetch=fetch)
    assert release is None
    assert "invalid JSON" in (error or "")


def test_fetch_latest_release_http_error_403() -> None:
    def fetch(url: str, *, timeout: float, headers: dict[str, str]):
        raise updater.urllib.error.HTTPError(
            url, 403, "Forbidden", None, None
        )

    release, error = fetch_latest_release(fetch=fetch)
    assert release is None
    assert "rate limit" in (error or "").lower()


def test_fetch_latest_release_network_error() -> None:
    def fetch(url: str, *, timeout: float, headers: dict[str, str]):
        raise updater.urllib.error.URLError("connection refused")

    release, error = fetch_latest_release(fetch=fetch)
    assert release is None
    assert "network error" in (error or "")


# ---------------------------------------------------------------------------
# Checksum parsing + verified download
# ---------------------------------------------------------------------------


def test_parse_checksums_coreutils_and_shasum_formats() -> None:
    digest = "a" * 64
    text = (
        f"{digest}  {TARBALL_ASSET_NAME}\n"
        f"{'b' * 64} *SHA256SUMS.txt\n"
        f"not a checksum line\n"
        f"{'c' * 64}\tREADME.md\n"
    ).encode()
    parsed = parse_checksums(text)
    assert parsed[TARBALL_ASSET_NAME] == digest
    assert parsed["SHA256SUMS.txt"] == "b" * 64
    assert parsed["README.md"] == "c" * 64
    assert "not a checksum line" not in parsed


def test_parse_checksums_lowercases_digest() -> None:
    parsed = parse_checksums(f"{'A' * 64}  {TARBALL_ASSET_NAME}\n".encode())
    assert parsed[TARBALL_ASSET_NAME] == "a" * 64


def test_download_verified_release_success(tmp_path) -> None:
    fetch = make_ok_fetch(tmp_path)
    release, _ = fetch_latest_release(fetch=fetch)
    assert release is not None
    source, error = download_verified_release(release, fetch=fetch)
    assert error is None
    assert source is not None
    assert source.name == "iterate-skill"
    assert (source / "SKILL.md").is_file()
    assert not (source / "harness").exists()
    cleanup = source.parent.parent
    assert cleanup.is_dir()
    import shutil

    shutil.rmtree(cleanup, ignore_errors=True)


def test_download_verified_release_missing_checksum_asset() -> None:
    payload = {
        "tag_name": "v9.9.9",
        "assets": [
            {
                "name": TARBALL_ASSET_NAME,
                "browser_download_url": "https://example.invalid/tarball",
            }
        ],
    }

    def fetch(url: str, *, timeout: float, headers: dict[str, str]):
        return updater._Fetched(status=200, body=json.dumps(payload).encode())

    release, _ = fetch_latest_release(fetch=fetch)
    assert release is not None
    source, error = download_verified_release(release, fetch=fetch)
    assert source is None
    assert "no SHA256SUMS.txt asset" in (error or "")


def test_download_verified_release_rejects_mismatched_checksum(tmp_path) -> None:
    source_tree = build_release_tree(tmp_path)
    tarball = tar_wrap(source_tree)
    wrong_body = f"{'f' * 64}  {TARBALL_ASSET_NAME}\n".encode()
    fetch, _ = make_fetch(tarball=tarball, checksums=wrong_body)
    release, _ = fetch_latest_release(fetch=fetch)
    assert release is not None
    source, error = download_verified_release(release, fetch=fetch)
    assert source is None
    assert "SHA-256 mismatch" in (error or "")


def test_download_verified_release_rejects_missing_tarball_entry(tmp_path) -> None:
    source_tree = build_release_tree(tmp_path)
    tarball = tar_wrap(source_tree)
    # Correct digest but under a different filename => no entry for our asset.
    checksums_body = f"{hashlib.sha256(tarball).hexdigest()}  other.bin\n".encode()
    fetch, _ = make_fetch(tarball=tarball, checksums=checksums_body)
    release, _ = fetch_latest_release(fetch=fetch)
    assert release is not None
    source, error = download_verified_release(release, fetch=fetch)
    assert source is None
    assert "no iterate-skill.tar.gz entry" in (error or "")


def test_download_verified_release_rejects_wrong_top_level_layout(tmp_path) -> None:
    # Two top-level dirs instead of the expected single repo dir.
    root = tmp_path / "w1"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir()
    tarball = tar_wrap(root, top_name=".")
    checksums_body = f"{hashlib.sha256(tarball).hexdigest()}  {TARBALL_ASSET_NAME}\n".encode()
    fetch, _ = make_fetch(tarball=tarball, checksums=checksums_body)
    release, _ = fetch_latest_release(fetch=fetch)
    assert release is not None
    source, error = download_verified_release(release, fetch=fetch)
    assert source is None
    assert "top-level layout" in (error or "")


# ---------------------------------------------------------------------------
# Install method detection
# ---------------------------------------------------------------------------


def test_source_checkout_root_repo(tmp_path, monkeypatch) -> None:
    package = tmp_path / "repo" / "iterate_cli"
    package.mkdir(parents=True)
    (tmp_path / "repo" / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "repo" / ".git").mkdir()
    monkeypatch.setattr(updater, "__file__", str(package / "__init__.py"))
    assert source_checkout_root() == (tmp_path / "repo").resolve()
    assert detect_install_method() == INSTALL_METHOD_SOURCE


def test_source_checkout_root_pip_install(tmp_path, monkeypatch) -> None:
    package = tmp_path / "venv" / "lib" / "site-packages" / "iterate_cli"
    package.mkdir(parents=True)
    # No pyproject/.git near the package, like a regular wheel install.
    monkeypatch.setattr(updater, "__file__", str(package / "__init__.py"))
    assert source_checkout_root() is None
    assert detect_install_method() == INSTALL_METHOD_PIP


# ---------------------------------------------------------------------------
# Assistant dir detection
# ---------------------------------------------------------------------------


def test_detect_assistant_dirs_home_wins_dedup(tmp_path) -> None:
    home = tmp_path / "home"
    proj = tmp_path / "project"
    home_dir = home / ".claude" / "skills" / "iterate"
    proj_dir = proj / ".cursor" / "skills" / "iterate"
    home_dir.mkdir(parents=True)
    proj_dir.mkdir(parents=True)
    (home_dir / "SKILL.md").write_text("# iterate\n", encoding="utf-8")
    (proj_dir / "SKILL.md").write_text("# iterate\n", encoding="utf-8")

    found = detect_assistant_dirs(proj, home)
    names = [name for name, _ in found]
    assert "claude" in names
    assert "cursor" in names
    # claude-code shares the .claude dir -> reported once via claude.
    assert "claude-code" not in names


def test_detect_assistant_dirs_ignores_non_install(tmp_path) -> None:
    home = tmp_path / "home"
    proj = tmp_path / "project"
    # Placeholder dir without SKILL.md is not an install.
    (proj / ".cursor" / "skills" / "iterate").mkdir(parents=True)
    assert detect_assistant_dirs(proj, home) == []


# ---------------------------------------------------------------------------
# update_assistant_dir
# ---------------------------------------------------------------------------


def _minimal_source(root: Path) -> Path:
    return build_release_tree(root)


def test_update_assistant_dir_copies_required_and_optional(tmp_path) -> None:
    source = _minimal_source(tmp_path / "src-tree")
    destination = tmp_path / "skills" / "iterate"
    update_assistant_dir(source, destination)

    for relative in REQUIRED_RELEASE_PATHS + OPTIONAL_RELEASE_PATHS:
        assert (destination / relative).exists(), f"missing {relative}"


def test_update_assistant_dir_replaces_stale_and_removes_harness(tmp_path) -> None:
    source = _minimal_source(tmp_path / "src-tree")
    destination = tmp_path / "skills" / "iterate"
    sleep_dst = destination / "README.md"
    sleep_dst.parent.mkdir(parents=True, exist_ok=True)
    sleep_dst.write_text("stale README\n", encoding="utf-8")
    stale_dir = destination / "templates" / "iterate-decisions.template.md"
    stale_dir.mkdir(parents=True)  # stale dir where a file is required
    harness_dir = destination / "harness"
    harness_dir.mkdir(parents=True)
    (harness_dir / "README.md").write_text("should be removed\n", encoding="utf-8")

    update_assistant_dir(source, destination)

    assert sleep_dst.read_text(encoding="utf-8").startswith("content of README.md")
    assert (destination / "templates" / "iterate-decisions.template.md").is_file()
    assert not harness_dir.exists()


def test_update_assistant_dir_required_missing_raises(tmp_path) -> None:
    source = _minimal_source(tmp_path / "src-tree")
    # Break the required set: remove SKILL.md from the release source.
    (source / "SKILL.md").unlink()
    destination = tmp_path / "skills" / "iterate"
    with pytest.raises(FileNotFoundError):
        update_assistant_dir(source, destination)


def test_update_assistant_dir_rejects_symlink_ancestor(tmp_path) -> None:
    source = _minimal_source(tmp_path / "src-tree")
    destination = tmp_path / "skills" / "iterate"
    destination.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (destination / "config").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlinked"):
        update_assistant_dir(source, destination)


# ---------------------------------------------------------------------------
# update_cli_package
# ---------------------------------------------------------------------------


def _ok_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")


def _fail_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        argv, returncode=1, stdout="boom", stderr="failure detail"
    )


def test_update_cli_package_pip_success(tmp_path, monkeypatch) -> None:
    source = tmp_path / "release-src"
    source.mkdir()
    recorded: dict[str, list[str]] = {}

    def runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        recorded["argv"] = argv
        return _ok_runner(argv)

    result = update_cli_package(
        method=INSTALL_METHOD_PIP, source_dir=source, runner=runner
    )
    assert result.success
    argv = recorded["argv"]
    assert "--force-reinstall" in argv
    assert "--no-deps" in argv
    assert str(source) in argv


def test_update_cli_package_pip_without_source() -> None:
    result = update_cli_package(method=INSTALL_METHOD_PIP, source_dir=None, runner=_ok_runner)
    assert not result.success
    assert "no verified release source" in result.message.lower()


def test_update_cli_package_pip_failure() -> None:
    result = update_cli_package(
        method=INSTALL_METHOD_PIP, source_dir=Path("/tmp/not-used"), runner=_fail_runner
    )
    assert not result.success
    assert "failed" in result.message.lower()
    assert "failure detail" in result.message


def test_update_cli_package_source(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    monkeypatch.setattr(updater, "source_checkout_root", lambda: repo_root)
    recorded: list[list[str]] = []

    def runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        recorded.append(argv)
        return _ok_runner(argv)

    result = update_cli_package(method=INSTALL_METHOD_SOURCE, runner=runner)
    assert result.success
    assert any("git" in argv and "pull" in argv for argv in recorded)
    assert any("pip" in argv and "install" in argv and "-e" in argv for argv in recorded)


def test_update_cli_package_source_git_pull_fails(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / ".git").mkdir(parents=True)
    monkeypatch.setattr(updater, "source_checkout_root", lambda: repo_root)

    result = update_cli_package(method=INSTALL_METHOD_SOURCE, runner=_fail_runner)
    assert not result.success
    assert "git pull failed" in result.message


# ---------------------------------------------------------------------------
# run_update orchestration
# ---------------------------------------------------------------------------


def _fake_home(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    proj = tmp_path / "project"
    skill = home / ".claude" / "skills" / "iterate"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("stale\n", encoding="utf-8")
    return home, proj


def test_run_update_unreachable(tmp_path) -> None:
    def fetch(url: str, **kw):
        raise updater.urllib.error.URLError("offline")

    home, proj = _fake_home(tmp_path)
    outcome = run_update(
        project_root=proj, home=home, confirmed=True, fetch=fetch
    )
    assert outcome.unreachable
    assert outcome.download_error is not None
    assert outcome.assistants_updated == []


def test_run_update_check_only_never_downloads(tmp_path) -> None:
    fetch = make_ok_fetch(tmp_path)
    home, proj = _fake_home(tmp_path)
    outcome = run_update(project_root=proj, home=home, check_only=True, fetch=fetch)
    assert outcome.check_only
    assert outcome.up_to_date is False  # 9.9.9 > 3.3.1
    assert outcome.assistants_updated == []


def test_run_update_up_to_date(tmp_path) -> None:
    fetch, _ = make_fetch(tag=f"v{__version__}")
    home, proj = _fake_home(tmp_path)
    outcome = run_update(project_root=proj, home=home, confirmed=True, fetch=fetch)
    assert outcome.up_to_date
    assert outcome.assistants_updated == []


def test_run_update_requires_confirmation(tmp_path) -> None:
    fetch = make_ok_fetch(tmp_path)
    home, proj = _fake_home(tmp_path)
    outcome = run_update(project_root=proj, home=home, confirmed=False, fetch=fetch)
    assert outcome.cancelled
    assert not outcome.up_to_date
    assert outcome.assistants_updated == []
    # Nothing was downloaded/applied.
    assert (home / ".claude" / "skills" / "iterate" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "stale\n"


def test_run_update_full_flow_pip(tmp_path, monkeypatch) -> None:
    fetch = make_ok_fetch(tmp_path)
    home, proj = _fake_home(tmp_path)
    monkeypatch.setattr(updater, "detect_install_method", lambda: INSTALL_METHOD_PIP)
    recorded: list[list[str]] = []

    def runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        recorded.append(argv)
        return _ok_runner(argv)

    outcome = run_update(
        project_root=proj, home=home, confirmed=True, fetch=fetch, runner=runner
    )
    assert not outcome.unreachable
    assert outcome.latest == "9.9.9"
    assert outcome.cli_result is not None and outcome.cli_result.success
    assert "claude" in outcome.assistants_updated
    assert outcome.assistants_failed == []
    # The assistant dir was refreshed from the release, not the stale copy.
    skill_md = home / ".claude" / "skills" / "iterate" / "SKILL.md"
    assert skill_md.read_text(encoding="utf-8").startswith("content of SKILL.md")


def test_run_update_skip_all_assistants(tmp_path, monkeypatch) -> None:
    fetch = make_ok_fetch(tmp_path)
    home, proj = _fake_home(tmp_path)
    monkeypatch.setattr(updater, "detect_install_method", lambda: INSTALL_METHOD_PIP)

    outcome = run_update(
        project_root=proj,
        home=home,
        confirmed=True,
        assistants=[],
        fetch=fetch,
        runner=_ok_runner,
    )
    assert outcome.assistants_updated == []
    assert outcome.cli_result is not None and outcome.cli_result.success
    # Stale copy untouched.
    assert (home / ".claude" / "skills" / "iterate" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "stale\n"


def test_run_update_rejects_bad_checksum(tmp_path) -> None:
    source_tree = build_release_tree(tmp_path)
    tarball = tar_wrap(source_tree)
    wrong = f"{'f' * 64}  {TARBALL_ASSET_NAME}\n".encode()
    fetch, _ = make_fetch(tarball=tarball, checksums=wrong)
    home, proj = _fake_home(tmp_path)

    outcome = run_update(
        project_root=proj,
        home=home,
        confirmed=True,
        fetch=fetch,
        runner=_ok_runner,
    )
    assert outcome.download_error is not None
    assert "SHA-256 mismatch" in (outcome.download_error or "")
    assert outcome.assistants_updated == []
    assert (home / ".claude" / "skills" / "iterate" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "stale\n"


def test_run_update_tracks_failed_assistant(tmp_path, monkeypatch) -> None:
    fetch = make_ok_fetch(tmp_path)
    home, proj = _fake_home(tmp_path)
    monkeypatch.setattr(updater, "detect_install_method", lambda: INSTALL_METHOD_PIP)

    def boom(source, destination):
        raise PermissionError("simulated copy failure")

    monkeypatch.setattr(updater, "update_assistant_dir", boom)

    outcome = run_update(
        project_root=proj, home=home, confirmed=True, fetch=fetch, runner=_ok_runner
    )
    assert any(name == "claude" for name, _ in outcome.assistants_failed)
    # CLI reinstall still attempted and OK.
    assert outcome.cli_result is not None and outcome.cli_result.success


def test_update_outcome_to_dict_shape() -> None:
    outcome = UpdateOutcome(
        current="3.3.1",
        latest="9.9.9",
        check_only=True,
        cli_result=UpdateResult(True, "ok"),
        assistants_failed=[("cursor", "boom")],
    )
    d = outcome.to_dict()
    assert d["current_version"] == "3.3.1"
    assert d["latest_version"] == "9.9.9"
    assert d["check_only"] is True
    assert d["cli_update"]["success"] is True
    assert d["assistants_failed"] == [{"assistant": "cursor", "error": "boom"}]
    assert d["cancelled"] is False
    assert d["up_to_date"] is False


# ---------------------------------------------------------------------------
# _run_command timeout enforcement
# ---------------------------------------------------------------------------


def test_run_command_production_runner_applies_timeout(monkeypatch) -> None:
    """The production default runner must bound git/pip work by the timeout."""
    captured: dict[str, object] = {}

    class FakeProcess:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            # The whole child tree must be isolated so a timeout can killpg it.
            if "start_new_session" not in kwargs or not kwargs["start_new_session"]:
                raise AssertionError("subprocess must be started in a new session")
            self.returncode = 0

        def communicate(self, timeout=None):
            captured["timeout"] = timeout
            return "", ""

    monkeypatch.setattr(updater.subprocess, "Popen", FakeProcess)
    updater._run_command(["git", "pull"], updater._default_runner, 120, "git pull")
    assert captured["argv"] == ["git", "pull"]
    assert captured["timeout"] == 120


def test_run_command_injected_runner_keeps_contract() -> None:
    """Injected test runners keep the original (argv) signature."""

    def runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

    # Must not raise; the injected runner receives no timeout kwarg.
    updater._run_command(["echo", "hi"], runner, 60, "test cmd")


def test_run_command_timeout_expired_reports_runtime_error(monkeypatch) -> None:
    """A subprocess.TimeoutExpired becomes a readable RuntimeError, not a crash."""

    class HangingProcess:
        def __init__(self, argv, **kwargs):
            self.returncode = None
            self.pid = 4242
            self._argv = argv

        def communicate(self, timeout=None):
            raise subprocess.TimeoutExpired(
                cmd=self._argv, timeout=timeout, output=b"", stderr=b""
            )

    monkeypatch.setattr(updater.subprocess, "Popen", HangingProcess)
    with pytest.raises(RuntimeError, match="timed out after 600s"):
        updater._run_command(
            ["pip", "install"], updater._default_runner, 600, "pip install"
        )


# ---------------------------------------------------------------------------
# _safe_extractall: traversal / symlink / bomb members
# ---------------------------------------------------------------------------


def _tarball_with_members(file_names: list[str]) -> bytes:
    """Build a gzip tarball containing one empty member with each given name."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in file_names:
            if name.endswith("/"):
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            else:
                data = b"content"
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_safe_extractall_rejects_dir_traversal_member(tmp_path) -> None:
    """A ``../escape/`` directory member must be refused, not just files."""
    blob = _tarball_with_members(["../escape/"])
    with (
        tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar,
        pytest.raises(tarfile.TarError, match="traversal"),
    ):
        updater._safe_extractall(tar, tmp_path)


def test_safe_extractall_rejects_absolute_member(tmp_path) -> None:
    blob = _tarball_with_members(["/etc/evil"])
    with (
        tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar,
        pytest.raises(tarfile.TarError, match="absolute"),
    ):
        updater._safe_extractall(tar, tmp_path)


def test_safe_extractall_rejects_escaping_relative_member(tmp_path) -> None:
    blob = _tarball_with_members(["a/../../escape.txt"])
    with (
        tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar,
        pytest.raises(tarfile.TarError, match="traversal"),
    ):
        updater._safe_extractall(tar, tmp_path)


def test_safe_extractall_rejects_symlink_absolute_target(tmp_path) -> None:
    """A symlink member whose link target is absolute must be refused."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    buf.seek(0)
    with (
        tarfile.open(fileobj=buf, mode="r:gz") as tar,
        pytest.raises(tarfile.TarError, match="absolute link target"),
    ):
        updater._safe_extractall(tar, tmp_path)


def test_safe_extractall_rejects_symlink_escaping_target(tmp_path) -> None:
    """A symlink member whose link target escapes the root must be refused."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../outside"
        tar.addfile(info)
    buf.seek(0)
    with (
        tarfile.open(fileobj=buf, mode="r:gz") as tar,
        pytest.raises(tarfile.TarError, match="escaping"),
    ):
        updater._safe_extractall(tar, tmp_path)


def test_safe_extractall_accepts_benign_tree(tmp_path) -> None:
    blob = _tarball_with_members(["SKILL.md", "config/dimensions/core.yaml"])
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        updater._safe_extractall(tar, tmp_path)
    assert (tmp_path / "SKILL.md").is_file()
    assert (tmp_path / "config" / "dimensions" / "core.yaml").is_file()


def test_safe_extractall_refuses_symlink_without_data_filter(tmp_path, monkeypatch) -> None:
    """On Python < 3.12 (no ``tarfile.data_filter``) any symlink/hardlink
    member must be refused outright: the fallback extraction cannot follow a
    link chain out of the root, and the release tarball ships no links."""
    monkeypatch.delattr(tarfile, "data_filter", raising=False)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "target"  # benign-looking relative target
        tar.addfile(info)
    buf.seek(0)
    with (
        tarfile.open(fileobj=buf, mode="r:gz") as tar,
        pytest.raises(tarfile.TarError, match="without the data extraction filter"),
    ):
        updater._safe_extractall(tar, tmp_path)


def test_safe_extractall_accepts_benign_tree_without_data_filter(tmp_path, monkeypatch) -> None:
    """The no-data_filter fallback still extracts a benign, link-free tree."""
    monkeypatch.delattr(tarfile, "data_filter", raising=False)
    blob = _tarball_with_members(["SKILL.md", "config/dimensions/core.yaml"])
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        updater._safe_extractall(tar, tmp_path)
    assert (tmp_path / "SKILL.md").is_file()
    assert (tmp_path / "config" / "dimensions" / "core.yaml").is_file()


# ---------------------------------------------------------------------------
# Byte-accurate download cap (_urlopen_bounded)
# ---------------------------------------------------------------------------


def test_urlopen_bounded_enforces_byte_cap(monkeypatch) -> None:
    """The 50 MiB cap must be enforced on bytes, not chunk count."""

    class FakeResponse:
        def __init__(self, total: int) -> None:
            self.remaining = total

        def read(self, size: int) -> bytes:
            if self.remaining <= 0:
                return b""
            chunk = min(size, self.remaining)
            self.remaining -= chunk
            return b"x" * chunk

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __getattr__(self, name):
            return 200  # status used nowhere here; be permissive

    class FakeRequest:
        def add_header(self, key: str, value: str) -> None:
            return None

    _totals: list[int] = []  # assigned dynamically below via closure

    def fake_request(url: str, method: str = "GET"):
        req = FakeRequest()
        req._total = _totals
        return req

    monkeypatch.setattr(
        updater.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(request._total.pop(0)),
    )
    monkeypatch.setattr(updater.urllib.request, "Request", fake_request)

    # Exactly at the cap: allowed.
    cap = updater.MAX_DOWNLOAD_BYTES
    _totals[:] = [cap]
    assert len(updater._urlopen_bounded("https://x.invalid/a", 10, {})) == cap
    # One byte over the cap: rejected.
    _totals[:] = [cap + 1]
    with pytest.raises(OSError, match="safety cap"):
        updater._urlopen_bounded("https://x.invalid/a", 10, {})


# ---------------------------------------------------------------------------
# --assistants name validation
# ---------------------------------------------------------------------------


def test_validate_assistant_names_known_names_ok() -> None:
    from iterate_cli.updater import ASSISTANT_SKILL_DIRS

    known = list(ASSISTANT_SKILL_DIRS)[:2]
    assert updater.validate_assistant_names(known) == []


def test_validate_assistant_names_unknown_reported() -> None:
    unknown = updater.validate_assistant_names(["claude", "not-a-real-assistant"])
    assert unknown == ["not-a-real-assistant"]


def test_validate_assistant_names_empty_skips_are_valid() -> None:
    assert updater.validate_assistant_names([]) == []
    assert updater.validate_assistant_names(None) == []


def test_run_update_rejects_unknown_assistants_before_network(tmp_path) -> None:
    """Unknown --assistants names fail fast with no download/apply."""
    home, proj = _fake_home(tmp_path)

    def fetch(url: str, **kw):
        raise AssertionError("network must not be touched for unknown assistants")

    outcome = run_update(
        project_root=proj, home=home, confirmed=True, fetch=fetch,
        assistants=["claude", "bogus"],
    )
    assert outcome.assistants_unknown == ["bogus"]
    assert outcome.unreachable is False
    assert outcome.latest is None


def test_update_outcome_to_dict_includes_unknown_assistants() -> None:
    outcome = UpdateOutcome(current="3.3.1", assistants_unknown=["bogus"])
    d = outcome.to_dict()
    assert d["assistants_unknown"] == ["bogus"]


# ---------------------------------------------------------------------------
# CLI exit-code semantics for `iterate update` (JSON report)
# ---------------------------------------------------------------------------


def _report_json(outcome: UpdateOutcome, capsys, monkeypatch) -> int:
    from iterate_cli import cli

    monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)
    return cli._report_update_outcome(outcome, json_output=True)


def test_report_json_successful_update_returns_zero(capsys, monkeypatch) -> None:
    """A successfully-applied update exits 0 in --json mode (was 1)."""
    outcome = UpdateOutcome(
        current="3.4.0",
        latest="3.4.1",
        check_only=False,
        up_to_date=False,
        cancelled=False,
        cli_result=UpdateResult(True, "CLI reinstalled from verified release source"),
        assistants_updated=["claude"],
    )
    code = _report_json(outcome, capsys, monkeypatch)
    assert code == 0


def test_report_json_failed_cli_update_returns_one(capsys, monkeypatch) -> None:
    outcome = UpdateOutcome(
        current="3.4.0",
        latest="3.4.1",
        check_only=False,
        up_to_date=False,
        cli_result=UpdateResult(False, "pip failed"),
    )
    code = _report_json(outcome, capsys, monkeypatch)
    assert code == 1


def test_report_json_unknown_assistants_returns_one(capsys, monkeypatch) -> None:
    outcome = UpdateOutcome(
        current="3.4.0",
        latest="3.4.1",
        check_only=False,
        up_to_date=False,
        assistants_unknown=["bogus"],
    )
    code = _report_json(outcome, capsys, monkeypatch)
    assert code == 1


def test_report_json_up_to_date_returns_zero(capsys, monkeypatch) -> None:
    outcome = UpdateOutcome(current="3.4.0", latest="3.4.0", up_to_date=True)
    code = _report_json(outcome, capsys, monkeypatch)
    assert code == 0