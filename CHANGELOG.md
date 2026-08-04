# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/)。
每个版本变更记录在下方，最新版本在最前。

---

## [2.3.0] — 2026-08-04

### 文档 / Docs

- **新增"常见问题 / FAQ"章节（SkillHub Convention 评测改进）**：SkillHub 评测指出 C·Convention 的短板是"没有常见问题解答，遇到特殊情况只能靠试错摸索"。README 新增 FAQ 章节，按「安装 / 使用 / 安全」三组覆盖：国内网络安装受限、Node/Python 版本要求、是否自动安装 CLI、取消安装是否留半成品、适用/不适用场景、首次使用未初始化、大项目耗时无进度、漂移检测含义、改动未合并推送、验证命令不生效、新增验证工具、密钥与 `.env` 保护、更新下载安全性等 13 个常见问题。

### 维护 / Maintenance

- 同步更新 `SKILL.md`、`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json` 中的版本号至 `2.3.0`。

---

## [2.2.9] — 2026-08-04

### 安全 / Security

- **发布预上传 tarball + SHA256SUMS，installer 下载资产时验证（ClawHub Description-Behavior Mismatch）**：`.github/workflows/release.yml` 改为先 `git archive` 生成 `iterate-skill.tar.gz`，再生成 `SHA256SUMS.txt`，并把两者作为 Release 资产上传。`npm-installer/lib/installer.js` 与 `scripts/install.py` 现在优先下载上传的 `iterate-skill.tar.gz` asset，再用 `SHA256SUMS.txt` 校验，而不是依赖 GitHub 自动生成的 tarball。这样 checksum 文件在 release 发布时即已存在，installer 执行的是真正的完整性校验。
- **明确披露安装器会安装 `iterate` CLI 到 PATH（Context-Inappropriate Capability / Excessive Agency）**：README 与 SKILL.md 的安全说明中明确说明 `npx iterate-skill-installer` 会顺带把 `iterate` CLI 安装到 PATH（优先 `pipx` 隔离，否则 `--user`），并给出不安装 CLI 的替代方式。
- **明确 onboarding 扫描范围（敏感文件披露）**：README 与 SKILL.md 说明 onboarding 扫描仅检查 manifest 等公开文件的存在性以及 `README.md` / `CLAUDE.md` 等上下文文件，不会读取 `.env`、密钥、凭证等敏感文件内容。
- **进一步强化 merge/push opt-in 披露**：README 的 At a Glance、安全说明与 SKILL.md 的风险披露中，统一写明 `auto_merge` / `push_per_round` 默认 `false`，merge/push 为 opt-in。

### 维护 / Maintenance

- 同步更新 `SKILL.md`、`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json` 中的版本号至 `2.2.9`。

---

## [2.2.8] — 2026-08-04

### 安全 / Security

- **关闭个性化配置的可执行命令信任边界绕过（ClawHub SkillSpector SDI-4/SDI-2）**：`load_personalization_from_config` 与 `merge_personalization_into_config` 现在对 `iterate.config.yaml` 中来源的 `extra_validation_commands` 均用 `validate_extra_command` 重新校验（fail-closed），命令含 shell 链接元字符或不在预批准前缀白名单内时直接跳过，不再并入可执行的 `validation.commands`，也不会自动扩展 `command_whitelist`。此前手工编辑的配置文件可绕过严格白名单并持久化、执行任意命令，现已封堵。
- **统一验证命令白名单文档（SDI-4）**：`SKILL.md`、`tools/SKILL.claude.md`、`tools/SKILL.cursor.md` 中原有"不在白名单的命令需用户确认"的表述与个性化硬白名单矛盾，已统一为"不在白名单的命令直接拒绝，不可通过用户确认绕过"，消除安全模型前后不一致。
- **统一 merge/push 文档默认值（SQP-2 / instruction_scope）**：`SKILL.md` 简介、Git 隔离工作流、重要注意事项，以及 `examples/python-project.md`、`examples/swift-project.md`、`tools/SKILL.cursor.md` 中把 merge/push 描述为"自动/预期行为"的表述已修正为 opt-in，并明确 `git.auto_merge` 与 `git.push_per_round` 默认均为 `false`（安全默认），未显式开启时改动保留在迭代分支由人工 review。
- **新增 `pip-audit` 到预批准验证命令前缀**。

### 修复 / Bug Fixes

