#!/usr/bin/env python3
"""Iterate skill CLI.

Inspired by ui-ux-pro-max-skill's uipro-cli, this script installs the skill
into AI assistants' skills directories and provides helpers to manage the
project-level iterate.config.yaml.

Usage:
    python scripts/install.py --ai trae --target /path/to/project
    python scripts/install.py install --ai all --target /path/to/project
    python scripts/install.py config --init --target /path/to/project
    python scripts/install.py config --set goal="Improve code quality"
    python scripts/install.py config --set dimensions='[correctness, security]'
    python scripts/install.py config --interactive
    python scripts/install.py uninstall --ai trae --target /path/to/project
    python scripts/install.py validate --target /path/to/project
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

SUPPORTED_AI = {
    "trae": ".trae/skills/iterate",
    "claude": ".claude/skills/iterate",
    "cursor": ".cursor/skills/iterate",
    "windsurf": ".windsurf/skills/iterate",
    "copilot": ".github/skills/iterate",
    "codex": ".codex/skills/iterate",
    "roocode": ".roo/skills/iterate",
    "qoder": ".qoder/skills/iterate",
    "gemini": ".gemini/skills/iterate",
    "opencode": ".opencode/skills/iterate",
    "continue": ".continue/skills/iterate",
    "augment": ".augment/skills/iterate",
    "warp": ".warp/skills/iterate",
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

AI_CHOICES = list(SUPPORTED_AI.keys()) + ["all"]

DEFAULT_CONFIG_PATH = Path("config/iterate.config.yaml")

DIMENSION_CHOICES = [
    "correctness",
    "security",
    "performance",
    "architecture",
    "style-tests",
    "tech-debt",
    "spec-compliance",
    "frontend-backend",
    "ui-ux",
]

LANGUAGE_CHOICES = ["zh", "en"]
SCOPE_CHOICES = ["full", "changed-only"]


def copy_skill_files(source: Path, destination: Path, dry_run: bool) -> list[str]:
    """Copy skill files from source to destination."""
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


def install_command(ai: str, target: Path, dry_run: bool, source: Path) -> int:
    """Install the skill for one or more AI assistants."""
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

    if dry_run:
        print("Dry run complete; no files were copied.")
    else:
        print("Installation complete.")
    return 0


def uninstall_command(ai: str, target: Path) -> int:
    """Remove the skill for one or more AI assistants."""
    targets = list(SUPPORTED_AI.keys()) if ai == "all" else [ai]

    for assistant in targets:
        relative_dir = SUPPORTED_AI[assistant]
        destination = target / relative_dir

        if not destination.exists():
            print(f"Skipped (not installed): {assistant} at {destination}")
            continue

        shutil.rmtree(destination)
        print(f"Uninstalled {assistant}: {destination}")

    print("Uninstall complete.")
    return 0


def _load_validate_module(source: Path):
    """Import validate.py from the source scripts directory."""
    import importlib.util

    validate_path = source / "scripts" / "validate.py"
    spec = importlib.util.spec_from_file_location("validate", validate_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load validate module from {validate_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_command(target: Path, source: Path) -> int:
    """Validate the project-level iterate.config.yaml."""
    config_path = target / "iterate.config.yaml"
    schema_path = source / "config" / "config.schema.json"

    if not config_path.exists():
        print(f"No project config found at {config_path}")
        return 1

    try:
        validate = _load_validate_module(source)
    except ImportError as exc:
        print(f"Failed to import validate.py: {exc}", file=sys.stderr)
        return 1

    errors = validate.validate_config(config_path, schema_path)
    if errors:
        print(f"Validation failed for {config_path}")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(f"Validation passed: {config_path}")
    return 0


def parse_value(raw: str) -> object:
    """Parse a config value from CLI string using YAML/JSON semantics."""
    stripped = raw.strip()
    if not stripped:
        return ""

    try:
        parsed = yaml.safe_load(stripped)
    except yaml.YAMLError:
        parsed = None

    if parsed is None:
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = stripped

    return parsed


def set_nested_value(config: dict[str, object], key: str, value: object) -> None:
    """Set a possibly nested config key, creating intermediate mappings."""
    parts = key.split(".")
    current = config
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def load_config(path: Path) -> dict[str, object]:
    """Load a YAML config file or return an empty mapping."""
    if not path.exists():
        return {}

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}: {exc}") from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Configuration must be a YAML mapping: {path}")
    return data


def save_config(path: Path, config: dict[str, object]) -> None:
    """Save a config mapping to a YAML file with helpful comments."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def init_config(target: Path, source: Path) -> int:
    """Copy the master config to the project root if it does not exist."""
    master_path = source / DEFAULT_CONFIG_PATH
    project_path = target / "iterate.config.yaml"

    if project_path.exists():
        print(f"Project config already exists: {project_path}")
        print("Use --set to modify it, or delete it first to re-initialize.")
        return 1

    if not master_path.exists():
        print(f"Master config not found: {master_path}", file=sys.stderr)
        return 1

    project_path.write_text(master_path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Initialized project config: {project_path}")
    return 0


def list_config(target: Path) -> int:
    """Print the current project-level config."""
    project_path = target / "iterate.config.yaml"
    if not project_path.exists():
        print(f"No project config found at {project_path}")
        return 1

    config = load_config(project_path)
    print(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    return 0


def set_config_values(target: Path, set_pairs: list[list[str]]) -> int:
    """Apply --set key=value pairs to the project-level config."""
    project_path = target / "iterate.config.yaml"
    config = load_config(project_path) if project_path.exists() else {}

    for group in set_pairs:
        for pair in group:
            if "=" not in pair:
                print(f"Invalid --set argument (expected key=value): {pair}", file=sys.stderr)
                return 1
            key, value = pair.split("=", 1)
            key = key.strip()
            if not key:
                print(f"Empty key in --set argument: {pair}", file=sys.stderr)
                return 1
            set_nested_value(config, key, parse_value(value))

    save_config(project_path, config)
    print(f"Updated project config: {project_path}")
    return 0


def prompt_choice(question: str, choices: list[str], default: str | None = None) -> str:
    """Ask the user to select one option from a list."""
    print(f"\n{question}")
    for idx, choice in enumerate(choices, start=1):
        marker = " (default)" if choice == default else ""
        print(f"  {idx}. {choice}{marker}")
    while True:
        answer = input("Enter number or name: ").strip()
        if not answer and default is not None:
            return default
        if answer.isdigit():
            idx = int(answer) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        if answer in choices:
            return answer
        print("Invalid choice, please try again.")


def prompt_text(question: str, default: str | None = None) -> str:
    """Ask the user for free-form text input."""
    default_hint = f" [{default}]" if default else ""
    while True:
        answer = input(f"\n{question}{default_hint}: ").strip()
        if answer:
            return answer
        if default is not None:
            return default
        print("A value is required.")


def prompt_int(question: str, default: int | None = None) -> int:
    """Ask the user for an integer."""
    default_hint = f" [{default}]" if default is not None else ""
    while True:
        answer = input(f"\n{question}{default_hint}: ").strip()
        if not answer and default is not None:
            return default
        try:
            return int(answer)
        except ValueError:
            print("Please enter a valid integer.")


def prompt_bool(question: str, default: bool = True) -> bool:
    """Ask the user a yes/no question."""
    default_text = "Y/n" if default else "y/N"
    while True:
        answer = input(f"\n{question} [{default_text}]: ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please enter 'y' or 'n'.")


def interactive_config(target: Path, source: Path) -> int:
    """Run an interactive wizard to create or update the project config."""
    project_path = target / "iterate.config.yaml"
    master_path = source / DEFAULT_CONFIG_PATH

    if project_path.exists():
        config = load_config(project_path)
    elif master_path.exists():
        config = load_config(master_path)
    else:
        config = {}

    print("=== iterate-skill configuration wizard ===")

    config["goal"] = prompt_text("Iteration goal", config.get("goal", "Improve code quality"))
    config["max_rounds"] = prompt_int("Max rounds", config.get("max_rounds", 7))
    config["language"] = prompt_choice(
        "Output language", LANGUAGE_CHOICES, config.get("language", "en")
    )
    config["dimensions"] = prompt_dimensions(config.get("dimensions", DIMENSION_CHOICES))
    config["review"] = config.get("review", {})
    config["review"]["scope"] = prompt_choice(
        "Review scope", SCOPE_CHOICES, config["review"].get("scope", "full")
    )
    config["atomic"] = config.get("atomic", {})
    config["atomic"]["max_lines"] = prompt_int(
        "Atomic issue max lines", config["atomic"].get("max_lines", 20)
    )
    config["git"] = config.get("git", {})
    config["git"]["push_per_round"] = prompt_bool(
        "Push after each round", config["git"].get("push_per_round", True)
    )

    save_config(project_path, config)
    print(f"\nConfiguration saved: {project_path}")
    return 0


def prompt_dimensions(current: object) -> list[str]:
    """Interactively select enabled dimensions."""
    current_set = set(current) if isinstance(current, list) else set(DIMENSION_CHOICES)
    selected = []
    print("\nSelect review dimensions (enter numbers/names, comma-separated):")
    for idx, dim in enumerate(DIMENSION_CHOICES, start=1):
        marker = " [enabled]" if dim in current_set else ""
        print(f"  {idx}. {dim}{marker}")
    answer = input("Dimensions: ").strip()
    if not answer:
        return list(current_set)

    for part in answer.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(DIMENSION_CHOICES):
                selected.append(DIMENSION_CHOICES[idx])
        elif part in DIMENSION_CHOICES:
            selected.append(part)

    return selected if selected else list(current_set)


def config_command(
    target: Path,
    source: Path,
    init: bool,
    list_config_flag: bool,
    interactive: bool,
    set_pairs: list[list[str]] | None = None,
) -> int:
    """Manage the project-level iterate.config.yaml."""
    if init:
        return init_config(target, source)
    if list_config_flag:
        return list_config(target)
    if set_pairs:
        return set_config_values(target, set_pairs)
    if interactive:
        return interactive_config(target, source)

    print("No config action specified. Use --init, --list, --set, or --interactive.")
    return 1


def _add_install_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "install", help="Install the skill into an AI assistant's skills directory."
    )
    parser.add_argument(
        "--ai", required=True, choices=AI_CHOICES, help="Target AI assistant (or 'all')."
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.cwd(),
        help="Project or home directory (default: current directory).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print what would be copied without copying."
    )


def _add_uninstall_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "uninstall", help="Remove the skill from an AI assistant's skills directory."
    )
    parser.add_argument(
        "--ai", required=True, choices=AI_CHOICES, help="Target AI assistant (or 'all')."
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.cwd(),
        help="Project directory (default: current directory).",
    )


