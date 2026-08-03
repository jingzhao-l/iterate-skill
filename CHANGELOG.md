# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/)。
每个版本变更记录在下方，最新版本在最前。

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
