"""Interactive CLI onboarding wizard.

Guides the user through project setup step by step. Uses a pluggable
``input_func`` parameter (defaults to ``builtins.input``) so tests can
inject mock responses without touching stdin.

The wizard uses multi-path branching:
- **First-time** (no ITERATE.md): gate → basic onboarding → offer personalization.
- **Returning user** (ITERATE.md exists): offer config update → offer personalization.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from iterate_cli.fingerprint import capture_fingerprints
from iterate_cli.generator import OnboardingData
from iterate_cli.scan import (
    ScanResult,
    scan_project,
    suggest_command_whitelist,
    suggest_dimensions,
    suggest_validation_commands,
)

# Type alias for the input function used throughout the wizard.
InputFunc = Callable[[str], str]

# Sentinel returned by ``run_wizard`` when a returning user explicitly
# declines all updates (no changes needed). This is distinct from ``None``
# which means the user *cancelled* mid-flow (e.g. started the basic wizard
# then aborted). Callers use this to pick the right exit code: 0 for
# "no changes needed", 1 for "cancelled".
NO_CHANGES_NEEDED: Any = object()

# All selectable dimensions in display order.
ALL_DIMENSIONS: list[str] = [
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

# Dimension display names for the selection menu.
DIMENSION_LABELS: dict[str, str] = {
    "correctness": "正确性 / Correctness (critical)",
    "security": "安全 / Security (critical)",
    "performance": "性能 / Performance (high)",
    "architecture": "架构 / Architecture (high)",
    "style-tests": "风格与测试 / Style & Tests (medium)",
    "tech-debt": "技术债 / Tech Debt (medium)",
    "spec-compliance": "规范一致性 / Spec Compliance (high)",
    "frontend-backend": "前后端一致性 / Frontend-Backend (high)",
    "ui-ux": "UI/UX (medium)",
}


def run_wizard(
    project_root: Path,
    input_func: InputFunc = input,
) -> Optional[OnboardingData]:
    """Run the interactive CLI onboarding wizard with multi-path branching.

    The flow depends on whether ``ITERATE.md`` already exists:
    - **First-time**: gate question → basic onboarding → offer personalization.
    - **Returning user**: offer config update → offer personalization.

    Args:
        project_root: The project root directory to onboard.
        input_func: Callable used to read user input (defaults to ``input``).

    Returns:
        OnboardingData if the user completes the wizard,
        None if the user cancelled mid-flow,
        NO_CHANGES_NEEDED if a returning user explicitly declined all
            updates (no files need to be written).
    """
    _print_welcome()

    iterate_md_exists = (project_root / "ITERATE.md").is_file()

    if not iterate_md_exists:
        return _first_time_flow(project_root, input_func)
    else:
        return _returning_user_flow(project_root, input_func)


def _first_time_flow(
    project_root: Path,
    input_func: InputFunc,
) -> Optional[OnboardingData]:
    """Handle first-time onboarding (no ITERATE.md exists)."""
    print("首次 onboarding / First-time onboarding.")
    print("AI 工具可自动扫描代码库生成基础配置；CLI 适合手动配置 + 个性化约束。")
    print("AI tools can auto-scan; CLI suits manual config + personalization.")
    print()

    if not _gate_question(input_func):
        return None

    data = _run_basic_wizard(project_root, input_func)
    if data is None:
        return None

    # Offer personalization after basic onboarding.
    print()
    if _ask_yes_no(
        "是否有 iterate 场景的个性化要求? / Any personalization requirements?",
        input_func,
    ):
        from iterate_cli.personalize import run_personalize_wizard

        personalization = run_personalize_wizard(project_root, input_func)
        if personalization is not None:
            data.personalization = personalization

    return data


def _returning_user_flow(
    project_root: Path,
    input_func: InputFunc,
) -> Optional[OnboardingData]:
    """Handle returning user (ITERATE.md already exists)."""
    print("检测到已有 ITERATE.md / ITERATE.md already exists.")
    print()

    # Ask about updating basic config.
    print("⚠️  不建议手动更新基础配置，建议使用 `iterate refresh` 进行增量刷新。")
    print("    Manual update is discouraged; use `iterate refresh` for incremental update.")
    print()
    update_basic = _ask_yes_no(
        "是否需要更新基础配置? / Update basic config?",
        input_func,
    )

    if update_basic:
        data = _run_basic_wizard(project_root, input_func)
        if data is None:
            return None
    else:
        # Load existing config to preserve settings.
        data = _load_existing_onboarding_data(project_root)
        if data is None:
            print("无法加载现有配置，转为基础 onboarding / Could not load existing config, falling back to basic.")
            data = _run_basic_wizard(project_root, input_func)
            if data is None:
                return None

    # Ask about personalization.
    print()
    print("是否进行个性化配置? 或使用 skill 时遇到问题? /")
    print("Personalize configuration? Encountered issues during skill usage?")
    personalize = _ask_yes_no("", input_func)

    if not update_basic and not personalize:
        # User declined both: no changes needed.
        print()
        print("配置未变更。如需更新 AI 维护区，请使用 `iterate refresh`。")
        print("No changes made. Use `iterate refresh` to update AI-maintained sections.")
        return NO_CHANGES_NEEDED

    if personalize:
        from iterate_cli.personalize import (
            load_personalization_from_config,
            run_personalize_wizard,
        )
        from iterate_cli.refresh import load_onboarding_config

        existing_config = load_onboarding_config(project_root) or {}
        existing_personalization = load_personalization_from_config(existing_config)

        personalization = run_personalize_wizard(
            project_root,
            input_func,
            existing=existing_personalization,
        )
        if personalization is not None:
            data.personalization = personalization
        elif not update_basic:
            # User declined basic update AND cancelled personalization: nothing to write.
            print()
            print("个性化配置已取消，基础配置未更新。无变更。")
            print("Personalization cancelled, basic config not updated. No changes.")
            return NO_CHANGES_NEEDED

    return data


def _run_basic_wizard(
    project_root: Path,
    input_func: InputFunc,
) -> Optional[OnboardingData]:
    """Run the basic onboarding wizard (tech stack, dimensions, git, etc.)."""
    scan = scan_project(project_root)
    _print_scan_results(scan)

    confirmed_langs = _confirm_tech_stack(scan, input_func)
    validation_commands = _collect_validation_commands(scan, input_func)
    command_whitelist = suggest_command_whitelist(scan)
    dimensions = _collect_dimensions(scan, input_func)
    target_branch, review_scope, push_per_round = _collect_git_config(input_func)
    description, conventions = _collect_project_info(input_func)

    fingerprints = capture_fingerprints(project_root)

    data = OnboardingData(
        project_root=project_root,
        channel="cli",
        scan=scan,
        project_description=description,
        code_conventions=conventions,
        dimensions=dimensions,
        target_branch=target_branch,
        review_scope=review_scope,
        push_per_round=push_per_round,
        validation_commands=validation_commands,
        command_whitelist=command_whitelist,
        fingerprints=fingerprints,
    )

    # Update scan languages in case user confirmed differently.
    scan.detected_languages = confirmed_langs

    if not _confirm_summary(data, input_func):
        _print_cancelled()
        return None

    return data


def _load_existing_onboarding_data(project_root: Path) -> Optional[OnboardingData]:
    """Load existing onboarding data from iterate.config.yaml.

    Reads project description and code conventions from the ``onboarding``
    section of the config (persisted by ``generate_config_yaml``) so that a
    returning user who declines to update basic config does not lose their
    previously entered description/conventions.

    Returns None if config cannot be loaded. Logs errors to stderr
    instead of silently swallowing them.
    """
    try:
        config_path = project_root / "iterate.config.yaml"
        if not config_path.is_file():
            print("⚠️  iterate.config.yaml not found, cannot load existing config.", file=sys.stderr)
            return None

        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        # Reject non-dict YAML (e.g. ``- item`` or ``just a string``) so
        # that ``config.get(...)`` below does not raise AttributeError.
        if not isinstance(config, dict):
            print(
                f"⚠️  {config_path} is not a YAML mapping (got {type(config).__name__}).",
                file=sys.stderr,
            )
            return None
        scan = scan_project(project_root)

        onboarding_section = config.get("onboarding") or {}
        channel = onboarding_section.get("channel", "cli")
        # Read persisted user-entered text from config (not from ITERATE.md
        # user-owned section, which is for manual edits and personalization).
        project_description = str(onboarding_section.get("project_description") or "")
        code_conventions = str(onboarding_section.get("code_conventions") or "")

        return OnboardingData(
            project_root=project_root,
            channel=channel,
            scan=scan,
            project_description=project_description,
            code_conventions=code_conventions,
            dimensions=config.get("dimensions") or [],
            target_branch=(config.get("git") or {}).get("target_branch", "main"),
            review_scope=(config.get("review") or {}).get("scope", "full"),
            push_per_round=(config.get("git") or {}).get("push_per_round", True),
            validation_commands=(config.get("validation") or {}).get("commands") or {},
            command_whitelist=(config.get("validation") or {}).get("command_whitelist") or [],
            fingerprints=capture_fingerprints(project_root),
            language=config.get("language", "en"),
        )
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        print(f"⚠️  Failed to load existing config: {exc}", file=sys.stderr)
        return None


def _print_welcome() -> None:
    """Print the wizard welcome banner."""
    print()
    print("=" * 60)
    print("  Iterate Skill — Onboarding")
    print("  项目知识库初始化 / Project Knowledge Base Setup")
    print("=" * 60)
    print()


def _gate_question(input_func: InputFunc) -> bool:
    """Ask the gate question about project familiarity.

    If the user is not confident, suggests using the AI tool instead.
    Returns True to continue CLI onboarding, False to abort.
    """
    print("本向导将在命令行中收集项目信息以生成 ITERATE.md 和 iterate.config.yaml。")
    print("This wizard collects project info to generate ITERATE.md and iterate.config.yaml.")
    print()
    print("⚠️  命令行向导无法扫描代码库，只能基于你的回答生成配置。")
    print("    The CLI wizard cannot scan your codebase; it only uses your answers.")
    print()
    print("如果你对项目的技术栈、模块结构和构建/测试命令有清晰认知，可继续。")
    print("If you have a clear understanding of your project's tech stack,")
    print("module structure, and build/test commands, you can continue.")
    print()
    print("否则建议在 AI 编程工具中直接调用 /iterate，由 AI 自动扫描代码库完成 onboarding。")
    print("Otherwise, use /iterate in your AI coding tool for automated AI onboarding.")
    print()

    answer = _ask_yes_no("是否继续命令行 onboarding? / Continue CLI onboarding?", input_func)
    if not answer:
        print()
        print("💡 建议在 AI 编程工具中调用 /iterate 完成 onboarding。")
        print("   Suggestion: run /iterate in your AI coding tool for AI onboarding.")
        print()
        return False
    return True


def _confirm_tech_stack(scan: ScanResult, input_func: InputFunc) -> list[str]:
    """Show detected tech stack and let user confirm or override."""
    print()
    print("--- 技术栈 / Tech Stack ---")

    if scan.detected_languages:
        print(f"检测到的语言 / Detected languages: {', '.join(scan.detected_languages)}")
        print(f"检测到的包管理器 / Detected package managers: {', '.join(scan.detected_package_managers)}")
        print(f"Manifest 文件 / Manifest files: {', '.join(scan.manifests)}")
        print()
        if _ask_yes_no("检测结果是否正确? / Is this correct?", input_func):
            return list(scan.detected_languages)
    else:
        print("未检测到已知 manifest 文件 / No known manifest files detected.")
        print()

    print("请手动输入主要语言（逗号分隔）/ Enter main languages (comma-separated):")
    raw = input_func("  > ").strip()
    if not raw:
        return ["Unknown"]
    return [lang.strip() for lang in raw.split(",") if lang.strip()]


def _collect_validation_commands(
    scan: ScanResult,
    input_func: InputFunc,
) -> dict[str, list[str]]:
    """Collect validation commands from the user, with suggestions."""
    print()
    print("--- 验证命令 / Validation Commands ---")
    print("这些命令会在每轮修复后自动执行。请确保它们正确且安全。")
    print("These commands run automatically after each round. Ensure they are correct and safe.")
    print()

    suggested = suggest_validation_commands(scan)
    if suggested:
        print("建议的命令（基于检测到的技术栈）/ Suggested commands (based on detected tech stack):")
        for module, cmds in suggested.items():
            print(f"  [{module}]")
            for cmd in cmds:
                print(f"    - {cmd}")
        print()

        if _ask_yes_no("使用这些命令? / Use these commands?", input_func):
            return suggested

    return _manual_collect_commands(input_func)


def _manual_collect_commands(input_func: InputFunc) -> dict[str, list[str]]:
    """Manually collect validation commands from the user."""
    from iterate_cli.personalize import MODULE_NAME_PATTERN

    print("手动输入验证命令（每行一条，空行结束该模块）/")
    print("Enter commands manually (one per line, empty line to finish a module):")
    print()

    commands: dict[str, list[str]] = {}
    while True:
        module = input_func("模块名 / Module name (如 python, swift, typescript; 留空结束 / empty to finish): ").strip()
        if not module:
            break
        if not MODULE_NAME_PATTERN.match(module):
            print(f"⚠️  模块名只能包含字母、数字、下划线、连字符、点。跳过 '{module}'。")
            print(f"    Module name may only contain letters, digits, underscore, dash, dot. Skipping '{module}'.")
            continue

        cmds: list[str] = []
        while True:
            cmd = input_func(f"  {module} 命令 / command (留空结束 / empty to finish): ").strip()
            if not cmd:
                break
            cmds.append(cmd)

        if cmds:
            commands[module] = cmds

    return commands


def _collect_dimensions(scan: ScanResult, input_func: InputFunc) -> list[str]:
    """Let the user select review dimensions, with suggested defaults."""
    print()
    print("--- 审查维度 / Review Dimensions ---")

    suggested = suggest_dimensions(scan)
    print(f"推荐维度 / Suggested: {', '.join(suggested)}")
    print()
    print("可用维度 / Available dimensions:")
    for i, dim in enumerate(ALL_DIMENSIONS, 1):
        marker = " ✓" if dim in suggested else ""
        print(f"  {i}. {DIMENSION_LABELS[dim]}{marker}")

    print()
    print("输入编号选择/取消维度（逗号分隔），直接回车使用推荐项 /")
    print("Enter numbers to toggle (comma-separated), or press Enter for suggested:")
    raw = input_func("  > ").strip()

    if not raw:
        return suggested

    selected = _parse_dimension_selection(raw)
    if not selected:
        print("无效输入，使用推荐项 / Invalid input, using suggestions.")
        return suggested

    return selected


def _parse_dimension_selection(raw: str) -> list[str]:
    """Parse a comma-separated number string into a dimension list.

    Args:
        raw: User input like "1,2,5,7".

    Returns:
        List of dimension keys (deduplicated, order preserved), or empty
        list if parsing fails.
    """
    nums: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            num = int(part)
        except ValueError:
            return []
        if num < 1 or num > len(ALL_DIMENSIONS):
            return []
        nums.append(num)

    # Deduplicate while preserving order (schema requires uniqueItems).
    seen: set[str] = set()
    result: list[str] = []
    for n in nums:
        dim = ALL_DIMENSIONS[n - 1]
        if dim not in seen:
            seen.add(dim)
            result.append(dim)
    return result


def _collect_git_config(input_func: InputFunc) -> tuple[str, str, bool]:
    """Collect git-related configuration."""
    print()
    print("--- Git 配置 / Git Configuration ---")

    target_branch = input_func("目标分支 / Target branch (默认 main, 留空用 main): ").strip()
    if not target_branch:
        target_branch = "main"

    print("审查范围 / Review scope:")
    print("  1. full — 全量审查（默认）/ Full review (default)")
    print("  2. changed-only — 增量审查 / Changed files only")
    scope_choice = input_func("选择 / Select (1/2, 默认 1): ").strip()
    review_scope = "changed-only" if scope_choice == "2" else "full"

    push = _ask_yes_no("每轮通过后立即 push? / Push after each round?", input_func, default=True)

    return target_branch, review_scope, push


def _collect_project_info(input_func: InputFunc) -> tuple[str, str]:
    """Collect project description and code conventions."""
    print()
    print("--- 项目信息 / Project Info ---")

    description = input_func("一句话描述项目 / One-line project description: ").strip()

    print("代码约定（多行，空行结束）/ Code conventions (multi-line, empty line to finish):")
    conv_lines: list[str] = []
    while True:
        line = input_func("  > ").strip()
        if not line:
            break
        conv_lines.append(line)
    conventions = "\n".join(conv_lines)

    return description, conventions


def _confirm_summary(data: OnboardingData, input_func: InputFunc) -> bool:
    """Show a summary of collected data and ask for confirmation."""
    print()
    print("=" * 60)
    print("  确认 / Confirmation")
    print("=" * 60)
    print()
    print(f"  通道 / Channel:         {data.channel}")
    print(f"  语言 / Languages:       {', '.join(data.scan.detected_languages) or 'N/A'}")
    print(f"  维度 / Dimensions:      {', '.join(data.dimensions)}")
    print(f"  目标分支 / Branch:      {data.target_branch}")
    print(f"  审查范围 / Scope:       {data.review_scope}")
    print(f"  每轮 push / Push:       {data.push_per_round}")
    if data.validation_commands:
        print("  验证命令 / Validation:")
        for module, cmds in data.validation_commands.items():
            for cmd in cmds:
                print(f"    [{module}] {cmd}")
    else:
        print("  验证命令 / Validation:  (无 / none)")
    if data.fingerprints:
        print(f"  指纹 / Fingerprints:    {len(data.fingerprints)} manifest(s)")
    print()
    print("将写入 / Will write: ITERATE.md + iterate.config.yaml")
    print()

    return _ask_yes_no("确认生成? / Confirm and generate?", input_func)


def _print_scan_results(scan: ScanResult) -> None:
    """Print a summary of scan results."""
    print()
    print("--- 扫描结果 / Scan Results ---")
    if scan.manifests:
        print(f"  Manifest: {', '.join(scan.manifests)}")
    else:
        print("  Manifest: (无 / none)")
    if scan.detected_languages:
        print(f"  Languages: {', '.join(scan.detected_languages)}")
    if scan.top_level_dirs:
        print(f"  Directories: {', '.join(scan.top_level_dirs[:10])}")
        if len(scan.top_level_dirs) > 10:
            print(f"    ... and {len(scan.top_level_dirs) - 10} more")
    print(f"  Specs: {'yes' if scan.has_specs else 'no'}")
    print(f"  Tests: {'yes' if scan.has_tests else 'no'}")
    print(f"  CI: {'yes' if scan.has_ci else 'no'}")
    print(f"  Frontend: {'yes' if scan.has_frontend else 'no'}")
    print()


def _print_cancelled() -> None:
    """Print cancellation message."""
    print()
    print("已取消 / Cancelled.")
    print()


def _ask_yes_no(
    question: str,
    input_func: InputFunc,
    default: bool = False,
) -> bool:
    """Ask a yes/no question.

    Args:
        question: The question text.
        input_func: Input callable.
        default: Default answer if user presses Enter without typing.

    Returns:
        True for yes, False for no.
    """
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        raw = input_func(f"{question} {hint} ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("请输入 y 或 n / Please enter y or n.")
