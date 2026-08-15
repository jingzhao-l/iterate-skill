"""Interactive CLI onboarding wizard.

Guides the user through project setup step by step. Uses a pluggable
``input_func`` parameter (defaults to ``builtins.input``) so tests can
inject mock responses without touching stdin.

The wizard uses multi-path branching:
- **First-time** (no ITERATE.md): gate -> basic onboarding -> offer personalization.
- **Returning user** (ITERATE.md exists): offer config update -> offer personalization.

All visual output is routed through the unified TUI layer (``iterate_cli.tui``)
for consistent skills.sh / Claude Code style styling.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

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
from iterate_cli.tui import tui

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

# Maximum number of scanned top-level directories to list in the scan preview.
# Beyond this the output is truncated with a "… and N more" hint.
MAX_DIRS_DISPLAYED = 10

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
) -> OnboardingData | None:
    """Run the interactive CLI onboarding wizard with multi-path branching.

    The flow depends on whether ``ITERATE.md`` already exists:
    - **First-time**: gate question -> basic onboarding -> offer personalization.
    - **Returning user**: offer config update -> offer personalization.

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
) -> OnboardingData | None:
    """Handle first-time onboarding (no ITERATE.md exists)."""
    tui.info("首次 onboarding / First-time onboarding.")
    tui.hint("AI 工具可自动扫描代码库生成基础配置；CLI 适合手动配置 + 个性化约束。")
    tui.empty_line()

    if not _gate_question(input_func):
        return None

    data = _run_basic_wizard(project_root, input_func)
    if data is None:
        return None

    # Offer personalization after basic onboarding.
    tui.empty_line()
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
) -> OnboardingData | None:
    """Handle returning user (ITERATE.md already exists)."""
    tui.info("检测到已有 ITERATE.md / ITERATE.md already exists.")
    tui.empty_line()

    # Ask about updating basic config.
    tui.warning("不建议手动更新基础配置，建议使用 `iterate refresh` 进行增量刷新。")
    tui.hint("Manual update is discouraged; use `iterate refresh` for incremental update.", indent=4)
    tui.empty_line()
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
            tui.warning("无法加载现有配置，转为基础 onboarding / Could not load existing config, falling back to basic.")
            data = _run_basic_wizard(project_root, input_func)
            if data is None:
                return None

    # Ask about personalization.
    tui.empty_line()
    personalize = _ask_yes_no(
        "是否进行个性化配置? 或使用 skill 时遇到问题? / Personalize configuration?",
        input_func,
    )

    if not update_basic and not personalize:
        # User declined both: no changes needed.
        tui.empty_line()
        tui.info("配置未变更。如需更新 AI 维护区，请使用 `iterate refresh`。")
        tui.hint("No changes made. Use `iterate refresh` to update AI-maintained sections.", indent=2)
        return NO_CHANGES_NEEDED

    if personalize:
        from iterate_cli.personalize import (
            load_existing_personalization,
            run_personalize_wizard,
        )
        from iterate_cli.refresh import load_onboarding_config

        existing_config = load_onboarding_config(project_root) or {}
        existing_personalization = load_existing_personalization(project_root, existing_config)

        personalization = run_personalize_wizard(
            project_root,
            input_func,
            existing=existing_personalization,
        )
        if personalization is not None:
            data.personalization = personalization
        elif not update_basic:
            # User declined basic update AND cancelled personalization: nothing to write.
            tui.empty_line()
            tui.info("个性化配置已取消，基础配置未更新。无变更。")
            tui.hint("Personalization cancelled, basic config not updated. No changes.", indent=2)
            return NO_CHANGES_NEEDED

    return data


def _run_basic_wizard(
    project_root: Path,
    input_func: InputFunc,
) -> OnboardingData | None:
    """Run the basic onboarding wizard (tech stack, dimensions, git, etc.)."""
    with tui.status("正在扫描项目 / Scanning project..."):
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


