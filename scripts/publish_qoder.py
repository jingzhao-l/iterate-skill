#!/usr/bin/env python3
"""Dedicated Qoder packaging script for the iterate skill.

Mirrors how SkillHub / ModelScope / ClawHub each get their own distribution
machinery (see RELEASE.md): the only canonical "skill body" is the ``git archive
':!harness'`` extraction, so this script rebuilds a Qoder-specific package from
that same body and validates it against Qoder's package rules. Publication to
the Qoder AppHub is done manually by the operator (it is a logged-in web UI,
not a public CLI/API), so this script stops at producing a ready-to-upload zip.

Qoder package rules enforced here:
  * a single top-level directory whose name equals the ``name`` in ``SKILL.md``
    frontmatter (this skill -> ``iterate/``)
  * ``SKILL.md`` must start with YAML frontmatter (``name``/``description``/``version``)
  * ``name`` must stay identical across all versions
  * unpacked size < 50 MB and zip size < 50 MB
  * ``harness/*`` must be absent (project-wide "skill only, not the harness" rule)

Usage:
  python scripts/publish_qoder.py check [-p PATH]        # preflight a built dir/zip
  python scripts/publish_qoder.py build [--out PATH] ... # rebuild the Qoder zip locally
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
import zipfile
from collections.abc import Iterable

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAX_PACKAGE_BYTES = 50 * 1024 * 1024  # 50 MB (Qoder upper limit)

# The canonical skill-body extraction mirrors the release manual: exclude the
# independent harness/plugin sub-projects. Everything else is user-extendable.
MANDATORY_EXCLUDES = ("harness",)

# Dev/share artifacts that are git-tracked but never part of the skill body.
DEFAULT_EXCLUDES = (".trae-html-share-packages",)

# Recognised SKILL.md frontmatter keys: Qoder interprets three of them.
QODER_FRONTMATTER_KEYS = ("name", "description", "version")

# Qoder third-person description with natural-language trigger keywords. Used
# when building a Qoder package without an explicit --description override.
QODER_DESCRIPTION = (
    "Automatically review and fix code across an entire codebase over multiple "
    "rounds. Runs many parallel reviewers, each focused on a dimension such as "
    "correctness, security, performance, and architecture; fixes atomic issues "
    "directly and executes architecture-level changes only after the user "
    "approves, validating after each round until no findings remain. Use for "
    "pre-release code review, bug hunting, security hardening, and refactoring. "
    "Supports a read-only review mode."
)

_FRONTMATTER_KEY_RE = re.compile(r"^[ \t]*([A-Za-z0-9_.-]+)[ \t]*:[ \t]*(.*)$")


# --------------------------------------------------------------------------- #
# Small frontmatter helper (stdlib only; this project avoids third-party deps).#
# --------------------------------------------------------------------------- #
def parse_frontmatter(text: str) -> tuple[dict[str, str], int]:
    """Parse the leading YAML frontmatter of ``text``.

    Returns ``(fields, body_start)`` where ``fields`` maps each ``key: value``
    line to its raw right-hand side (kept verbatim), and ``body_start`` is the
    index in ``text`` at which the Markdown body begins (just past the closing
    ``---`` delimiter). Raises ``ValueError`` when there is no valid block.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md does not start with a YAML frontmatter block")
    fields: dict[str, str] = {}
    body_start = len(text)
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            # body begins at the start of the line after the closing delimiter
            consumed = sum(len(line) + 1 for line in lines[: idx + 1])
            body_start = min(consumed, len(text))
            return fields, body_start
        match = _FRONTMATTER_KEY_RE.match(lines[idx])
        if match:
            fields[match.group(1)] = match.group(2)
    raise ValueError("frontmatter block is missing its closing '---' delimiter")


def rewrite_frontmatter(
    text: str, description: str | None = None
) -> tuple[str, list[str]]:
    """Rewrite SKILL.md so only Qoder's ``name/description/version`` remain.

    The Markdown body is preserved verbatim. ``description`` (optional)
    replaces the source description with a Qoder third-person/trigger version.
    Returns ``(new_text, changes)`` with a log of every key that was dropped so
    nothing is discarded silently.
    """
    fields, body_start = parse_frontmatter(text)
    changes: list[str] = []
    for key in fields:
        if key not in QODER_FRONTMATTER_KEYS:
            changes.append(f"dropped frontmatter key {key!r} (Qoder ignores it)")
    if description is not None:
        changes.append("replaced description with Qoder third-person/trigger version")
    if not any(key in fields for key in ("name",)):
        raise ValueError("SKILL.md frontmatter must keep at least a 'name'")
    header = ["---"]
    header.append(f"name: {fields['name']}")
    header.append(f"description: {description or fields.get('description', '')}")
    if "version" in fields:
        header.append(f"version: {fields['version']}")
    header.append("---")
    new_text = "\n".join(header) + "\n" + text[body_start:]
    return new_text, changes


