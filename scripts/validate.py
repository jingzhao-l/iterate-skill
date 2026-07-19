#!/usr/bin/env python3
"""校验 iterate-skill 相关文件。

用法：
    python scripts/validate.py decisions <path-to-.iterate_decisions.md>
    python scripts/validate.py config <path-to-iterate.config.yaml>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


REQUIRED_DECISION_SECTIONS = [
    "Atomic Fixes (Direct)",
    "Architectural Fixes (Approved + Executed)",
    "Architectural Fixes (Deferred to Next Round)",
    "AI Important Decisions",
    "Validation",
]

CONFLICT_MARKERS = ["<<<<<<<", "=======", ">>>>>>>"]

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "config" / "config.schema.json"


def validate_decisions(path: Path) -> list[str]:
    """校验 .iterate_decisions.md 格式是否合规。"""
    errors: list[str] = []

    if not path.exists():
        errors.append(f"File not found: {path}")
        return errors

    content = path.read_text(encoding="utf-8")

    for marker in CONFLICT_MARKERS:
        if marker in content:
            errors.append(f"Unresolved git conflict marker found: {marker}")

    for section in REQUIRED_DECISION_SECTIONS:
        if section not in content:
            errors.append(f"Missing section: {section}")

    round_headers = re.findall(r"^## Round (\d+|\{N\}) — ", content, re.MULTILINE)
    if not round_headers:
        errors.append("No round headers found (expected '## Round N — ...')")

    return errors


def load_schema(schema_path: Path) -> dict[str, Any]:
    """加载 JSON Schema 文件。"""
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_config_against_schema(
    config: dict[str, Any], schema: dict[str, Any]
) -> list[str]:
    """使用 jsonschema 校验配置。"""
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:  # pragma: no cover - dependency guard
        return [f"jsonschema is required for schema validation: {exc}"]

    errors: list[str] = []
    validator = Draft202012Validator(schema)
    for error in validator.iter_errors(config):
        path = "/".join(str(part) for part in error.path) or "<root>"
        errors.append(f"Schema error at {path}: {error.message}")
    return errors


def command_is_whitelisted(command: str, whitelist: list[str]) -> bool:
    """检查命令是否以白名单中的某个前缀开头。"""
    stripped = command.strip()
    return any(stripped.startswith(prefix) for prefix in whitelist)


def validate_command_whitelist(config: dict[str, Any]) -> list[str]:
    """校验 validation.commands 中的命令是否在白名单内。"""
    errors: list[str] = []
    validation = config.get("validation", {})

    if not isinstance(validation, dict):
        errors.append("validation must be a mapping")
        return errors

    whitelist = validation.get("command_whitelist", [])
    commands_by_module = validation.get("commands", {})

    if not isinstance(whitelist, list) or not whitelist:
        errors.append("validation.command_whitelist must be a non-empty list")
        return errors

    if not isinstance(commands_by_module, dict):
        errors.append("validation.commands must be a mapping")
        return errors

    for module, commands in commands_by_module.items():
        if not isinstance(commands, list):
            errors.append(f"validation.commands.{module} must be a list")
            continue
        for idx, command in enumerate(commands):
            if not isinstance(command, str):
                errors.append(
                    f"validation.commands.{module}[{idx}] must be a string"
                )
                continue
            if not command_is_whitelisted(command, whitelist):
                errors.append(
                    f"validation.commands.{module}[{idx}] is not in command_whitelist: {command!r}"
                )

    return errors


def validate_config(path: Path, schema_path: Path | None = None) -> list[str]:
    """校验 iterate.config.yaml 格式、schema 与白名单。"""
    errors: list[str] = []

    if not path.exists():
        errors.append(f"File not found: {path}")
        return errors

    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        errors.append(f"Invalid YAML: {exc}")
        return errors

    if not isinstance(config, dict):
        errors.append("Configuration must be a YAML mapping")
        return errors

    schema = load_schema(schema_path or DEFAULT_SCHEMA_PATH)
    errors.extend(validate_config_against_schema(config, schema))
    errors.extend(validate_command_whitelist(config))
    return errors


def print_errors(source: str, errors: list[str]) -> None:
    """统一输出错误信息。"""
    print(f"Validation failed for {source}")
    for error in errors:
        print(f"  - {error}")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 1

    command, target_str = args[0], args[1]
    target = Path(target_str)

    if command == "decisions":
        errors = validate_decisions(target)
    elif command == "config":
        schema_path = Path(args[2]) if len(args) > 2 else None
        errors = validate_config(target, schema_path)
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        return 1

    if errors:
        print_errors(str(target), errors)
        return 1

    print(f"Validation passed: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