def _load_existing_onboarding_data(project_root: Path) -> OnboardingData | None:
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
            tui.error("iterate.config.yaml not found, cannot load existing config.")
            return None

        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        # Reject non-dict YAML (e.g. ``- item`` or ``just a string``) so
        # that ``config.get(...)`` below does not raise AttributeError.
        if not isinstance(config, dict):
            tui.error(
                f"{config_path} is not a YAML mapping (got {type(config).__name__})."
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
            push_per_round=(config.get("git") or {}).get("push_per_round", False),
            validation_commands=(config.get("validation") or {}).get("commands") or {},
            command_whitelist=(config.get("validation") or {}).get("command_whitelist") or [],
            fingerprints=capture_fingerprints(project_root),
            language=config.get("language", "en"),
        )
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        tui.error(f"Failed to load existing config: {exc}")
        return None


def _print_welcome() -> None:
    """Print the wizard welcome banner."""
    tui.intro(
        "Iterate Skill — Onboarding",
        "项目知识库初始化 / Project Knowledge Base Setup",
    )


def _gate_question(input_func: InputFunc) -> bool:
    """Ask the gate question about project familiarity.

    If the user is not confident, suggests using the AI tool instead.
    Returns True to continue CLI onboarding, False to abort.
    """
    tui.info("本向导将在命令行中收集项目信息以生成 ITERATE.md 和 iterate.config.yaml。")
    tui.empty_line()
    tui.info("CLI 会自动扫描代码库（manifest、目录、技术栈），并让你确认/修正检测结果。")
    tui.hint("The CLI wizard scans your codebase (manifests, directories, tech stack) and lets you confirm or adjust the results.", indent=4)
    tui.empty_line()
    tui.info("如果你对项目的技术栈、模块结构和构建/测试命令有清晰认知，可继续。")
    tui.hint("If you have a clear understanding of your project's tech stack, module structure, and build/test commands, you can continue.", indent=2)
    tui.empty_line()
    tui.info("若你更希望完全由 AI 自动扫描并生成，可在 AI 编程工具中直接调用 /iterate。")
    tui.hint("Alternatively, use /iterate in your AI coding tool for fully automated AI onboarding.", indent=2)
    tui.empty_line()

    # User explicitly ran `iterate onboard`, so default to continue (Y).
    answer = _ask_yes_no(
        "是否继续命令行 onboarding? / Continue CLI onboarding?",
        input_func,
        default=True,
    )
    if not answer:
        tui.empty_line()
        tui.info("建议在 AI 编程工具中调用 /iterate 完成 onboarding。")
        tui.hint("Suggestion: run /iterate in your AI coding tool for AI onboarding.", indent=2)
        tui.empty_line()
        return False
    return True


def _confirm_tech_stack(scan: ScanResult, input_func: InputFunc) -> list[str]:
    """Show detected tech stack and let user confirm or override."""
    tui.section("技术栈 / Tech Stack")

    if scan.detected_languages:
        tui.key_value("语言 / Languages", ", ".join(scan.detected_languages))
        tui.key_value("包管理器 / Pkg managers", ", ".join(scan.detected_package_managers))
        tui.key_value("Manifest 文件 / Manifests", ", ".join(scan.manifests))
        tui.empty_line()
        # Auto-detection is usually correct; default to accepting it (Y).
        if _ask_yes_no("检测结果是否正确? / Is this correct?", input_func, default=True):
            return list(scan.detected_languages)
    else:
        tui.hint("未检测到已知 manifest 文件 / No known manifest files detected.")
        tui.empty_line()

    tui.question("请手动输入主要语言（逗号分隔）/ Enter main languages (comma-separated):")
    raw = input_func("  └ ").strip()
    if not raw:
        return ["Unknown"]
    return [lang.strip() for lang in raw.split(",") if lang.strip()]


