"""Tests that keep the four release version sources in sync.

The iterate-skill version is duplicated across four files that ship to
different platforms (PyPI-style metadata, the CLI, the skill manifest, and the
npm installer). A post-patch bump (e.g. 3.0.0 -> 3.0.1) that touches only one
of them lets ``iterate doctor``/``refresh`` skill_version drift from the
installer's ``--version``. These tests fail the build when the sources diverge.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    """Read ``[project].version`` from pyproject.toml (3.11+ stdlib, else tomli)."""
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
        import tomli as tomllib  # type: ignore[no-redef]
    with open(REPO_ROOT / "pyproject.toml", "rb") as handle:
        data = tomllib.load(handle)
    return data["project"]["version"]


def _cli_version() -> str:
    """Read ``__version__`` from iterate_cli/__init__.py."""
    source = (REPO_ROOT / "iterate_cli" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', source)
    assert match, "iterate_cli/__init__.py missing __version__ literal"
    return match.group(1)


def _skill_version() -> str:
    """Read the ``version`` field from SKILL.md frontmatter."""
    text = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---"), "SKILL.md must start with a YAML frontmatter block"
    _, frontmatter, _rest = text.split("---", 2)
    data = yaml.safe_load(frontmatter)
    return str(data["version"])


def _npm_version() -> str:
    """Read the ``version`` field from npm-installer/package.json."""
    data = json.loads((REPO_ROOT / "npm-installer" / "package.json").read_text(encoding="utf-8"))
    return str(data["version"])


def _changelog_version() -> str:
    """Read the first ``## [x.y.z]`` heading from CHANGELOG.md."""
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    for line in changelog.splitlines():
        stripped = line.strip()
        if stripped.startswith("## [") and "[3." in stripped:
            end = stripped.find("]")
            version = stripped[4:end]
            if version.count(".") == 2:
                return version
    raise AssertionError("CHANGELOG.md must have a `## [x.y.z]` heading")


def test_five_version_sources_agree() -> None:
    """pyproject.toml / CLI / SKILL.md / npm installer / CHANGELOG must all agree."""
    versions = {
        "pyproject.toml": _pyproject_version(),
        "iterate_cli/__init__.py": _cli_version(),
        "SKILL.md frontmatter": _skill_version(),
        "npm-installer/package.json": _npm_version(),
        "CHANGELOG.md": _changelog_version(),
    }
    unique = set(versions.values())
    assert len(unique) == 1, f"version sources drifted: {versions}"


def _version_chain_gaps(changelog: str) -> tuple[list[int], list[tuple[int, int]]]:
    """Return (missing minors, missing patches) for the 3.x release chain.

    Every minor from 3.4 upward must have a heading, and within each minor the
    patches must be contiguous from ``.0`` to that minor's highest patch. It
    deliberately does NOT demand a patch for every minor: the skill line
    skipped 3.6.1/3.7.1 (those tags belong to iterate-plugin), so demanding a
    global 0..latest-patch range would force invented release notes.
    """
    patches_by_minor: dict[int, set[int]] = {}
    for line in changelog.splitlines():
        stripped = line.strip()
        if stripped.startswith("## [3."):
            end = stripped.find("]")
            parts = stripped[4:end].split(".")
            if len(parts) == 3 and parts[0] == "3":
                patches_by_minor.setdefault(int(parts[1]), set()).add(int(parts[2]))
    latest_minor = max(patches_by_minor)
    missing_minors = [m for m in range(4, latest_minor + 1) if m not in patches_by_minor]
    missing_patches = sorted(
        (m, p)
        for m, patches in patches_by_minor.items()
        for p in range(max(patches) + 1)
        if p not in patches
    )
    return missing_minors, missing_patches


def test_changelog_version_chain_has_no_gaps() -> None:
    """Every released minor version in CHANGELOG.md must have a heading.

    A release-notes block that lost its ``## [x.y.z]`` heading (the 3.4.1
    orphan) silently merges into the neighbouring release, so the patch
    history is unreadable and the next version is mis-numbered. Lock the
    invariant that the 3.x series is contiguous from 3.4.0 upward.
    """
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    missing_minors, missing_patches = _version_chain_gaps(changelog)
    assert not missing_minors, f"CHANGELOG.md is missing minor headings for 3.{missing_minors}"
    assert not missing_patches, f"CHANGELOG.md is missing headings for 3.{missing_patches}"


