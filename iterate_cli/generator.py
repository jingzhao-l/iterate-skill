"""Onboarding output generator.

Renders ITERATE.md (project knowledge base) and iterate.config.yaml (project-level
overrides) from onboarding data. Supports incremental refresh by preserving
user-owned sections from an existing ITERATE.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from iterate_cli import __version__ as SKILL_VERSION
from iterate_cli.fingerprint import (
    FINGERPRINT_VERSION,
    FingerprintEntry,
    fingerprints_to_dict,
)
from iterate_cli.scan import ScanResult

# Partition markers in ITERATE.md.
AI_START_MARKER = "<!-- ITERATE:AI-MAINTAINED:START -->"
AI_END_MARKER = "<!-- ITERATE:AI-MAINTAINED:END -->"
USER_START_MARKER = "<!-- ITERATE:USER-OWNED:START -->"
USER_END_MARKER = "<!-- ITERATE:USER-OWNED:END -->"

# Default user-owned section content when generating a fresh ITERATE.md.
DEFAULT_USER_OWNED_SECTION = """
## 自定义代码约定 / Custom Code Conventions

<!-- 在此添加你的项目特有的代码约定。刷新 onboarding 时本区内容会保留。 -->
<!-- Add your project-specific code conventions here. This section is preserved during refresh. -->

## 禁区与风险区 / Restricted & Risk Areas

<!-- 标记不可修改的文件、敏感目录、已知风险区。 -->
<!-- Mark files/dirs that should not be modified, sensitive areas, known risks. -->

## 手动批注 / Manual Annotations

<!-- 任何你想让 iterate 知道的额外信息。 -->
<!-- Any additional information you want iterate to know. -->
"""

# Template path relative to the repo root (this file is in iterate_cli/).
TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "ITERATE.template.md"


@dataclass
class OnboardingData:
    """All data needed to generate onboarding outputs."""

    project_root: Path
    channel: str  # "cli" or "ai"
    scan: ScanResult
    project_description: str = ""
    code_conventions: str = ""
    dimensions: list[str] = field(default_factory=list)
    target_branch: str = "main"
    review_scope: str = "full"
    push_per_round: bool = True
    validation_commands: dict[str, list[str]] = field(default_factory=dict)
    command_whitelist: list[str] = field(default_factory=list)
    fingerprints: list[FingerprintEntry] = field(default_factory=list)
    iterate_notes: str = ""
    language: str = "en"

    def completed_at(self) -> str:
        """ISO 8601 timestamp of onboarding completion."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_iterate_md(data: OnboardingData) -> str:
    """Render the ITERATE.md content from onboarding data and template.

    Args:
        data: OnboardingData with scan results and user inputs.

    Returns:
        Complete ITERATE.md file content as a string.

    Raises:
        FileNotFoundError: If the template file is missing.
    """
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    replacements: dict[str, str] = {
        "{{COMPLETED_AT}}": data.completed_at(),
        "{{CHANNEL}}": data.channel,
        "{{SKILL_VERSION}}": SKILL_VERSION,
        "{{FINGERPRINT_VERSION}}": FINGERPRINT_VERSION,
        "{{PROJECT_ROOT}}": str(data.project_root),
        "{{PROJECT_OVERVIEW}}": _render_project_overview(data),
        "{{TECH_STACK}}": _render_tech_stack(data),
        "{{MODULE_MAP}}": _render_module_map(data),
        "{{RECOMMENDED_DIMENSIONS}}": _render_dimensions(data),
        "{{ITERATE_NOTES}}": _render_iterate_notes(data),
    }

    content = template
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)

    return content


def generate_config_yaml(data: OnboardingData) -> str:
    """Render the iterate.config.yaml content with onboarding section.

    Args:
        data: OnboardingData with scan results and user inputs.

    Returns:
        Complete iterate.config.yaml file content as a string.
    """
    config: dict[str, Any] = {
        "goal": "Improve code quality and maintainability",
        "max_rounds": 7,
        "language": data.language,
        "dimensions": data.dimensions,
        "review": {"scope": data.review_scope},
        "atomic": {"max_lines": 20, "max_adjacent_methods": 3},
        "git": {
            "target_branch": data.target_branch,
            "use_worktree": False,
            "push_per_round": data.push_per_round,
        },
        "validation": {
            "command_whitelist": data.command_whitelist,
            "commands": data.validation_commands,
        },
        "reviewer": {"output_schema_validation": True},
        "onboarding": {
            "version": FINGERPRINT_VERSION,
            "completed_at": data.completed_at(),
            "channel": data.channel,
            "skill_version": SKILL_VERSION,
            "drift_check": True,
            "fingerprints": fingerprints_to_dict(data.fingerprints),
        },
    }

    return yaml.safe_dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)