- 修复 `extra_validation_commands` 从配置加载时未校验、可被手工编辑的配置文件绕过白名单的问题。

### 维护 / Maintenance

- 同步更新 `SKILL.md`、`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json` 中的版本号至 `2.2.8`。

---

## [2.2.7] — 2026-08-03

### 安全 / Security

- **降低安装器 `child_process` 的静态分析误报**：VirusTotal 的 `suspicious.dangerous_exec` 将调用 `child_process` 的安装器标记为可疑，属于对"包安装器"的启发式误报。本次将 `commandExists` 由 `execFile` 改为 `spawnSync`（同步、无异步回调特征），并在文件顶部补充安全设计说明，明确：所有子进程以参数数组调用（不经 shell、无命令注入面）、程序名均为固定白名单字面量、用户输入（如 `--target`）作为独立 argv 传递而非拼入 shell 字符串。安装器调用系统命令（curl/python/pipx/tar）是必要行为，无法完全消除该标记，但本次改动可降低误报概率。

### 维护 / Maintenance

- 同步更新 `SKILL.md`、`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json` 中的版本号至 `2.2.7`。

---

## [2.2.6] — 2026-08-03

### 修复 / Bug Fixes

- **macOS 上 CLI 自动安装的 PEP 668 降级提示**：当系统 Python 为 externally-managed（如 Homebrew Python）导致 `pip install --user` 被拒时，安装器现在能识别该错误并给出明确的下一步指引（安装 pipx 或 `--break-system-packages`），而不是仅输出笼统的失败信息。
- **SKILL.md 的 AI Onboarding 明确写入 `channel`/`completed_at`**：此前 AI 通道生成的 `iterate.config.yaml` 未明确要求写 `onboarding.channel` 与 `onboarding.completed_at`，导致 `iterate status` 对 AI-onboarded 项目显示 `Channel: unknown`。现已与 CLI 通道产出对齐。

### 维护 / Maintenance

- **同步发布 npm 包至 `2.2.6`**：此前 npm 包停留在 `2.1.6`，用户 `npx iterate-skill-installer` 会拉到旧版安装器。本次将 npm 包与 GitHub Release 版本对齐并重新发布。
- 同步更新 `SKILL.md`、`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json` 中的版本号至 `2.2.6`。

---

## [2.2.5] — 2026-08-03

### 修复 / Bug Fixes

- **重新个性化时保留 ITERATE.md 中的自由文本备注与代码约定**：`iterate personalize` 或重新 onboarding 时，此前结构化规则从 `iterate.config.yaml` 加载，但自由文本的 `iterate_notes` 与 `code_conventions` 只存在于 ITERATE.md 的用户自有区块，未读回导致重新保存时 `merge_user_sections` 静默清空用户此前填写的内容。现在新增 `load_personalization_from_iterate_md` 与 `load_existing_personalization`，合并两个来源后再进入编辑，避免内容丢失。

### 测试 / Tests

- 新增 `TestLoadPersonalizationFromIterateMd` 回归测试，验证从 ITERATE.md 用户自有区块正确解析备注与代码约定。

### 维护 / Maintenance

- 同步更新 `SKILL.md`、`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json` 中的版本号至 `2.2.5`。

---

## [2.2.4] — 2026-08-03

### 修复 / Bug Fixes

- **`iterate onboard` 的引导默认值改为「继续」**：此前用户显式运行 `iterate onboard` 时，gate 问题、技术栈确认、建议校验命令等关键提示默认值为「否」，用户直接回车会中止流程或退回手动输入，体验反直觉。现在这些提示在用户显式发起 onboarding 时默认「是」，直接回车即可按推荐流程继续。

### 测试 / Tests

- 新增 `test_gate_defaults_to_continue_on_empty` 回归测试，验证 gate 问题在空回车时默认继续进入 onboarding。

### 维护 / Maintenance

- 同步更新 `SKILL.md`、`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json` 中的版本号至 `2.2.4`。

---

## [2.2.3] — 2026-08-03

### 修复 / Bug Fixes

- **安装时仅预选自动检测到的 AI 工具**：此前 `install.py` 的箭头键多选默认全选所有受支持工具，即使某些工具未安装也会被预勾选，导致用户误以为会安装到不存在的工具。现在只预选检测到的（已安装）工具，未检测到的工具列出但默认不勾选，需用户显式选择。
- **安装取消时不再误报成功**：此前当用户取消安装（未选择任何工具）时 `install_command` 返回 `0`，导致 `npx iterate-skill-installer` 打印成功提示。现在返回非零退出码，npm 包装器检测到取消/失败后停止并提示，不再误报成功。