def detect_extra_frontmatter(text: str) -> list[str]:
    """Return warnings for frontmatter keys Qoder does not understand."""
    fields, _ = parse_frontmatter(text)
    return [
        f"frontmatter key {key!r} is non-standard for Qoder (ignored there)"
        for key in fields
        if key not in QODER_FRONTMATTER_KEYS
    ]


def frontmatter_name(text: str) -> str:
    fields, _ = parse_frontmatter(text)
    name = fields.get("name")
    if not name:
        raise ValueError("SKILL.md frontmatter is missing its 'name' field")
    return name.strip()


def frontmatter_version(text: str) -> str | None:
    fields, _ = parse_frontmatter(text)
    version = fields.get("version")
    return version.strip() if version else None


# --------------------------------------------------------------------------- #
# Package building                                                             #
# --------------------------------------------------------------------------- #
def _copy_tree(src: str, dst: str, excludes: Iterable[str]) -> None:
    """Recursively copy ``src`` into ``dst``, skipping excluded top fields."""
    for entry in os.listdir(src):
        if entry in excludes or entry.startswith("."):
            continue
        shutil.copytree(
            os.path.join(src, entry),
            os.path.join(dst, entry),
        )


def _git_archive_extract(dst: str, excludes: Iterable[str]) -> list[str]:
    """Extract the canonical skill body (git archive ':!harness') under dst.

    Returns warnings; raises RuntimeError when ``git`` is missing or fails.
    """
    specs = [f":!{pat}" for pat in (*MANDATORY_EXCLUDES, *excludes)]
    warnings: list[str] = []
    tmp_zip = os.path.join(dst, ".archive-src.zip")
    cmd = ["git", "archive", "--format=zip", "-o", tmp_zip, "HEAD", *specs]
    result = os.system(" ".join(cmd))
    if result != 0:
        raise RuntimeError("git archive failed; are you in the repo root?")
    with zipfile.ZipFile(tmp_zip) as archive:
        for member in archive.namelist():
            archive.extract(member, dst)
    os.remove(tmp_zip)
    return warnings


def build_package(
    version: str | None,
    *,
    out: str | None,
    source: str | None,
    exclude: Iterable[str] = (),
    frontmatter: str = "keep",
    description: str | None = None,
) -> tuple[str, list[str], dict[str, object]]:
    """Build the Qoder zip under an ``iterate/`` top directory.

    Returns ``(zip_path, warnings, meta)``. ``frontmatter='minimal'`` applies
    the full Qoder adaptation (clean frontmatter, third-person description,
    references/ index, self-containment note) to the staged copy only.
    """
    excludes = tuple(exclude)
    all_excludes = (*MANDATORY_EXCLUDES, *DEFAULT_EXCLUDES, *excludes)
    warnings: list[str] = []
    meta: dict[str, object] = {}

    with tempfile.TemporaryDirectory(prefix="qoder-pkg-") as tmp:
        stage = os.path.join(tmp, "iterate")
        os.makedirs(stage, exist_ok=True)

        if source is not None:
            _copy_tree(source, stage, all_excludes)
            warnings.append(f"copied from --source {source!r} (copy path, not git archive)")
        else:
            try:
                warnings.extend(_git_archive_extract(stage, all_excludes))
            except (RuntimeError, OSError) as exc:
                warnings.append(f"git archive unavailable ({exc}); falling back to copy")
                _copy_tree(REPO_ROOT, stage, all_excludes)

        skill_path = os.path.join(stage, "SKILL.md")
        if not os.path.isfile(skill_path):
            raise ValueError("packaged tree has no SKILL.md at its root")

        with open(skill_path, "r", encoding="utf-8") as handle:
            skill_text = handle.read()
        detected_name = frontmatter_name(skill_text)
        meta["name"] = detected_name
        meta["version"] = frontmatter_version(skill_text)

        if detected_name == "iterate" and os.path.basename(stage) != detected_name:
            warnings.append(
                f"top-level dir is {os.path.basename(stage)!r}, renamed to {detected_name!r}"
            )
            alt = os.path.join(tmp, detected_name)
            shutil.move(stage, alt)
            stage = alt

        if frontmatter == "minimal":
            qoder_description = description if description is not None else QODER_DESCRIPTION
            if any(
                key not in QODER_FRONTMATTER_KEYS for key in detect_frontmatter_keys(skill_text)
            ) or description is not None:
                rewritten, changes = rewrite_frontmatter(
                    skill_text, description=qoder_description
                )
                with open(skill_path, "w", encoding="utf-8") as handle:
                    handle.write(rewritten)
                warnings.extend(changes)
            else:
                warnings.append("--frontmatter minimal: frontmatter already Qoder-compatible")
            warnings.extend(_append_dependencies_section(skill_path))
            warnings.extend(_gen_references_index(stage))
        else:
            warnings.extend(detect_extra_frontmatter(skill_text))

        errors, check_warnings = validate_tree(stage)
        if errors:
            raise ValueError("package failed Qoder checks:\n- " + "\n- ".join(errors))
        warnings.extend(check_warnings)

        if not version:
            version = meta["version"] or "local"
        zip_path = out or os.path.join(tmp, f"iterate-{version}-qoder.zip")
        _zip_dir(stage, zip_path)
        meta["size"] = os.path.getsize(zip_path)
        meta["zip"] = zip_path
        meta["top_level"] = os.path.basename(stage)
        shutil.move(zip_path, os.path.abspath(zip_path))
        return os.path.abspath(zip_path), warnings, meta