def write_onboarding_outputs(
    data: OnboardingData,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Write ITERATE.md and iterate.config.yaml to the output directory.

    Args:
        data: OnboardingData with scan results and user inputs.
        output_dir: Directory to write files to (usually the project root).

    Returns:
        Tuple of (iterate_md_path, config_yaml_path).

    Raises:
        OSError: If files cannot be written.
    """
    iterate_md_path = output_dir / "ITERATE.md"
    config_path = output_dir / "iterate.config.yaml"

    iterate_md_path.write_text(generate_iterate_md(data), encoding="utf-8")
    config_path.write_text(generate_config_yaml(data), encoding="utf-8")

    return iterate_md_path, config_path


def extract_user_owned_section(existing_md: str) -> str:
    """Extract the user-owned section content from an existing ITERATE.md.

    Args:
        existing_md: The full content of an existing ITERATE.md file.

    Returns:
        The user-owned section content (without the marker comments).
        If markers are not found, returns the default user-owned section.
    """
    start_idx = existing_md.find(USER_START_MARKER)
    end_idx = existing_md.find(USER_END_MARKER)

    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        return DEFAULT_USER_OWNED_SECTION

    # Extract content between markers (after the start marker line).
    after_start = existing_md[start_idx + len(USER_START_MARKER):]
    end_in_after = after_start.find(USER_END_MARKER)
    if end_in_after == -1:
        return DEFAULT_USER_OWNED_SECTION

    return after_start[:end_in_after].strip("\n")


def generate_refreshed_md(data: OnboardingData, existing_md: str) -> str:
    """Generate a refreshed ITERATE.md, preserving user-owned sections.

    This is used for incremental refresh: the AI-maintained sections are
    regenerated from new scan data, while user-owned sections are kept
    exactly as the user left them.

    Args:
        data: Updated OnboardingData with fresh scan results.
        existing_md: The existing ITERATE.md content to preserve user sections from.

    Returns:
        Complete refreshed ITERATE.md content.
    """
    # Generate fresh content with default user section.
    fresh = generate_iterate_md(data)

    # Extract user-owned content from the existing file.
    user_content = extract_user_owned_section(existing_md)

    # Replace the default user section with the preserved content.
    start_idx = fresh.find(USER_START_MARKER)
    end_idx = fresh.find(USER_END_MARKER)

    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        return fresh

    before = fresh[: start_idx + len(USER_START_MARKER)]
    after = fresh[end_idx:]

    return f"{before}\n{user_content}\n{after}"


def _render_project_overview(data: OnboardingData) -> str:
    """Render the project overview section."""
    lines: list[str] = []

    if data.project_description:
        lines.append(data.project_description)
    elif data.scan.detected_languages:
        langs = ", ".join(data.scan.detected_languages)
        lines.append(f"项目使用 {langs} 开发。")
        lines.append(f"Project developed with {langs}.")
    else:
        lines.append("（待补充 / To be filled）")
        lines.append("Project description not yet provided.")

    if data.code_conventions:
        lines.append("")
        lines.append("### 代码约定 / Code Conventions")
        lines.append("")
        lines.append(data.code_conventions)

    return "\n".join(lines)


def _render_tech_stack(data: OnboardingData) -> str:
    """Render the tech stack section."""
    scan = data.scan
    lines: list[str] = []

    if scan.detected_languages:
        lines.append("**语言 / Languages:** " + ", ".join(scan.detected_languages))
    else:
        lines.append("**语言 / Languages:** 未检测到 / None detected")

    if scan.detected_package_managers:
        lines.append("**包管理器 / Package Managers:** " + ", ".join(scan.detected_package_managers))

    if scan.manifests:
        lines.append("")
        lines.append("**Manifest 文件 / Manifest Files:**")
        for m in scan.manifests:
            lines.append(f"- `{m}`")

    if scan.has_ci:
        lines.append("")
        lines.append("**CI/CD:** 已配置 / Configured")
    else:
        lines.append("")
        lines.append("**CI/CD:** 未检测到 / Not detected")

    return "\n".join(lines)


def _render_module_map(data: OnboardingData) -> str:
    """Render the module map section."""
    scan = data.scan
    lines: list[str] = []

    if not scan.top_level_dirs:
        lines.append("（未检测到顶层目录 / No top-level directories detected）")
        return "\n".join(lines)

    lines.append("| 目录 / Directory | 用途 / Purpose |")
    lines.append("|---|---|")

    for d in scan.top_level_dirs:
        purpose = _guess_dir_purpose(d, scan)
        lines.append(f"| `{d}/` | {purpose} |")

    if scan.has_specs:
        lines.append("")
        lines.append("**规范目录 / Specs:** 已检测到 / Detected")
    if scan.has_tests:
        lines.append("")
        lines.append("**测试目录 / Tests:** 已检测到 / Detected")

    return "\n".join(lines)


def _guess_dir_purpose(dir_name: str, scan: ScanResult) -> str:
    """Guess the purpose of a top-level directory by name."""
    purpose_map = {
        "src": "源码 / Source code",
        "lib": "库代码 / Library code",
        "app": "应用入口 / Application entry",
        "api": "API 层 / API layer",
        "routes": "路由 / Routes",
        "controllers": "控制器 / Controllers",
        "handlers": "请求处理 / Request handlers",
        "server": "服务端 / Server",
        "tests": "测试 / Tests",
        "test": "测试 / Tests",
        "docs": "文档 / Documentation",
        "config": "配置 / Configuration",
        "scripts": "脚本 / Scripts",
        "tools": "工具 / Tools",
        "assets": "静态资源 / Static assets",
        "public": "公共资源 / Public assets",
        "static": "静态文件 / Static files",
        "templates": "模板 / Templates",
        "migrations": "数据库迁移 / Database migrations",
        "locales": "国际化 / Internationalization",
        "vendor": "第三方依赖 / Third-party",
        "cmd": "命令行入口 / CLI entry",
        "internal": "内部包 / Internal packages",
        "pkg": "公开包 / Public packages",
    }
    return purpose_map.get(dir_name, "其他 / Other")


def _render_dimensions(data: OnboardingData) -> str:
    """Render the recommended dimensions section."""
    if not data.dimensions:
        return "（未配置 / Not configured）"

    lines: list[str] = []
    lines.append("以下维度已启用（可在 `iterate.config.yaml` 中调整）：")
    lines.append("The following dimensions are enabled (adjustable in `iterate.config.yaml`):")
    lines.append("")

    priority_map = {
        "correctness": "critical",
        "security": "critical",
        "performance": "high",
        "architecture": "high",
        "spec-compliance": "high",
        "frontend-backend": "high",
        "style-tests": "medium",
        "tech-debt": "medium",
        "ui-ux": "medium",
    }

    for dim in data.dimensions:
        priority = priority_map.get(dim, "medium")
        lines.append(f"- `{dim}` (priority: {priority})")

    return "\n".join(lines)


def _render_iterate_notes(data: OnboardingData) -> str:
    """Render the iterate notes section."""
    notes: list[str] = []

    # Always include base notes.
    notes.append("### 通用 / General")
    notes.append("- 审查时跳过自动生成文件（dist/, build/, *.generated.*）。")
    notes.append("- 不要修改锁文件（package-lock.json, poetry.lock, Cargo.lock 等）。")
    notes.append("- 每轮修复后运行 validation.commands，失败即回滚。")
    notes.append("")

    # Add tech-stack-specific notes.
    for lang in data.scan.detected_languages:
        if lang == "Python":
            notes.append("### Python")
            notes.append("- `__init__.py` 导出变更可能影响下游模块。")
            notes.append("- 类型注解缺失不应视为原子问题。")
            notes.append("- dataclass / pydantic 字段变更属于架构问题。")
            notes.append("")
        elif lang in ("JavaScript/TypeScript", "TypeScript"):
            notes.append("### JavaScript / TypeScript")
            notes.append("- API 路由变更属于架构问题。")
            notes.append("- 组件 props 变更属于架构问题。")
            notes.append("- `any` 类型修复应结合上下文，不可盲目收窄。")
            notes.append("")
        elif lang == "Swift":
            notes.append("### Swift")
            notes.append("- `Sendable` / `@MainActor` 标注变更属于架构问题。")
            notes.append("- SwiftUI View 属性变更可能破坏调用方。")
            notes.append("- 避免修改 `*.xcodeproj` 文件。")
            notes.append("")
        elif lang == "Go":
            notes.append("### Go")
            notes.append("- 接口方法变更属于架构问题。")
            notes.append("- goroutine 泄漏是 correctness 维度重点。")
            notes.append("- `init()` 副作用变更需特别关注。")
            notes.append("")
        elif lang == "Rust":
            notes.append("### Rust")
            notes.append("- `unsafe` 块变更属于架构问题。")
            notes.append("- trait 实现变更属于架构问题。")
            notes.append("- 所有权/生命周期变更属于架构问题。")
            notes.append("")

    # Add user-provided notes if any.
    if data.iterate_notes:
        notes.append("### 用户自定义注意点 / User Custom Notes")
        notes.append(data.iterate_notes)

    return "\n".join(notes)