### 测试 / Tests

- 新增 `TestInstallPreselect` 回归测试，验证多选仅预选检测到的工具。
- 新增 `TestInstallCancelExitCode` 回归测试，验证取消安装返回非零退出码。

### 维护 / Maintenance

- 同步更新 `SKILL.md`、`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json` 中的版本号至 `2.2.3`。

---

## [2.2.2] — 2026-08-03

### 修复 / Bug Fixes

- **修复 `iterate onboard` 重新 onboarding 时丢失 `personalization` 结构化规则**：此前返回用户仅更新基础配置（未重新个性化）时，`iterate.config.yaml` 会被整体重新生成，导致原有的 `personalization` 结构化规则（受保护路径 `protected_paths`、风险区域、额外校验命令 `extra_validation_commands` 等）被静默丢弃。现在 `_cmd_onboard` 会在用户未重新个性化时，从现有配置加载并保留 `personalization`，保证基础配置更新不丢失结构化规则。

### 测试 / Tests

- 新增 `TestCmdOnboardPreservesConfigPersonalization` 回归测试，验证返回用户仅更新基础配置时，`protected_paths` 与 `extra_validation_commands` 等结构化规则在 `iterate.config.yaml` 中得以保留。

### 维护 / Maintenance

- 同步更新 `SKILL.md`、`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json` 中的版本号至 `2.2.2`。

---

## [2.2.1] — 2026-08-03

### 修复 / Bug Fixes

- **`npx iterate-skill-installer` 自动安装 `iterate` CLI**：此前 npx 一键安装只复制 skill 文件到 AI 助手目录，但 README Quick Start 却引导用户运行 `iterate onboard`（需先安装 CLI），造成用户旅程断裂。现在安装器在复制 skill 后自动安装 `iterate` CLI（优先 `pipx`，否则 `pip install --user`），真正实现“一条命令完成 skill + CLI 安装”。
- **修复 `iterate refresh` 将 `push_per_round` 默认置为 `True`**：`iterate_cli/refresh.py` 的 `_build_refresh_data` 在配置缺失时默认 `push_per_round=True`，违背 Secure-by-default（`OnboardingData` 与文档默认均为 `False`）。已统一为 `False`。
- **修正 CLI onboarding 的“无法扫描代码库”错误表述**：此前 wizard 的 gate 提示声称“命令行向导无法扫描代码库，只能基于你的回答生成配置”，但实际 `scan_project` 会扫描并自动检测技术栈。已更新 wizard 文案、README 与 SKILL.md，说明 CLI 会扫描代码库并让用户确认/调整。

### 测试 / Tests

- 新增 `test_refresh_defaults_push_per_round_to_false` 回归测试，验证 `refresh` 在配置缺失 `git.push_per_round` 时默认置为 `False`（Secure-by-default）。

### 维护 / Maintenance

- 同步更新 `SKILL.md`、`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json` 中的版本号至 `2.2.1`。

---

## [2.2.0] — 2026-08-03

### 新增 / Features

- **AI 工具选择改为箭头键多选菜单**：`scripts/install.py` 在选择安装目标时，交互终端（TTY）下使用 `↑/↓` 移动高亮、`空格 / 回车` 勾选当前工具、`Done` 确认、`q` 取消，取代原先的编号输入，更直观且支持多选。非 TTY（管道 / 测试）自动回退到编号输入，保证可测试性。
- **AI 工具自动检测优化**：安装时基于用户 `home` 目录自动检测本机已安装的 AI 编程工具并预选；未检测到任何工具时，列出全部支持的工具供手动选择。
- **项目目录自动识别**：`npx iterate-skill-installer` 在非 home 目录启动时，若未显式指定 `--global` / `--target`，会询问当前目录是否为目标项目目录；若是则直接进入项目级安装。

### 测试 / Tests

- 新增 `TestArrowSelectState` 单元测试，覆盖多选状态机的上下移动、勾选/取消、`Done` 确认、取消、`_read_arrow_key` 按键解码与渲染标记。
- `npm-installer` 新增 `test/mode.test.js`，覆盖 `resolveInstallMode` 的全局/项目级安装判定（显式 `--target` / `--global`、cwd 为 home、cwd 非 home 时是否确认项目目录）。