def _collect_validation_commands(
    scan: ScanResult,
    input_func: InputFunc,
) -> dict[str, list[str]]:
    """Collect validation commands from the user, with suggestions."""
    tui.section("验证命令 / Validation Commands")
    tui.info("这些命令会在每轮修复后自动执行。请确保它们正确且安全。")
    tui.hint("These commands run automatically after each round. Ensure they are correct and safe.", indent=2)
    tui.empty_line()

    suggested = suggest_validation_commands(scan)
    if suggested:
        tui.info("建议的命令（基于检测到的技术栈）/ Suggested commands:")
        for module, cmds in suggested.items():
            tui.bullet(f"[{module}]", indent=4)
            for cmd in cmds:
                tui.info(f"- {cmd}", indent=6)
        tui.empty_line()

        # Suggested commands are tailored to the detected stack; default to using them (Y).
        if _ask_yes_no("使用这些命令? / Use these commands?", input_func, default=True):
            return suggested

    return _manual_collect_commands(input_func)


def _manual_collect_commands(input_func: InputFunc) -> dict[str, list[str]]:
    """Manually collect validation commands from the user."""
    # Reuse the single authoritative validator (personalize.validate_extra_command)
    # so onboard manual entry and the later personalize flow enforce identical
    # rules: shell-metacharacter blacklist AND known-safe-prefix whitelist.
    from iterate_cli.personalize import (
        MODULE_NAME_PATTERN,
        validate_extra_command,
    )

    tui.info("手动输入验证命令（每行一条，空行结束该模块）/")
    tui.hint("Enter commands manually (one per line, empty line to finish a module)", indent=2)
    tui.empty_line()

    commands: dict[str, list[str]] = {}
    while True:
        module = input_func("  └ 模块名 / Module name (留空结束 / empty to finish): ").strip()
        if not module:
            break
        if not MODULE_NAME_PATTERN.match(module):
            tui.warning(f"模块名只能包含字母、数字、下划线、连字符、点。跳过 '{module}'。", indent=4)
            tui.hint(f"Module name may only contain letters, digits, underscore, dash, dot. Skipping '{module}'.", indent=6)
            continue

        cmds: list[str] = []
        while True:
            cmd = input_func(f"  └ {module} 命令 / command (留空结束 / empty to finish): ").strip()
            if not cmd:
                break
            # Single authoritative validator: rejects shell-chaining
            # metacharacters and non-whitelisted prefixes, so a manually
            # entered command can never smuggle side effects into the
            # executable validation config.
            is_valid, reason = validate_extra_command(cmd)
            if not is_valid:
                tui.warning(f"拒绝命令 / Rejected: '{cmd}' — {reason}", indent=4)
                continue
            cmds.append(cmd)

        if cmds:
            commands[module] = cmds

    return commands


def _collect_dimensions(scan: ScanResult, input_func: InputFunc) -> list[str]:
    """Let the user select review dimensions, with suggested defaults."""
    tui.section("审查维度 / Review Dimensions")

    suggested = suggest_dimensions(scan)
    tui.info(f"推荐维度 / Suggested: {', '.join(suggested)}")
    tui.empty_line()
    tui.info("可用维度 / Available dimensions:")
    items = []
    markers = []
    for dim in ALL_DIMENSIONS:
        items.append(DIMENSION_LABELS[dim])
        markers.append("✓" if dim in suggested else "")
    tui.numbered_list(items, indent=4, markers=markers)

    tui.empty_line()
    tui.question("输入编号选择/取消维度（逗号分隔），直接回车使用推荐项 /")
    tui.hint("Enter numbers to toggle (comma-separated), or press Enter for suggested:", indent=2)
    raw = input_func("  └ ").strip()

    if not raw:
        return suggested

    selected = _parse_dimension_selection(raw)
    if not selected:
        tui.warning("无效输入，使用推荐项 / Invalid input, using suggestions.", indent=4)
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
    tui.section("Git 配置 / Git Configuration")

    target_branch = input_func("  └ 目标分支 / Target branch (默认 main, 留空用 main): ").strip()
    if not target_branch:
        target_branch = "main"

    tui.info("审查范围 / Review scope:")
    tui.numbered_list([
        "full — 全量审查（默认）/ Full review (default)",
        "changed-only — 增量审查 / Changed files only",
    ], indent=4)
    scope_choice = input_func("  └ 选择 / Select (1/2, 默认 1): ").strip()
    if not scope_choice:
        review_scope = "full"
    elif scope_choice == "1":
        review_scope = "full"
    elif scope_choice == "2":
        review_scope = "changed-only"
    else:
        tui.warning(f"无效输入 / Invalid input: {scope_choice!r}，使用默认 full。")
        review_scope = "full"

    push = _ask_yes_no("每轮通过后立即 push? / Push after each round?", input_func, default=False)

    return target_branch, review_scope, push


