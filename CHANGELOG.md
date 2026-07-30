# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/)。
每个版本变更记录在下方，最新版本在最前。

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