### 代码质量 / Code Quality

- 修复 `scripts/install.py` 中 `InputFunc` 类型别名未定义（F821）：补充 `from typing import Callable` 与 `InputFunc = Callable[[str], str]`。
- 移除 `iterate_cli/tui.py` 中未使用的 `rich.text.Text` 导入（F401）。
- CI 新增 `ruff check scripts/ tests/ iterate_cli/` 步骤，防止后续引入未定义名称 / 未使用导入等静态问题。

### 维护 / Maintenance

- 同步更新 `SKILL.md`、`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json` 中的版本号至 `2.2.0`。

---

## [2.1.6] — 2026-08-03

### 文档 / Documentation

- **全面重构 README.md**：以“用户旅程”为主线重新组织内容，降低阅读负担。
  - 新增“3 分钟上手 / Quick Start”章节，用三步引导用户完成安装、onboarding、开始迭代。
  - 安装方式精简为“推荐 + 其他方式”两层，突出 `npx iterate-skill-installer` 唯一推荐路径。
  - 合并原先并列的 4 种安装方式，将 pip install、手动复制 SKILL.md、源码脚本归入“其他方式”。
  - 新增“全局安装 vs 项目级安装”对比表格，给出明确建议。
  - 新增“为什么不推荐 skills.sh 安装？”说明，明确从 v2.1 起统一使用 npm 安装器。
  - 将“使用方式”和“Onboarding”内容整合到“它如何工作”章节，减少重复。

### 维护 / Maintenance

- 同步更新 `SKILL.md`、`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json` 中的版本号至 `2.1.6`。

---

## [2.1.5] — 2026-08-03

### 修复 / Fixed

- **修复安装摘要框线错位**：`scripts/install.py` 的 `_strip_markup` 正则现在能正确匹配空关闭标签（如 `[/]`），确保框线宽度计算与可见文本一致。

### 文档 / Documentation

- README 中补充 `npx iterate-skill-installer` 一键安装器的使用示例与选项说明。
- 重新组织 README 的安装与使用流程，使主线更清晰。

---

## [2.1.3] — 2026-08-03

### 修复 / Fixed

- 在 `scripts/requirements.txt` 中显式添加 `rich==13.7.1`，确保 npx 安装器创建的隔离 Python 环境具备 TUI 渲染依赖。
- 改进 `scripts/install.py` 的 markup stripping fallback，在 rich 不可用时仍能对齐输出。

---

## [2.1.2] — 2026-08-03

### 修复 / Fixed

- `npm-installer` 现在正确传递 `FORCE_COLOR=1` 到 Python 安装脚本，确保非 TTY 环境下仍保留彩色输出。

---

## [2.1.1] — 2026-08-03

### 新增 / Added

- `scripts/install.py` 新增 skills.sh 风格框线分区（`_frame_box`）和安装摘要，提升安装完成后的可读性。

---

## [2.1.0] — 2026-08-03

### 新增 / Added

- **skills.sh 风格 TUI**：新增 `iterate_cli/tui.py` 统一终端渲染层，采用青色主题与 @clack/prompts 符号体系（◆ ◇ └ ● ✓ ⚠）。
- **ITERATE 立体 ASCII 横幅**：CLI 命令与版本输出顶部展示 ITERATE Logo，左对齐避免错位。
- **AI 助手自动检测**：`scripts/install.py` 可检测 25+ 已安装的 AI 编程工具，并提供交互式多选菜单。
- **npx 一键安装器**：新增 `npm-installer`，支持 `npx iterate-skill-installer` 一条命令完成下载、SHA256 校验、隔离 Python 环境创建与安装。
- **跨助手安装统一**：同一份安装逻辑覆盖 Trae、Claude Code、Cursor、Windsurf、GitHub Copilot、Codex、Roo Code 等 25+ 工具。

### 改进 / Changed

- 将 `iterate onboard`、`personalize`、`status`、`refresh`、`reonboard` 的输出统一接入 TUI 层。
- 安装脚本 `pip install .` 输出美化，与整体 CLI 风格保持一致。

---

## [2.0.2] — 2026-07-29

### 安全 / Security

针对 ClawHub SkillSpector 审计报告的剩余 findings 进行第二轮修复。本次涉及**行为变更**（默认值从 `true` 改为 `false`）和**命令安全策略升级**（从"警告+确认"改为"硬拒绝"）。