def detect_frontmatter_keys(text: str) -> list[str]:
    fields, _ = parse_frontmatter(text)
    return list(fields.keys())


_DEP_MARKER = "<!-- QODER:DEPENDENCIES -->"


def _append_dependencies_section(skill_path: str) -> list[str]:
    """Append a self-containment/deployment note to the Qoder SKILL.md copy."""
    with open(skill_path, "r", encoding="utf-8") as handle:
        text = handle.read()
    if _DEP_MARKER in text:  # already annotated on a previous build
        return []
    section = (
        "## 依赖说明 / Dependencies & Self-Containment\n\n"
        "This is a fully self-contained package. Every file the skill loads at "
        "runtime — `config/`, `scripts/`, `templates/`, `iterate_cli/`, "
        "`pyproject.toml`, `npm-installer/` — ships inside this directory, so "
        "running the skill needs no pre-installed `npx`/`pip`/CLI. The CLI is "
        "optional: `npx iterate-skill-installer` downloads the release tarball "
        "from GitHub and verifies it against `SHA256SUMS.txt` (mandatory checksum "
        "check) before installing. The auxiliary files resolved at runtime are "
        "indexed in `references/INDEX.md`.\n\n"
        "<!-- " + _DEP_MARKER.replace("-->", "").replace("<!-- ", "") + " -->\n"
    )
    with open(skill_path, "a", encoding="utf-8") as handle:
        handle.write("\n" + section)
    return ["appended Qoder dependencies/self-containment section to SKILL.md"]


_INDEX_ROWS = (
    ("config/iterate.config.yaml", "Step 1.4", "Master default configuration (deep-merged with project overrides)"),
    ("config/dimensions/", "Phase 1 + Step 1.4", "Reviewer dimension definitions (focus prompts, priorities)"),
    ("scripts/validate.py", "config validation", "Validates iterate.config.yaml / decision log / dimensions"),
    ("scripts/install.py", "installer", "Installs the skill into supported assistants' directories"),
    ("templates/onboarding-playbook.md", "Step 0", "AI onboarding scan checklist + tech-stack mapping"),
    ("iterate_cli/", "`iterate` CLI", "CLI onboarding / personalize / status / doctor / show"),
    ("pyproject.toml", "CLI entry point", "Python package definition (`iterate` console entry point)"),
    ("npm-installer/", "bootstrap installer", "`npx iterate-skill-installer` bootstrap (pull release + verify SHA256)"),
)


def _gen_references_index(stage: str) -> list[str]:
    """Write ``references/INDEX.md`` listing the shipped runtime dependencies."""
    rows = [
        "| Path | Invoked by | Purpose |",
        "|---|---|---|",
    ]
    for path, where, purpose in _INDEX_ROWS:
        if os.path.exists(os.path.join(stage, path)):
            rows.append(f"| `{path}` | {where} | {purpose} |")
    index = (
        "# Iterate — Qoder auxiliary dependency index\n\n"
        "This skill package is self-contained: every file the skill references "
        "at runtime ships in this `iterate/` directory. The paths below are "
        "resolved relative to `SKILL.md` (i.e. this directory). None require "
        "network access to run the skill standalone.\n\n"
        + "\n".join(rows)
        + "\n"
    )
    refs = os.path.join(stage, "references")
    os.makedirs(refs, exist_ok=True)
    with open(os.path.join(refs, "INDEX.md"), "w", encoding="utf-8") as handle:
        handle.write(index)
    return ["wrote references/INDEX.md dependency manifest"]


def _zip_dir(directory: str, zip_path: str) -> None:
    """Zip ``directory`` so its basename is the single top-level entry."""
    base = os.path.basename(directory.rstrip(os.sep))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for root, dirs, files in os.walk(directory):
            dirs.sort()
            for name in files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, directory)
                archive.write(full, os.path.join(base, rel))


