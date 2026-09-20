"""``iterate update`` — self-update support for the iterate-skill CLI and skill files.

The skill is distributed in two halves that need refreshing:

1. **The CLI package** (``iterate_cli``, entry point ``iterate``), installed
   into the current interpreter by pip / pipx / ``pip install -e .``.
2. **The assistant skill directories** (SKILL.md + config/ + iterate_cli/ +
   scripts/ + templates/ ...), installed into AI assistant dirs such as
   ``~/.claude/skills/iterate`` by the installer.

``iterate update`` downloads the latest GitHub release tarball
(``iterate-skill.tar.gz`` + ``SHA256SUMS.txt``), verifies its SHA-256 before
any write, then (a) refreshes installed assistant skill dirs and (b) re-installs
the CLI package from the verified release source. ``--check`` never writes
anything — it only compares versions. A cached (24h) advisory hint on
``iterate --version`` tells users an update exists.

All external I/O (network, subprocess, filesystem) is injectable so the module
is fully testable without network access and so CI / non-interactive callers
can opt in via ``--yes``. UI concerns (prompts, markup) live in the CLI layer;
this module never reads stdin.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from iterate_cli import __version__

# ---------------------------------------------------------------------------
# Named constants (no magic strings scattered through the business logic)
# ---------------------------------------------------------------------------

GITHUB_REPO_OWNER = "jingzhao-l"
GITHUB_REPO_NAME = "iterate-skill"
RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/latest"

TARBALL_ASSET_NAME = "iterate-skill.tar.gz"
CHECKSUMS_ASSET_NAME = "SHA256SUMS.txt"

#: Top-level paths never copied into an assistant dir regardless of contents —
#: the skill release never carries harness/ and an assistant dir must never
#: gain it. Mirrors ``scripts/install.py`` ``copy_skill_files`` handling.
EXCLUDED_TOP_LEVEL = {"harness"}

#: XDG-compatible config home used for the update-check cache.
CONFIG_DIR_NAME = "iterate-skill"
CACHE_FILE_NAME = "update-check.json"
CACHE_TTL_SECONDS = 24 * 60 * 60

UPDATE_CHECK_ENV = "ITERATE_UPDATE_CHECK"  # "0"/"off"/"false" disables the hint

HTTP_TIMEOUT_SECONDS = 15
DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MiB safety cap on any single payload
_DOWNLOAD_CHUNK_SIZE = 64 * 1024
MAX_EXTRACT_BYTES = 600 * 1024 * 1024  # total uncompressed (decompression-bomb guard)
MAX_EXTRACT_MEMBER_BYTES = 300 * 1024 * 1024  # per-member cap
GIT_TIMEOUT_SECONDS = 120
PIP_TIMEOUT_SECONDS = 600

INSTALL_METHOD_SOURCE = "source"
INSTALL_METHOD_PIP = "pip"

VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+")

#: The latest-release JSON key carrying the version (also accepts pre/suffixes).
_TAG_VERSION_KEYS = ("tag_name", "name")

#: sha256sum file matcher: ``<hex digest> <spaces> [*]<filename>``.
_CHECKSUM_LINE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(\S.*)$", re.MULTILINE)

#: Well-known assistant skill-dir layouts. MUST stay identical to
#: ``scripts/install.py`` ``SUPPORTED_AI`` — a cross-source sync test in
#: ``tests/test_updater_sync.py`` locks the two maps together.
ASSISTANT_SKILL_DIRS: dict[str, str] = {
    "claude": ".claude/skills/iterate",
    "claude-code": ".claude/skills/iterate",
    "cursor": ".cursor/skills/iterate",
    "trae": ".trae/skills/iterate",
    "windsurf": ".windsurf/skills/iterate",
    "copilot": ".github/skills/iterate",
    "codex": ".codex/skills/iterate",
    "gemini": ".gemini/skills/iterate",
    "gemini-cli": ".gemini/skills/iterate",
    "opencode": ".opencode/skills/iterate",
    "aider": ".aider/skills/iterate",
    "aiderdesk": ".aiderdesk/skills/iterate",
    "zed": ".zed/skills/iterate",
    "warp": ".warp/skills/iterate",
    "continue": ".continue/skills/iterate",
    "cline": ".cline/skills/iterate",
    "roocode": ".roo/skills/iterate",
    "qoder": ".qoder/skills/iterate",
    "augment": ".augment/skills/iterate",
    "openclaw": "skills/iterate",
    "autohand": ".autohand/skills/iterate",
    "bob": ".bob/skills/iterate",
    "codearts": ".codeartsdoer/skills/iterate",
    "antigravity": ".antigravity/skills/iterate",
    "amp": ".amp/skills/iterate",
    "deepagents": ".deepagents/skills/iterate",
    "kimi": ".kimi/skills/iterate",
    "astral": ".astral/skills/iterate",
}

#: Skill files/dirs refreshed into an assistant dir. Required entries must
#: exist in the verified release source; optional ones are copied when present.
#: MUST stay identical to ``scripts/install.py`` REQUIRED_FILES/OPTIONAL_FILES
#: (locks: ``tests/test_updater_sync.py``).
REQUIRED_RELEASE_PATHS = [
    "SKILL.md",
    "config/iterate.config.yaml",
    "config/config.schema.json",
    "config/dimensions.yaml",
    "config/dimensions",
    "scripts/validate.py",
    "scripts/requirements.txt",
    "templates/iterate-decisions.template.md",
    "iterate_cli",
    "pyproject.toml",
    "templates/ITERATE.template.md",
    "templates/onboarding-playbook.md",
]

OPTIONAL_RELEASE_PATHS = [
    "README.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "CHANGELOG.md",
    "examples/python-project.md",
    "examples/swift-project.md",
    "examples/typescript-project.md",
    "tools/SKILL.trae.md",
    "tools/SKILL.claude.md",
    "tools/SKILL.cursor.md",
]


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class ReleaseUnavailableError(RuntimeError):
    """The latest release could not be reached or parsed."""


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------


def normalize_version(raw: object) -> str | None:
    """Extract an ``X.Y.Z`` version from arbitrary release tag/name text."""
    match = VERSION_PATTERN.search(str(raw or "").strip())
    return match.group(0) if match else None


def _version_tuple(version: str) -> tuple[int, int, int]:
    numbers = [int(part) for part in re.findall(r"\d+", version) if part]
    if not numbers:
        raise ValueError(f"not a version string: {version!r}")
    while len(numbers) < 3:
        numbers.append(0)
    return (numbers[0], numbers[1], numbers[2])


def compare_versions(current: str, latest: str) -> int:
    """Return ``-1``/``0``/``1`` comparing ``latest`` against ``current``.

    A positive result means ``latest`` is newer than ``current``.
    """
    return (
        1
        if _version_tuple(latest) > _version_tuple(current)
        else -1
        if _version_tuple(latest) < _version_tuple(current)
        else 0
    )


# ---------------------------------------------------------------------------
# Network layer (stdlib urllib only; injectable for tests)
# ---------------------------------------------------------------------------


@dataclass
class _Fetched:
    """Minimal HTTP response surface consumed by the injectable ``fetch`` callables."""

    status: int
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


@dataclass
class ReleaseInfo:
    """Latest-release facts the updater needs."""

    tag: str
    tarball_url: str
    checksum_url: str | None = None


def _urlopen_bounded(url: str, timeout: float, headers: dict[str, str]) -> bytes:
    """GET ``url`` returning the body, refusing to read past the size cap."""
    request = urllib.request.Request(url, method="GET")
    for key, value in headers.items():
        request.add_header(key, value)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(_DOWNLOAD_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise OSError(f"payload exceeds {MAX_DOWNLOAD_BYTES} byte safety cap")
            chunks.append(chunk)
    return b"".join(chunks)


def _default_fetch(url: str, *, timeout: float, headers: dict[str, str]) -> _Fetched:
    """urllib-backed fetch used in production."""
    body = _urlopen_bounded(url, timeout, headers)
    return _Fetched(status=200, body=body)


def _error_reason(exc: BaseException, prefix: str) -> str:
    detail = str(exc)
    return f"{prefix}: {detail}" if detail else prefix


def fetch_latest_release(
    fetch: Callable[..., _Fetched] | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> tuple[ReleaseInfo | None, str | None]:
    """Discover the latest published release.

    Returns ``(info, error_reason)`` — ``error_reason`` is None on success;
    on failure ``info`` is None and ``error_reason`` explains why. The
    ``fetch`` callable can be injected for tests (defaults to urllib).
    """
    fetcher = fetch if fetch is not None else _default_fetch
    try:
        response = fetcher(
            RELEASE_API_URL,
            timeout=timeout,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "iterate-skill-updater",
            },
        )
    except urllib.error.HTTPError as exc:
        status = exc.code
        if status == 403:
            return None, "GitHub API rate limit exceeded (HTTP 403); retry later"
        return None, f"GitHub API returned HTTP {status}"
    except urllib.error.URLError as exc:
        return None, f"GitHub API network error: {exc.reason}"
    except TimeoutError:
        return None, f"GitHub API request timed out after {timeout}s"
    except OSError as exc:
        return None, _error_reason(exc, "GitHub API connection error")
    except Exception as exc:  # noqa: BLE001 — a cleanup fallback, never crash
        return None, _error_reason(exc, "GitHub API request failed")

    if response.status != 200:
        return None, f"GitHub API returned HTTP {response.status}"
    try:
        payload = response.json()
    except ValueError as exc:
        return None, f"GitHub API returned invalid JSON: {exc}"

    tag = None
    if isinstance(payload, dict):
        for key in _TAG_VERSION_KEYS:
            tag = normalize_version(payload.get(key))
            if tag is not None:
                break
    if tag is None:
        return None, "GitHub API response is missing a vX.Y.Z version"

    tarball_url: str | None = None
    checksum_url: str | None = None
    assets = payload.get("assets") if isinstance(payload, dict) else None
    if isinstance(assets, list):
        for item in assets:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            url = item.get("browser_download_url")
            if not isinstance(url, str):
                continue
            if name == TARBALL_ASSET_NAME:
                tarball_url = url
            elif name == CHECKSUMS_ASSET_NAME:
                checksum_url = url
    if not isinstance(tarball_url, str):
        return None, f"latest release has no {TARBALL_ASSET_NAME} asset"
    return (
        ReleaseInfo(tag=tag, tarball_url=tarball_url, checksum_url=checksum_url),
        None,
    )


# ---------------------------------------------------------------------------
# Verified release download + safe extraction
# ---------------------------------------------------------------------------


def _sha256_of(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def parse_checksums(data: bytes) -> dict[str, str]:
    """Parse a sha256sum-style file into ``{filename: hexdigest}``.

    Accepts coreutils ``sha256sum`` output (``<digest>  <name>``) and the
    ``*name`` binary marker used by ``shasum -a 256``.
    """
    text = data.decode("utf-8", errors="replace")
    result: dict[str, str] = {}
    for match in _CHECKSUM_LINE.finditer(text):
        digest, name = match.groups()
        result[name.strip()] = digest.lower()
    return result


def _download_bytes(
    url: str,
    fetch: Callable[..., _Fetched],
    timeout: float,
    what: str,
) -> tuple[bytes | None, str | None]:
    """Fetch a URL body, returning ``(data, error_reason)``."""
    try:
        response = fetch(
            url, timeout=timeout, headers={"User-Agent": "iterate-skill-updater"}
        )
    except urllib.error.HTTPError as exc:
        return None, f"{what} returned HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return None, f"{what} network error: {exc.reason}"
    except TimeoutError:
        return None, f"{what} timed out after {timeout}s"
    except OSError as exc:
        return None, _error_reason(exc, f"{what} failed")
    except Exception as exc:  # noqa: BLE001 — any fetch failure is a clean fallback
        return None, _error_reason(exc, f"{what} failed")
    if response.status != 200:
        return None, f"{what} returned HTTP {response.status}"
    return response.body, None


def _verify(tarball: bytes, checksums: bytes) -> str | None:
    """Return None on match, else the human-readable rejection reason."""
    expected = parse_checksums(checksums).get(TARBALL_ASSET_NAME)
    if expected is None:
        return f"checksum file has no {TARBALL_ASSET_NAME} entry"
    actual = _sha256_of(tarball)
    if actual != expected:
        return (
            f"SHA-256 mismatch: expected {expected}, got {actual}; refusing any write"
        )
    return None


def _safe_extractall(tar: tarfile.TarFile, path: Path) -> None:
    """Extract ``tar`` under ``path``, refusing traversal/escape/bomb members."""
    members = tar.getmembers()
    total = 0
    for member in members:
        if member.isdev() or member.isfifo():
            raise tarfile.TarError(f"refusing device/fifo member: {member.name!r}")
        if member.size > MAX_EXTRACT_MEMBER_BYTES:
            raise tarfile.TarError(
                f"suspicious member size: {member.name} is {member.size} bytes"
            )
        total += member.size
        if total > MAX_EXTRACT_BYTES:
            raise tarfile.TarError("archive expands past the decompression-bomb cap")
        name = member.name.replace("\\", "/")
        if name.startswith(("/", "\\")):
            raise tarfile.TarError(f"refusing absolute member path: {member.name!r}")
        normalized = os.path.normpath(name)
        if normalized in (".", ""):
            continue
        if normalized.startswith("..") or "/../" in f"/{normalized}":
            raise tarfile.TarError(
                f"refusing path traversal member: {member.name!r}"
            )
        if member.issym() or member.islnk():
            link = member.linkname.replace("\\", "/")
            if link.startswith(("/", "\\")):
                raise tarfile.TarError(
                    f"refusing absolute link target: {member.name!r} -> {member.linkname!r}"
                )
            norm_link = os.path.normpath(link)
            if norm_link.startswith("..") or "/../" in f"/{norm_link}":
                raise tarfile.TarError(
                    f"refusing escaping link target: {member.name!r} -> {member.linkname!r}"
                )
    if hasattr(tarfile, "data_filter"):
        tar.extractall(path=path, filter="data")
    else:
        # No Python-3.12 data_filter here: refuse the one archive form the
        # member scan above cannot fully contain (a symlink/hardlink member
        # whose safe-looking target is redirected out-of-root through a later
        # intermediate link). The release tarball ships no links, so a link on
        # an older interpreter is by definition a tampered archive.
        if any(member.issym() or member.islnk() for member in members):
            raise tarfile.TarError(
                "refusing symlink/hardlink member without the data extraction filter"
            )
        tar.extractall(path=path)


def download_verified_release(
    release: ReleaseInfo,
    fetch: Callable[..., _Fetched] | None = None,
    timeout: float = DOWNLOAD_TIMEOUT_SECONDS,
) -> tuple[Path | None, str | None]:
    """Download + verify + extract the release tarball into a temp dir.

    Refuses a release with no checksum asset and refuses extraction on any
    SHA-256 mismatch, so nothing is written unless the archive is authentic.
    The returned path is the extracted repo root (``<tmp>/<tag>/source/``);
    the caller owns cleanup (``shutil.rmtree`` the temp parent).
    """
    fetcher = fetch if fetch is not None else _default_fetch

    if not release.checksum_url:
        return None, f"release {release.tag} has no {CHECKSUMS_ASSET_NAME} asset"

    tarball, tarball_err = _download_bytes(
        release.tarball_url, fetcher, timeout, "release tarball"
    )
    if tarball is None:
        return None, tarball_err or "tarball download failed"
    checksums, checksums_err = _download_bytes(
        release.checksum_url, fetcher, timeout, "checksum file"
    )
    if checksums is None:
        return None, checksums_err or "checksum download failed"

    reason = _verify(tarball, checksums)
    if reason is not None:
        return None, reason

    temp_parent = Path(tempfile.mkdtemp(prefix="iterate-update-"))
    extract_root = temp_parent / "source"
    try:
        extract_root.mkdir()
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
            _safe_extractall(tar, extract_root)
    except (tarfile.TarError, OSError, EOFError) as exc:
        shutil.rmtree(temp_parent, ignore_errors=True)
        return None, f"release archive invalid: {exc}"

    # The tarball is a ``git archive --prefix=iterate-skill/`` archive, so the
    # extracted content lives under a single top-level directory (the source
    # root for copy + pip reinstall).
    candidates = sorted(p for p in extract_root.iterdir() if p.is_dir())
    if len(candidates) != 1:
        shutil.rmtree(temp_parent, ignore_errors=True)
        return None, "release archive has an unexpected top-level layout"
    return candidates[0], None


# ---------------------------------------------------------------------------
# Install-method detection
# ---------------------------------------------------------------------------


def source_checkout_root() -> Path | None:
    """Return the repo root when running from a source checkout, else None.

    A source install (editable ``pip install -e .`` or running from a clone)
    has ``pyproject.toml`` + ``.git`` next to the ``iterate_cli`` package dir.
    """
    repo_root = Path(__file__).resolve().parent.parent
    if (repo_root / "pyproject.toml").is_file() and (repo_root / ".git").is_dir():
        return repo_root
    return None


def detect_install_method() -> str:
    """Classify how the running CLI is installed (``source`` or ``pip``)."""
    return (
        INSTALL_METHOD_SOURCE
        if source_checkout_root() is not None
        else INSTALL_METHOD_PIP
    )


# ---------------------------------------------------------------------------
# Assistant skill-dir detection + update
# ---------------------------------------------------------------------------


def _is_skill_dir(path: Path) -> bool:
    return (path / "SKILL.md").is_file()


def detect_assistant_dirs(project_root: Path, home: Path) -> list[tuple[str, Path]]:
    """Return ``(assistant, skill_dir)`` for assistants actually installed.

    Home (global install) wins over project-local dirs; a destination shared
    by several assistant names (e.g. ``claude``/``claude-code``) is reported
    once, keyed by the first name encountered. Only dirs that contain a
    SKILL.md are listed.
    """
    seen: dict[Path, str] = {}

    def consider(root: Path) -> None:
        for assistant, relative_dir in ASSISTANT_SKILL_DIRS.items():
            candidate = root / relative_dir
            if candidate in seen:
                continue
            if _is_skill_dir(candidate):
                seen[candidate] = assistant

    consider(home)
    consider(project_root)
    return sorted((assistant, path) for path, assistant in seen.items())


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _copy_release_path(source: Path, destination: Path, relative: str) -> None:
    """Copy one release path into the destination, replacing stale entries."""
    src = source / relative
    dst = destination / relative

    normalized_dst = Path(os.path.abspath(os.path.normpath(dst)))
    if not normalized_dst.is_relative_to(destination):
        raise ValueError(f"refusing to copy outside destination: {relative!r}")
    # Symlinked-ancestor guard: a committed/concurrent symlink at an
    # intermediate dir would route writes outside the selected destination.
    real_dst_parent = Path(os.path.realpath(dst.parent))
    if not (
        real_dst_parent == destination or real_dst_parent.is_relative_to(destination)
    ):
        raise ValueError(f"refusing to copy through symlinked directory: {relative!r}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.is_symlink() or dst.exists() and not dst.is_dir():
            dst.unlink()
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        if dst.is_symlink():
            dst.unlink()
        elif dst.exists() and dst.is_dir():
            shutil.rmtree(dst)
        shutil.copy2(src, dst)


def update_assistant_dir(source: Path, destination: Path) -> None:
    """Refresh one assistant skill dir from the verified release source.

    Copies the REQUIRED/OPTIONAL release paths (never harness/) and removes
    any stale ``harness`` still present from an older installer bug. Raises
    ``OSError``/``ValueError`` on failure so the caller can report which
    assistant failed.
    """
    destination = Path(destination).resolve()

    for relative in REQUIRED_RELEASE_PATHS + OPTIONAL_RELEASE_PATHS:
        src = source / relative
        if not src.exists():
            if relative in REQUIRED_RELEASE_PATHS:
                raise FileNotFoundError(
                    f"required skill file missing in release: {relative}"
                )
            continue
        _copy_release_path(source, destination, relative)

    # Stale-forbidden top-level cleanup (e.g. harness/ from a defective copy).
    for excluded in EXCLUDED_TOP_LEVEL:
        leftover = destination / excluded
        if leftover.is_symlink() or leftover.exists():
            _remove_path(leftover)


# ---------------------------------------------------------------------------
# CLI install-method update (pip / source)
# ---------------------------------------------------------------------------


@dataclass
class UpdateResult:
    """Outcome of one CLI reinstall step."""

    success: bool
    message: str


def _default_runner(
    argv: list[str], *, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    # ``check=False`` is deliberate: callers read ``returncode`` / ``success``
    # and turn a non-zero exit into a structured message themselves.
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, check=False
    )


def _run_command(
    argv: list[str],
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]],
    timeout: float,
    what: str,
) -> None:
    try:
        if runner is _default_runner:
            result = _default_runner(argv, timeout=timeout)
        else:
            result = runner(argv)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"{what} timed out after {timeout:g}s for command {argv!r}"
        ) from error
    except OSError as error:
        raise RuntimeError(f"{what} failed to start: {error}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"{what} failed (exit {result.returncode}){suffix}")


def update_cli_package(
    *,
    method: str,
    source_dir: Path | None = None,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> UpdateResult:
    """Reinstall the CLI package into the current environment.

    - ``source`` install → ``git pull --ff-only`` + ``pip install -e``.
    - ``pip`` install → ``pip install --upgrade --force-reinstall --no-deps``
      from the verified release source dir (never a raw URL: integrity is
      guaranteed by the updater's own SHA-256 gate).
    """
    command_runner = runner if runner is not None else _default_runner
    python = Path(sys.executable)
    try:
        if method == INSTALL_METHOD_SOURCE:
            root = source_checkout_root()
            if root is None:
                return UpdateResult(False, "could not locate the source checkout")
            if (root / ".git").is_dir():
                _run_command(
                    ["git", "-C", str(root), "pull", "--ff-only"],
                    command_runner,
                    GIT_TIMEOUT_SECONDS,
                    "git pull",
                )
            _run_command(
                [str(python), "-m", "pip", "install", "-e", str(root)],
                command_runner,
                PIP_TIMEOUT_SECONDS,
                "pip install -e",
            )
            return UpdateResult(
                True, "source checkout pulled and re-installed (editable)"
            )
        if source_dir is None:
            return UpdateResult(
                False, "no verified release source available to reinstall from"
            )
        _run_command(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--force-reinstall",
                "--no-deps",
                str(source_dir),
            ],
            command_runner,
            PIP_TIMEOUT_SECONDS,
            "pip install release source",
        )
        return UpdateResult(
            True, f"CLI reinstalled from verified release source {source_dir.name}"
        )
    except RuntimeError as error:
        return UpdateResult(False, str(error))


# ---------------------------------------------------------------------------
# Update-check cache (advisory ``--version`` hint)
# ---------------------------------------------------------------------------


def get_config_dir() -> Path:
    """Return the config home for the update-check cache (``$ITERATE_CONFIG_DIR``
    or ``~/.config`` based; dir created on first write only)."""
    base = os.environ.get("ITERATE_CONFIG_DIR") or Path.home() / ".config"
    return Path(base) / CONFIG_DIR_NAME


def get_check_cache_path() -> Path:
    return get_config_dir() / CACHE_FILE_NAME


def read_check_cache(cache_path: Path) -> dict[str, str]:
    if not cache_path.is_file():
        return {}
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if value}


def write_check_cache(cache_path: Path, latest: str) -> None:
    payload = {
        "latest": latest,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass  # advisory — cache write failure must never break --version


def is_check_stale(cache: dict[str, str], ttl_seconds: int = CACHE_TTL_SECONDS) -> bool:
    checked_at = cache.get("checked_at")
    if not checked_at:
        return True
    try:
        timestamp = datetime.fromisoformat(checked_at)
    except ValueError:
        return True
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - timestamp
    return age > timedelta(seconds=ttl_seconds)


def build_update_hint(
    *,
    current: str | None = None,
    cache_path: Path | None = None,
    fetch: Callable[..., _Fetched] | None = None,
    timeout: float = DOWNLOAD_TIMEOUT_SECONDS,
) -> str | None:
    """Return an advisory line when a newer release exists (cached 24h)."""
    cache_file = cache_path if cache_path is not None else get_check_cache_path()
    cached = read_check_cache(cache_file)
    if is_check_stale(cached):
        release, _ = fetch_latest_release(fetch=fetch, timeout=timeout)
        latest = release.tag if release is not None else None
        if latest is not None:
            write_check_cache(cache_file, latest)
            cached = read_check_cache(cache_file)
    latest = cached.get("latest")
    if not latest:
        return None
    installed = current if current is not None else __version__
    if compare_versions(installed, latest) <= 0:
        return None
    return (
        f"A new version {latest} is available (you have {installed}). "
        "Run `iterate update` to upgrade."
    )


def maybe_print_update_hint() -> None:
    """Best-effort one-line advisory on ``iterate --version``.

    Never raises: the hint must not break ``--version``. Disabled via
    ``ITERATE_UPDATE_CHECK=0`` / ``off`` / ``false``.
    """
    if os.environ.get(UPDATE_CHECK_ENV, "1").strip().lower() in {
        "0",
        "off",
        "false",
        "no",
    }:
        return
    try:
        hint = build_update_hint()
    except Exception:  # noqa: BLE001 — advisory only, never crash --version
        return
    if hint:
        print(f"[iterate] {hint}", file=sys.stderr)


# ---------------------------------------------------------------------------
# High-level orchestration (used by the ``iterate update`` CLI command)
# ---------------------------------------------------------------------------


@dataclass
class UpdateOutcome:
    """Everything the ``update`` command needs to report, incl. ``--json``."""

    current: str
    latest: str | None = None
    method: str = INSTALL_METHOD_PIP
    unreachable: bool = False
    up_to_date: bool = False
    check_only: bool = False
    cancelled: bool = False
    download_error: str | None = None
    cli_result: UpdateResult | None = None
    assistants_updated: list[str] = field(default_factory=list)
    assistants_failed: list[tuple[str, str]] = field(default_factory=list)
    assistants_unknown: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Structured representation for ``--json`` output."""
        return {
            "current_version": self.current,
            "latest_version": self.latest,
            "install_method": self.method,
            "up_to_date": self.up_to_date,
            "unreachable": self.unreachable,
            "cancelled": self.cancelled,
            "check_only": self.check_only,
            "download_error": self.download_error,
            "cli_update": (
                {
                    "success": self.cli_result.success,
                    "message": self.cli_result.message,
                }
                if self.cli_result is not None
                else None
            ),
            "assistants_updated": self.assistants_updated,
            "assistants_failed": [
                {"assistant": name, "error": reason}
                for name, reason in self.assistants_failed
            ],
            "assistants_unknown": self.assistants_unknown,
        }


def validate_assistant_names(assistants: list[str] | None) -> list[str]:
    """Return the ``--assistants`` names that are not known assistant keys.

    Empty list means every requested name is valid. An explicit empty list is
    itself a valid value (it means "skip the skill-dir refresh"), so it is
    never reported as unknown.
    """
    if not assistants:
        return []
    return [name for name in assistants if name not in ASSISTANT_SKILL_DIRS]


def run_update(
    *,
    project_root: Path,
    check_only: bool = False,
    confirmed: bool = False,
    assistants: list[str] | None = None,
    fetch: Callable[..., _Fetched] | None = None,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
    home: Path | None = None,
) -> UpdateOutcome:
    """Implement ``iterate update``.

    Pure orchestrator: reads nothing from stdin (the CLI layer asks the user
    and passes the resulting ``confirmed`` boolean) and never raises on
    network/file failure — every failure becomes a field on the returned
    ``UpdateOutcome``. ``fetch``/``runner`` are injectable for tests.

    Args:
        project_root: Project root used for project-local assistant detection.
        check_only: Compare versions only; never download or write.
        confirmed: User/automation consent to apply the update.
        assistants: Optional subset of assistant keys to refresh. ``[]`` means
            skip the skill-dir refresh entirely; ``None`` refreshes all
            detected assistants.
        fetch: Injectable HTTP fetch (defaults to urllib).
        runner: Injectable subprocess runner (defaults to real subprocess).
        home: Home directory used for global assistant detection.
    """
    home_path = home if home is not None else Path.home()
    current = __version__
    outcome = UpdateOutcome(
        current=current,
        method=detect_install_method(),
        check_only=check_only,
    )

    # Fail fast on unknown assistant names (before any network call): a typo
    # like ``--assistants cluade`` must not silently update only a subset of
    # the requested assistants or, worse, be mistaken for "no assistants".
    outcome.assistants_unknown = validate_assistant_names(assistants)
    if outcome.assistants_unknown:
        return outcome

    release, error = fetch_latest_release(fetch=fetch)
    if release is None:
        outcome.unreachable = True
        outcome.download_error = error or "could not reach GitHub releases"
        return outcome

    outcome.latest = release.tag
    outcome.up_to_date = compare_versions(current, release.tag) <= 0
    if check_only or outcome.up_to_date:
        return outcome

    if not confirmed:
        outcome.cancelled = True
        return outcome

    if assistants is not None and not assistants:
        # Explicitly requested no assistants: skip the skill-dir refresh.
        targeted: list[tuple[str, Path]] = []
    else:
        detected = detect_assistant_dirs(project_root, home_path)
        targeted = [
            (name, path)
            for name, path in detected
            if assistants is None or name in assistants
        ]

    extracted, dl_error = download_verified_release(release, fetch=fetch)
    if extracted is None:
        outcome.download_error = dl_error or "release download failed"
        return outcome

    try:
        for name, path in targeted:
            try:
                update_assistant_dir(extracted, path)
                outcome.assistants_updated.append(name)
            except (OSError, ValueError) as exc:
                outcome.assistants_failed.append((name, str(exc)))
        outcome.cli_result = update_cli_package(
            method=outcome.method,
            source_dir=extracted,
            runner=runner,
        )
    finally:
        shutil.rmtree(extracted.parent.parent, ignore_errors=True)
    return outcome