def test_version_chain_allows_skipped_patch_but_rejects_internal_gap() -> None:
    """Plugin-only patch numbers must not be demanded, real gaps still fail.

    Regression for the 3.8.1 release: the old global range demanded 3.6.1 and
    3.7.1 (iterate-plugin tags) as soon as the skill published its first patch,
    turning a green main red on a tag that had no way to add those headings.
    """
    without_plugin_patches = (
        "## [3.4.0]\n## [3.5.0]\n## [3.6.0]\n## [3.7.0]\n## [3.8.0]\n## [3.8.2]\n"
    )
    assert _version_chain_gaps(without_plugin_patches) == ([], [(8, 1)])

    missing_minor = "## [3.4.0]\n## [3.5.0]\n## [3.7.0]\n"
    assert _version_chain_gaps(missing_minor) == ([6], [])


def test_version_is_three_part_semver() -> None:
    """The shared version must be a valid X.Y.Z semantic version."""
    version = _pyproject_version()
    pattern = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
    assert pattern.match(version), f"version {version!r} is not X.Y.Z semver"

def _documented_examples() -> list[str]:
    """Return every ``iterate ...`` example line inside a fenced code block.

    Only fenced blocks are scanned so prose mentioning ``iterate status`` does
    not count as a command entry. The trailing ``# comment`` is stripped, so
    two lines that differ only in their comment still register as the same
    invocation.
    """
    skill = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
    examples: list[str] = []
    in_fence = False
    for line in skill.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        stripped = line.strip()
        if stripped.startswith("iterate "):
            examples.append(stripped.split("#", 1)[0].rstrip())
    return examples


def test_skill_md_command_list_matches_the_parser() -> None:
    """Every command SKILL.md shows must exist, and none may be duplicated.

    Regression: the CLI reference listed ``iterate status`` twice (once bare,
    once with its ``--json`` notes) while ``guard`` and ``invariant`` — both
    shipped subcommands — were absent, so the documented surface neither
    matched the parser nor listed each command once.
    """
    import argparse

    from iterate_cli.cli import _build_parser

    parser = _build_parser()
    subaction = next(
        a
        for a in parser._actions
        if isinstance(a, argparse._SubParsersAction)
    )
    available = set(subaction.choices)

    examples = _documented_examples()
    assert examples, "SKILL.md has no fenced `iterate <command>` examples"

    documented = [line.split()[1] for line in examples]
    unknown = sorted({c for c in documented if c not in available})
    assert not unknown, f"SKILL.md documents commands the parser lacks: {unknown}"

    # The two that were missing entirely.
    for required in ("guard", "invariant"):
        assert required in documented, f"SKILL.md never shows `iterate {required}`"

    # No invocation may be shown twice. Keyed on the whole command line so the
    # legitimate variants (`config` / `config get` / `config set`, and
    # `guard pre-check` / `guard post-check`) do not read as duplicates.
    duplicates = sorted({line for line in examples if examples.count(line) > 1})
    assert not duplicates, f"SKILL.md shows these lines twice: {duplicates}"


# ---------------------------------------------------------------------------
# Pinned release-signing key must stay identical across all three copies
# ---------------------------------------------------------------------------

_SIGNING_FINGERPRINT = "0929EA31DF4F7429F63FC53189D88B1D043A1298"


def _key_from_python(path: Path) -> str:
    """Extract the armored key from a ``ITERATE_SIGNING_PUBLIC_KEY = \"\"\"…\"\"\"``
    (or ``…: Final[str] = \"\"\"…\"\"\"``) assignment."""
    source = path.read_text(encoding="utf-8")
    match = re.search(
        r'ITERATE_SIGNING_PUBLIC_KEY(?::\s*Final\[str\])?\s*=\s*"""(.*?)"""',
        source,
        re.DOTALL,
    )
    assert match, f"{path} is missing the ITERATE_SIGNING_PUBLIC_KEY triple-quoted literal"
    return match.group(1).strip()


def _key_from_js(path: Path) -> str:
    """Extract the armored key from the JS array-of-strings constant."""
    source = path.read_text(encoding="utf-8")
    start = source.index("const ITERATE_SIGNING_PUBLIC_KEY = [")
    end = source.index("]", start)
    parts = re.findall(r"'([^']*)'", source[start:end])
    assert parts, f"{path} is missing ITERATE_SIGNING_PUBLIC_KEY entries"
    return "\n".join(parts).strip()


