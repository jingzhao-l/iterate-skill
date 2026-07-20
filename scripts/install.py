#!/usr/bin/env python3
"""Iterate skill installer.

Inspired by ui-ux-pro-max-skill's uipro-cli, this script copies the skill
into the target AI assistant's skills directory.

Usage:
    python scripts/install.py --ai trae --target /path/to/project
    python scripts/install.py --ai claude --target /path/to/project
    python scripts/install.py --ai cursor --target /path/to/project
    python scripts/install.py --ai all --target /path/to/project
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SUPPORTED_AI = {
    "trae": ".trae/skills/iterate",
    "claude": ".claude/skills/iterate",
    "cursor": ".cursor/skills/iterate",
}

REQUIRED_FILES = [
    "SKILL.md",
    "config/iterate.config.yaml",
    "config/config.schema.json",
    "config/dimensions.yaml",
    "config/dimensions",
    "scripts/validate.py",
    "scripts/requirements.txt",
    "templates/iterate-decisions.template.md",
]

OPTIONAL_FILES = [
    "README.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "tools/SKILL.trae.md",
    "tools/SKILL.claude.md",
    "tools/SKILL.cursor.md",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install iterate-skill into an AI assistant's skills directory."
    )
    parser.add_argument(
        "--ai",
        required=True,
        choices=list(SUPPORTED_AI.keys()) + ["all"],
        help="Target AI assistant.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.cwd(),
        help="Project or home directory to install into (default: current directory).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be copied without copying.",
    )
    return parser.parse_args(argv)


def copy_skill_files(source: Path, destination: Path, dry_run: bool) -> list[str]:
    copied: list[str] = []
    all_files = REQUIRED_FILES + OPTIONAL_FILES

    for relative in all_files:
        src = source / relative
        if not src.exists():
            if relative in REQUIRED_FILES:
                raise FileNotFoundError(f"Required skill file missing: {src}")
            continue

        dst = destination / relative
        if dry_run:
            copied.append(f"{src} -> {dst}")
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        copied.append(str(dst))

    return copied


def install(ai: str, target: Path, dry_run: bool, source: Path) -> None:
    targets = list(SUPPORTED_AI.keys()) if ai == "all" else [ai]

    for assistant in targets:
        relative_dir = SUPPORTED_AI[assistant]
        destination = target / relative_dir

        if dry_run:
            print(f"[dry-run] Would install for {assistant} into {destination}")
        else:
            print(f"Installing for {assistant} into {destination}")

        copied = copy_skill_files(source, destination, dry_run)
        for item in copied:
            print(f"  {item}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source = Path(__file__).resolve().parent.parent

    if not args.target.exists():
        print(f"Error: target directory does not exist: {args.target}", file=sys.stderr)
        return 1

    try:
        install(args.ai, args.target.resolve(), args.dry_run, source)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("Dry run complete; no files were copied.")
    else:
        print("Installation complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
