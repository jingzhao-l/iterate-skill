#!/usr/bin/env python3
"""校验 .iterate_decisions.md 格式是否合规。

用法：
    python scripts/validate.py /path/to/.iterate_decisions.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = [
    "Atomic Fixes (Direct)",
    "Architectural Fixes (Approved + Executed)",
    "Architectural Fixes (Deferred to Next Round)",
    "AI Important Decisions",
    "Validation",
]


def validate(path: Path) -> list[str]:
    """返回错误列表；空列表表示校验通过。"""
    errors: list[str] = []

    if not path.exists():
        errors.append(f"File not found: {path}")
        return errors

    content = path.read_text(encoding="utf-8")

    # 检查是否有未解决的 Git 合并冲突标记
    conflict_markers = ["<<<<<<<", "=======", ">>>>>>>"]
    for marker in conflict_markers:
        if marker in content:
            errors.append(f"Unresolved git conflict marker found: {marker}")

    # 检查必要章节
    for section in REQUIRED_SECTIONS:
        if section not in content:
            errors.append(f"Missing section: {section}")

    # 检查每轮是否有标题
    round_headers = re.findall(r"^## Round \d+ — ", content, re.MULTILINE)
    if not round_headers:
        errors.append("No round headers found (expected '## Round N — ...')")

    return errors


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path-to-.iterate_decisions.md>")
        return 1

    target = Path(sys.argv[1])
    errors = validate(target)

    if errors:
        print(f"Validation failed for {target}")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(f"Validation passed: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