# --------------------------------------------------------------------------- #
# Validation                                                                    #
# --------------------------------------------------------------------------- #
def validate_tree(tree_root: str) -> tuple[list[str], list[str]]:
    """Run Qoder package checks on an unpacked package tree.

    Returns ``(errors, warnings)``; ``errors`` means the package must not ship.
    """
    errors: list[str] = []
    warnings: list[str] = []

    top_dir = os.path.basename(tree_root.rstrip(os.sep))
    if top_dir != "iterate":
        errors.append(f"top-level directory is {top_dir!r}; must be 'iterate'")

    skill_path = os.path.join(tree_root, "SKILL.md")
    if not os.path.isfile(skill_path):
        errors.append("SKILL.md missing at package root")
        return errors, warnings
    with open(skill_path, "r", encoding="utf-8") as handle:
        text = handle.read()
    try:
        name = frontmatter_name(text)
        if name != top_dir:
            errors.append(
                f"frontmatter name {name!r} != top-level directory {top_dir!r}"
            )
    except ValueError as exc:
        errors.append(str(exc))

    # Skill-only rule: zero harness/ anywhere under the package.
    harness_hits = _find_harness(tree_root)
    if harness_hits:
        errors.append("harness/ must be absent (skill-only distribution): " + ", ".join(harness_hits))

    total_bytes = _tree_size(tree_root)
    if total_bytes > MAX_PACKAGE_BYTES:
        errors.append(
            f"unpacked size {total_bytes} bytes > 50 MB limit"
        )
    return errors, warnings


def _find_harness(tree_root: str) -> list[str]:
    hits: list[str] = []
    for root, dirs, _files in os.walk(tree_root):
        for name in dirs:
            if name == "harness":
                hits.append(os.path.relpath(os.path.join(root, name), tree_root))
    return hits


def _tree_size(tree_root: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(tree_root):
        for name in files:
            total += os.path.getsize(os.path.join(root, name))
    return total


def validate_zip(zip_path: str) -> tuple[list[str], list[str], int]:
    """Validate a Qoder package zip; returns (errors, warnings, zip_size)."""
    errors: list[str] = []
    warnings: list[str] = []
    zip_size = os.path.getsize(zip_path)
    if zip_size > MAX_PACKAGE_BYTES:
        errors.append(f"zip size {zip_size} bytes > 50 MB")
    if not zipfile.is_zipfile(zip_path):
        errors.append("not a valid zip")
        return errors, warnings, zip_size
    names: list[str] = []
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        for entry in names:
            info = archive.getinfo(entry)
            if info.is_dir():
                continue
            if "harness" in entry.split("/"):
                errors.append(f"harness/ present in package: {entry}")
    if not names:
        errors.append("empty zip")
        return errors, warnings, zip_size
    top = names[0].split("/")[0]
    if top != "iterate":
        errors.append(f"top-level entry {top!r}; must be 'iterate'")
    return errors, warnings, zip_size


def check_package(path: str) -> int:
    """CLI for the ``check`` subcommand."""
    if os.path.isdir(path):
        errors, warnings = validate_tree(path)
    else:
        errors, warnings, _size = validate_zip(path)
    for warning in warnings:
        print("warning: " + warning)
    if errors:
        for error in errors:
            print("error: " + error)
        return 1
    print(f"ok: {path} passes Qoder package checks")
    return 0


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="publish_qoder",
        description="Rebuild and validate the Qoder skill package for iterate.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check_p = sub.add_parser("check", help="preflight a built package (dir or zip)")
    check_p.add_argument("path", help="path to an iterate/ dir or a built zip")

    build_p = sub.add_parser("build", help="rebuild the Qoder-compatible zip locally")
    build_p.add_argument("--source", help="use this dir instead of git archive of repo root")
    build_p.add_argument("--out", help="output zip path")
    build_p.add_argument(
        "--version",
        help="version to embed in the default zip name (default: SKILL.md frontmatter version)",
    )
    build_p.add_argument(
        "--description",
        help="Qoder third-person description; default is a built-in keyword-rich description",
    )
    build_p.add_argument(
        "--frontmatter",
        choices=("keep", "minimal"),
        default="minimal",
        help="'minimal' (default) rewrites to name/description/version + adds references/ and a self-containment note; 'keep' leaves SKILL.md as-is (non-standard keys warned)",
    )
    build_p.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="additional top-level paths to exclude (repeatable)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "check":
        return check_package(args.path)

    if args.command == "build":
        _, warnings, meta = build_package(
            args.version,
            out=args.out,
            source=args.source,
            exclude=args.exclude or (),
            frontmatter=args.frontmatter,
            description=args.description,
        )
        for warning in warnings:
            print("warning: " + warning)
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())