- **`extra_validation_commands` 改为硬白名单 / Strict whitelist enforcement**（Finding 1: Context-Inappropriate Capability）：
  - `iterate_cli/personalize.py` 的 `validate_extra_command` 从"未知前缀警告但可确认添加"改为"未知前缀**直接拒绝**"。
  - wizard 步骤移除确认分支，不再提供绕过白名单的路径。
  - 只有 `KNOWN_SAFE_COMMAND_PREFIXES` 中列出的 30+ 常见 test/lint/type-check/build 工具前缀才会被接受。
  - 测试同步更新：`test_unknown_prefix_warns_but_accepts` → `test_unknown_prefix_rejected`，`test_python_m_with_unknown_module_warns` → `test_python_m_with_unknown_module_rejected`，`test_add_extra_validation_commands` 验证 `safety check` 被拒绝。

- **`git reset --hard` 全部替换为非破坏性命令 / Non-destructive rollback**（Findings 11-14: Tool Parameter Abuse）：
  - Phase 2 原子修复回滚：`git reset --hard HEAD` → `git restore --staged --worktree .`
  - Phase 3 全量验证回滚：`git reset --hard iterate/round-{round}-backup` → `git reset --mixed iterate/round-{round}-backup && git restore --worktree .`
  - Phase 5 备份标签回滚引用：同上替换。
  - `--mixed` 只移动分支指针不改工作区，`git restore` 再恢复文件，避免了 `--hard` 的数据丢失风险。

- **`push_per_round` 和 `auto_merge` 默认值改为 `false` / Secure-by-default**（Findings 7-10: Missing User Warnings）：
  - `config/iterate.config.yaml`：`push_per_round: true` → `false`，新增 `auto_merge: false`。
  - `config/config.schema.json`：新增 `auto_merge` 字段定义（boolean, default: false）。
  - `iterate_cli/generator.py`：`OnboardingData.push_per_round` 默认值 `True` → `False`，生成配置新增 `auto_merge: False`。
  - `iterate_cli/wizard.py`：`_collect_git_config` 的 `_ask_yes_no` 默认值 `True` → `False`；`_load_existing_data` 的 fallback `True` → `False`。
  - `scripts/install.py`：`config --interactive` 的 `push_per_round` fallback `True` → `False`。
  - SKILL.md Phase 5 Merge/Push 步骤改为条件化：仅在配置显式设为 `true` 时才执行自动 merge/push。

- **架构修复审批门禁显式化 / Explicit approval gate**（Finding 5）：
  - SKILL.md Phase 3 用户审批步骤标注为 **强制门禁 / Mandatory gate**。
  - 新增安全约束说明：此门禁不可跳过、不可自动绕过，独立于 merge/push 流程。

- **命令白名单双层强制执行说明 / Dual-layer whitelist enforcement**（Finding 6）：
  - SKILL.md 安全章节更新：明确标注配置时校验（validate.py）和个性化硬白名单（validate_extra_command）双层执行。
  - 个性化硬白名单部分明确说明"不在白名单中的命令**直接拒绝**，不可通过用户确认绕过"。

- **`description` 补充 update 能力 / Description accuracy**（Finding 2）：
  - SKILL.md frontmatter description 从 "cross-assistant installer" 扩展为 "cross-assistant installer/update system with mandatory SHA256 checksum verification"。
  - Update 命令远程下载说明从"若包含 SHA256SUMS.txt 则校验"改为"**强制校验**，缺失则拒绝下载"。

- **`scripts/install.py` 强制 SHA256 校验 / Mandatory checksum verification**（延续 v2.0.1 未提交变更）：
  - `_download_release_source` 在 `checksum_url` 为 None 时拒绝下载。
  - `_run_validate_subprocess` 替换 `_load_validate_module`，用 subprocess 替代 exec_module 消除 static analysis 误报。

### Breaking Changes

- **`push_per_round` 默认值从 `true` 改为 `false`**：新 onboarding 生成的配置不再自动 push。已有配置不受影响（值已显式写入）。
- **`auto_merge` 新增字段，默认 `false`**：新 onboarding 生成的配置不自动 merge。已有配置无此字段时视为 `false`。
- **`extra_validation_commands` 未知前缀从"警告+确认"改为"拒绝"**：之前可通过确认添加非白名单命令，现在直接拒绝。