def _collect_project_info(input_func: InputFunc) -> tuple[str, str]:
    """Collect project description and code conventions."""
    tui.section("项目信息 / Project Info")

    description = input_func("  └ 一句话描述项目 / One-line project description: ").strip()

    tui.info("代码约定（多行，空行结束）/ Code conventions (multi-line, empty line to finish):")
    conv_lines: list[str] = []
    while True:
        line = input_func("  └ ").strip()
        if not line:
            break
        conv_lines.append(line)
    conventions = "\n".join(conv_lines)

    return description, conventions


def _confirm_summary(data: OnboardingData, input_func: InputFunc) -> bool:
    """Show a summary of collected data and ask for confirmation."""
    tui.section("确认 / Confirmation")
    tui.key_value("通道 / Channel", data.channel)
    tui.key_value("语言 / Languages", ", ".join(data.scan.detected_languages) or "N/A")
    tui.key_value("维度 / Dimensions", ", ".join(data.dimensions))
    tui.key_value("目标分支 / Branch", data.target_branch)
    tui.key_value("审查范围 / Scope", data.review_scope)
    tui.key_value("每轮 push / Push", str(data.push_per_round))
    if data.validation_commands:
        tui.info("验证命令 / Validation:", indent=2)
        for module, cmds in data.validation_commands.items():
            for cmd in cmds:
                tui.bullet(f"[{module}] {cmd}", indent=4)
    else:
        tui.key_value("验证命令 / Validation", "(无 / none)")
    if data.fingerprints:
        tui.key_value("指纹 / Fingerprints", f"{len(data.fingerprints)} manifest(s)")
    tui.empty_line()
    tui.hint("将写入 / Will write: ITERATE.md + iterate.config.yaml")
    tui.empty_line()

    return _ask_yes_no("确认生成? / Confirm and generate?", input_func)


def _print_scan_results(scan: ScanResult) -> None:
    """Print a summary of scan results."""
    tui.section("扫描结果 / Scan Results")
    tui.key_value("Manifest", ", ".join(scan.manifests) if scan.manifests else "(无 / none)")
    if scan.detected_languages:
        tui.key_value("Languages", ", ".join(scan.detected_languages))
    if scan.top_level_dirs:
        dirs = scan.top_level_dirs[:MAX_DIRS_DISPLAYED]
        tui.key_value("Directories", ", ".join(dirs))
        if len(scan.top_level_dirs) > MAX_DIRS_DISPLAYED:
            tui.hint(f"... and {len(scan.top_level_dirs) - MAX_DIRS_DISPLAYED} more", indent=4)
    tui.key_value("Specs", "yes" if scan.has_specs else "no")
    tui.key_value("Tests", "yes" if scan.has_tests else "no")
    tui.key_value("CI", "yes" if scan.has_ci else "no")
    tui.key_value("Frontend", "yes" if scan.has_frontend else "no")
    tui.empty_line()


def _print_cancelled() -> None:
    """Print cancellation message."""
    tui.cancel()


def _ask_yes_no(
    question: str,
    input_func: InputFunc,
    default: bool = False,
) -> bool:
    """Ask a yes/no question.

    Uses TUI question marker for the question header and a connector
    line for the input prompt, matching skills.sh / Claude Code style.

    Args:
        question: The question text.
        input_func: Input callable.
        default: Default answer if user presses Enter without typing.

    Returns:
        True for yes, False for no.
    """
    hint = "[Y/n]" if default else "[y/N]"
    if question:
        tui.question(question)
    while True:
        raw = input_func(f"  └ {hint} ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        tui.warning("请输入 y 或 n / Please enter y or n.", indent=4)