def _add_validate_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "validate", help="Validate the project-level iterate.config.yaml."
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.cwd(),
        help="Project directory (default: current directory).",
    )


def _add_config_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "config", help="Manage the project-level iterate.config.yaml."
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.cwd(),
        help="Project directory (default: current directory).",
    )
    parser.add_argument(
        "--init", action="store_true", help="Copy the master config to the project root."
    )
    parser.add_argument(
        "--list",
        dest="list_config",
        action="store_true",
        help="Print the current project config.",
    )
    parser.add_argument(
        "--set",
        action="append",
        nargs="+",
        metavar="KEY=VALUE",
        help="Set a config value (supports nested keys like validation.commands.python).",
    )
    parser.add_argument(
        "--interactive", action="store_true", help="Run an interactive configuration wizard."
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="iterate-skill",
        description="Install and configure iterate-skill for AI coding assistants.",
    )
    subparsers = parser.add_subparsers(dest="command")
    _add_install_parser(subparsers)
    _add_uninstall_parser(subparsers)
    _add_validate_parser(subparsers)
    _add_config_parser(subparsers)
    return parser


def parse_legacy_args(argv: list[str] | None) -> argparse.Namespace | None:
    """Support the original direct install invocation for backward compatibility."""
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        return None
    if args[0] in ("install", "uninstall", "validate", "config"):
        return None
    if "--ai" not in args:
        return None

    parser = argparse.ArgumentParser()
    parser.add_argument("--ai", required=True, choices=AI_CHOICES)
    parser.add_argument("--target", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    namespace = parser.parse_args(args)
    namespace.command = "install"
    return namespace


def main(argv: list[str] | None = None, source: Path | None = None) -> int:
    """CLI entry point."""
    if source is None:
        source = Path(__file__).resolve().parent.parent

    legacy = parse_legacy_args(argv)
    if legacy is not None:
        args = legacy
    else:
        parser = build_parser()
        args = parser.parse_args(argv)

    if not args.command:
        build_parser().print_help()
        return 1

    if args.command == "install":
        if not args.target.exists():
            print(f"Error: target directory does not exist: {args.target}", file=sys.stderr)
            return 1
        try:
            return install_command(args.ai, args.target.resolve(), args.dry_run, source)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.command == "uninstall":
        if not args.target.exists():
            print(f"Error: target directory does not exist: {args.target}", file=sys.stderr)
            return 1
        return uninstall_command(args.ai, args.target.resolve())

    if args.command == "validate":
        if not args.target.exists():
            print(f"Error: target directory does not exist: {args.target}", file=sys.stderr)
            return 1
        return validate_command(args.target.resolve(), source)

    if args.command == "config":
        return config_command(
            args.target.resolve(),
            source,
            args.init,
            args.list_config,
            args.interactive,
            args.set,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