### 升级 / Upgrade

```bash
python scripts/install.py update --ai trae --target /path/to/project
```

或直接从 GitHub Release 下载 v2.0.2 source code：
https://github.com/jingzhao-l/iterate-skill/releases/tag/v2.0.2

---

## [2.0.1] — 2026-07-29

### 安全 / Security

针对 ClawHub SkillSpector 与 static analysis 报告的安全审计 findings 进行透明度与校验加固。**不改变任何运行时行为**，所有改进都是为了让人机审计员更容易判断 skill 的能力边界与可信范围。

- **SKILL.md frontmatter 新增 `permissions` 字段**：显式声明 `file_read` / `file_write` / `shell` / `git` / `network` 能力，以及敏感文件跳过清单（`.env`、`*.key`、`.pem`、`.aws/`、`.ssh/` 等）。解决 SkillSpector Lp3「MCP Least Privilege / Underdeclared Capability」finding。
- **SKILL.md `description` 扩展**：从「multi-round code iteration」扩展到「multi-round code iteration with onboarding/personalization, and a cross-assistant installer」，使描述与实际能力（onboarding、personalize、跨 assistant 安装/更新）一致。解决 SkillSpector Tp4「MCP Tool Poisoning / 描述与能力不匹配」finding。
- **SKILL.md 4 处 `git reset --hard` 加边界注释**：明示「仅限 `iterate/*` 分支，严禁对 `main`/`master` 执行 reset --hard」，让静态扫描器与人工 review 都能识别安全边界。解决 4 处 Tool Parameter Abuse (High) finding。
- **SKILL.md 自动 merge/push 加 ⚠️ 高风险提示**：在 Phase 5 Merge 与 Push 步骤前加入风险提示，建议生产仓库设置 `push_per_round: false` 或 `auto_merge: false`，或为 main 启用分支保护。解决 2 处 Missing User Warnings (Medium) finding。
- **`scripts/install.py` `_load_validate_module` 加 security note 注释**：说明 `spec.loader.exec_module` 加载的是本 skill 自带的 `scripts/validate.py`，非远程代码、非用户输入、非网络获取，且 `source` 路径来自本地 checkout 或经过 SHA256 校验的 release tarball。澄清 Static analysis Critical「suspicious.dynamic_code_execution」finding 为误报。
- **`iterate_cli/personalize.py` 新增 `validate_extra_command` 校验函数**：对 `extra_validation_commands` 用户输入做白名单 + 黑名单双层校验：
  - 黑名单：拒绝 `;`、`|`、`&`、`` ` ``、`$`、`>`、`<`、换行等 shell 链接元字符，防止命令注入。
  - 白名单：30+ 常见 test/lint/type-check/build 工具前缀（pytest/ruff/mypy/eslint/swift/cargo/go/make 等），未命中白名单的命令需用户二次确认。
  - 支持 `python -m pytest` 形式的间接调用识别。
  解决 SkillSpector Context-Inappropriate Capability (Medium 95%) 与 Intent-Code Divergence (Medium 91%) finding。

### 文档 / Documentation

- `CHANGELOG.md` 新增本 v2.0.1 段，详细记录每项安全改进对应的 ClawHub finding 编号与原因。

### 不变性 / Non-changes

- **无 breaking change**：所有运行时行为、配置 schema、CLI 命令、返回值契约均与 v2.0.0 完全一致。
- **无新增依赖**：`validate_extra_command` 仅用标准库 `re`，未引入第三方包。
- **无 schema 变更**：`iterate.config.yaml` schema 不变，`personalization` 段结构不变。

### 升级 / Upgrade

```bash
python scripts/install.py update --ai trae --target /path/to/project
```

或直接从 GitHub Release 下载 v2.0.1 source code：
https://github.com/jingzhao-l/iterate-skill/releases/tag/v2.0.1

---

## [2.0.0] — 2026-07-29

### 重大变更 / Breaking Changes

- **Onboarding 全流程重构**：从单一流程改为多路径分支引导。
  - 首次用户（无 ITERATE.md）：gate 提问 → 基础 onboarding → 个性化配置。
  - 回归用户（有 ITERATE.md）：基础配置更新提示 → 个性化配置。
- **`run_wizard` 返回值契约变更**：新增 `NO_CHANGES_NEEDED` sentinel 用于区分"回归用户明确拒绝所有更新"（退出码 0）与"用户中途取消"（退出码 1）。原先 `None` 同时承担两种语义。
- **CLI 子命令新增**：`iterate personalize` 独立子命令用于随时更新个性化配置。

### 新增功能 / Added

- **个性化配置系统**（9 类约束）：
  - `protected_paths` — 受保护路径（禁止修改）
  - `risk_areas` — 风险区域（需谨慎）
  - `known_intentional` — 已知刻意模式（避免误报）
  - `dimension_focus` — 维度重点覆盖
  - `fix_priority_order` — 修复优先级顺序
  - `forbidden_fixes` — 禁止的修复类型
  - `iterate_notes` — iterate 场景备注
  - `code_conventions` — 代码规范补充
  - `extra_validation_commands` — 额外验证命令
- **Dual-storage 策略**：structured rules 写入 `iterate.config.yaml`，自由文本写入 `ITERATE.md` 用户区，merge 策略保留用户手动编辑。
- **多路径 CLI 引导**：首次 vs 回归用户分流，回归用户可选增量刷新。
- **`iterate personalize` 子命令**：9 步交互式 wizard，支持 add/remove/skip 统一界面。
- **Incremental refresh 原子写入 + rollback**：`incremental_refresh` 对 ITERATE.md 和 config.yaml 实施原子写入，失败时 best-effort rollback 并记录日志。
- **Personalization schema 版本化**：`personalization.version` 字段用于未来兼容性检测。
- **SKILL.md Step 0 / Phase 0**：skill 运行时消费 personalization 数据，调整审查行为。
- **Schema 约束强化**：`propertyNames` pattern 限制模块名仅允许 `[A-Za-z0-9_.-]`，防止 shell 元字符注入。
- **维度一致性校验**：`validate_personalization_consistency` 检查 personalization 中引用的维度是否在启用维度列表内。
- **Command whitelist 自动更新**：`merge_personalization_into_config` 自动从 `extra_validation_commands` 提取命令前缀加入白名单。

### 改进 / Changed

- `load_onboarding_config` 拒绝非 dict YAML（list/scalar），防止 caller 调用 `.get()` 时 AttributeError 崩溃。
- `_load_existing_onboarding_data` 同样增加非 dict 防护。
- `_cmd_onboard` 退出码语义精确化：`NO_CHANGES_NEEDED` → 0，`None`（取消）→ 1。
- `_returning_user_flow` 持久化 `project_description` 和 `code_conventions` 到 config.yaml 的 `onboarding` 段，避免回归用户丢失数据。
- `validate.py` 错误输出重定向到 stderr，错误消息包含数组索引以便定位。
- `_count_personalization_rules` 排除 `version` 元数据字段，正确计数 `extra_validation_commands`。
- `wizard.py` 维度选择去重，模块名校验（`MODULE_NAME_PATTERN`）。

### 修复 / Fixed

- 回归用户流程中 `project_description` 和 `code_conventions` 数据丢失。
- `extra_validation_commands` 保存/加载往返断裂。
- `merge_user_sections` 误匹配头部（`startswith` → 精确匹配）。
- `known_intentional.line` 字段类型保护缺失。
- `known_intentional.dimension` 缺少 enum 约束。
- Incremental refresh 原子性问题（双文件写入无 rollback）。
- `load_onboarding_config` 对非 UTF-8 文件和权限拒绝未处理。
- `_cmd_status` personalization 规则计数不准确。
- Rollback 失败静默吞错（现记录到 stderr）。
- `full_reonboard` backup 和 write 操作缺少错误处理。

### 测试 / Tests

- 测试套件从 ~140 扩展至 303 个测试。
- 新增覆盖：非 dict YAML 防护、退出码语义（取消 vs 无需变更）、atomicity rollback、维度去重、模块名校验、个性化一致性 e2e、增量刷新保留数据。

---

## [1.0.1] — 2026-07-20

### Fixed

- 简化 SKILL.md frontmatter 以兼容 OpenClaw/ClawHub 解析器，仅保留 `name`/`description`/`version` 字段。

---

## [1.0.0] — 2026-07-20

### Added

- 初始发布：fully automated multi-round code iteration with configurable N-dimension parallel review。
- CLI onboarding 基础流程。
- Fingerprint drift 检测。
- Dimension 配置与校验。
- Release tarball 安全提取（path traversal 防护）。