def test_pinned_signing_key_is_identical_in_all_three_copies() -> None:
    """A silent key swap in one copy would make installers refuse every release
    (fail closed) or, worse, verify against the wrong anchor. All three copies
    must be byte-identical.

    The release workflow refuses to sign with any key other than this
    fingerprint, so drift here breaks the release, not the security model —
    which is exactly why it must be caught in CI.
    """
    python_cli = _key_from_python(REPO_ROOT / "iterate_cli" / "signing.py")
    python_installer = _key_from_python(REPO_ROOT / "scripts" / "install.py")
    js_installer = _key_from_js(REPO_ROOT / "npm-installer" / "lib" / "installer.js")

    assert python_cli == python_installer, (
        "iterate_cli/signing.py and scripts/install.py embed different public keys"
    )
    assert python_cli == js_installer, (
        "iterate_cli/signing.py and npm-installer/lib/installer.js embed different public keys"
    )


def test_signing_fingerprint_is_declared_in_every_copy() -> None:
    """Each copy must NAME the pinned fingerprint, so diagnostics can point at
    the expected key and the release workflow can assert it."""
    for relative in (
        "iterate_cli/signing.py",
        "scripts/install.py",
        "npm-installer/lib/installer.js",
        ".github/workflows/release.yml",
    ):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert _SIGNING_FINGERPRINT in text, f"{relative} does not name the pinned key fingerprint"


# ---------------------------------------------------------------------------
# ITERATE_ALLOW_UNSIGNED: the "unsigned is allowed" value set must agree
# across every path that reads it
# ---------------------------------------------------------------------------


def _frozenset_from_python(path: Path, assignment: str) -> frozenset[str]:
    """Extract ``assignment = frozenset({...})`` literals, preserving order."""
    source = path.read_text(encoding="utf-8")
    pattern = rf"{re.escape(assignment)}\s*(?::\s*Final\[frozenset\[str\]\])?\s*=\s*frozenset\({{([^}}]*)}}\)"
    match = re.search(pattern, source)
    assert match, f"{path} is missing a `frozenset(...)` assignment for {assignment}"
    return frozenset(v.strip().strip("'\"") for v in match.group(1).split(",") if v.strip())


def _set_from_js(path: Path, assignment: str) -> frozenset[str]:
    """Extract ``const assignment = new Set([...])`` string entries."""
    source = path.read_text(encoding="utf-8")
    pattern = rf"const\s+{re.escape(assignment)}\s*=\s*new Set\(\[([^\]]*)\]\)"
    match = re.search(pattern, source)
    assert match, f"{path} is missing a `new Set([...])` constant for {assignment}"
    return frozenset(v.strip().strip("'\"") for v in match.group(1).split(",") if v.strip())


def test_allow_unsigned_value_sets_agree_across_all_paths() -> None:
    """All three code paths must agree on which values disable signature
    enforcement.

    A truthiness test that treats every non-empty value as an opt-out means
    ``ITERATE_ALLOW_UNSIGNED=0`` ("keep signatures mandatory") silently DISABLES
    them — the opposite of the operator's intent. That fix landed independently
    in each of the three installers; if one copy is loosened or widened without
    the others, an operator would get a *different* security posture depending on
    which binary they ran, and there is no single place to see the discrepancy.
    Lock the value set together so drift is a build failure.
    """
    values = {
        "iterate_cli/signing.py": _frozenset_from_python(
            REPO_ROOT / "iterate_cli" / "signing.py",
            "ALLOW_UNSIGNED_TRUE_VALUES",
        ),
        "scripts/install.py": _frozenset_from_python(
            REPO_ROOT / "scripts" / "install.py",
            "_ALLOW_UNSIGNED_TRUE_VALUES",
        ),
        "npm-installer/lib/installer.js": _set_from_js(
            REPO_ROOT / "npm-installer" / "lib" / "installer.js",
            "ALLOW_UNSIGNED_TRUTHY",
        ),
    }
    assert len(set(values.values())) == 1, f"ALLOW_UNSIGNED value sets drifted: {values}"

    canonical = values["iterate_cli/signing.py"]
    assert {"1", "true", "yes"} <= canonical, (
        f"the documented opt-out values are missing: {sorted(canonical)}"
    )
    # A value that must NEVER enable the override, whichever path reads it.
    for forbidden in ("0", "false", "no", "off"):
        assert forbidden not in canonical, (
            f"{forbidden!r} must not enable the unsigned-install override"
        )
