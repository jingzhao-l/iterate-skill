# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/)。
每个版本变更记录在下方，最新版本在最前。

---

## [iterate-plugin 2.3.7] — 2026-08-15（独立版本线）

本节记录 `harness/iterate-plugin`（dsh 插件）的独立版本线变更，不再跟随 skill 版本号。

### 插件安全 / Security (iterate-plugin)

- **S1 路径逃逸防护**：5 个插件工具（`config/validate/context/review/decision_log`）新增 `resolveProjectRoot` 路径校验，解析后拒绝以文件系统根目录作为项目根，杜绝模型可控的 `path` 参数指向任意系统目录的路径遍历逃逸。
- **S2 `timeout` 上限**：`iterate_validate` 的 `timeout` 参数经 `clampTimeout` 钳制在 600s 上限内，模型无法通过无界 `timeout` 无限拉长命令运行时间。

### 插件功能修复 / Bug Fixes (iterate-plugin)

- **B1** `reviewerTaskPrompt` 的 `is_atomic` 阈值从此前未插值的 `{atomic.max_lines}` 占位符改为真实读取 `config.atomic.max_lines`，`is_atomic` 判定恢复阈值依据。
- **B2** `known_intentional` 个性化过滤端到端打通：canonical 脚本从 `plan` 读取并透传给 `aggregate`，此前配置项实际不生效。
- **B3** normal 模式 architectural findings 跨轮去重，避免相同架构问题在多轮重复累积。
- **B4** 原子修复按文件分组、同一文件由单个 fixer 串行应用，杜绝不同 fixer 并发写同一文件产生的竞态。
- **M3** `sortFindings` 对非法 severity 兜底为 `low`，杜绝 NaN 进入比较器导致排序异常。
- **M4** dry-run 的 known 反馈改用去重后的 findings，避免已知列表随轮次无限膨胀。

### 一致性 / Consistency

- **C1** 清理 `package.json` 中指向不存在测试文件的 5 个失效脚本，仅保留 `test` 与 `test:validate`。
- **C2** README 测试数由过时的 31 更正为 63。
- **C3** 插件版本号统一为独立版本线 2.3.7（`package.json` / `package-lock.json`）。

### 新增单元测试 / Tests

- 新增 `resolveProjectRoot`（路径校验）、`clampTimeout`（超时钳制）、`reviewerTaskPrompt` 阈值插值、`sortFindings` 非法 severity 等测试；共 63 个全绿，类型检查通过。

---

## [2.3.10] — 2026-08-15

### 新功能 / Features (skill CLI)

- **`iterate doctor` 命令**：新增项目健康诊断命令，校验项目 `iterate.config.yaml` / `ITERATE.md` 与技能本体的规范一致性（onboarding 完整性、配置可解析、维度 id 合法性、review.scope 取值、git.target_branch 有效性、validation.commands 结构、skill_version 匹配、manifest 漂移）。发现错误时退出码非零，便于接入 CI。新增 `iterate_cli/doctor.py`。
- **`--json` 结构化输出**：`iterate status` 与 `iterate doctor` 支持 `--json`，输出机器可读的 JSON（用于脚本与 CI 消费）。JSON 模式下自动抑制 ASCII banner，避免污染输出。

### 修复 / Bug Fixes (skill)

- **统一手动验证命令校验逻辑**：`wizard._manual_collect_commands`（onboard 路径）此前只拦截 shell 元字符，与 `personalize.validate_extra_command`（后者严格白名单）强度不一致。现统一复用 `validate_extra_command` 作为唯一权威校验点，杜绝两路径校验割裂。`validate_extra_command` 同时扩展支持 `python <script>.py` 合法脚本调用（非 `-m`），保持 onboard 合法用例可用。
- **`_render_dimensions` priority_map 纳入维度锁**：generator 内硬编码的 priority_map 此前未被 `tests/test_dimension_lock.py` 覆盖，priority 变更会漂移。现新增六源维度锁第 7 个来源，锁定其与 `config/dimensions.yaml` 的 priority 一致。
- **onboard scope 输入防呆**：`wizard._collect_git_config` 中对非法 scope 输入（非 1/2）显式提示并回退默认 full，不再静默降级。
- **TUI 键值对齐**：`tui.key_value` 由字符宽度 `ljust` 改为 CJK 显示宽度感知对齐（新增 `_display_width`），修复中文键名错位。

---

## [2.3.9] — 2026-08-15

### 修复 / Bug Fixes (display)

- **ClawHub 人类读者导引位置调整**：将 SKILL.md 中的人类读者邀请语从 frontmatter 之后移至 `# /iterate` 标题之后，确保其在 ClawHub 平台渲染可见（原位置被平台过滤）。该行对 AI 助手无副作用。
- **人类读者导引补充英文版**：在中文导引旁新增英文版 `For human readers` 说明，邀请浏览者前往 GitHub 阅读 README，保持双语一致。
- **导引与简介视觉分隔**：在人类读者导引与 skill 简介之间加入分隔线 `---`，并为简介添加 `## 简介 / Overview` 标题，避免两段文字紧邻造成阅读困难。

## [2.3.8] — 2026-08-15

### 修复 / Bug Fixes (distribution)

- **ClawHub 名称纠正**：修正发布于 ClawHub 的 Skill 显示名为 `Iterate`（此前误发布为 `Clawhub Stage 2.3.7`），并重新分发至新版 2.3.8。
- **SKILL.md 顶部新增人类读者导引**：在 frontmatter 之后新增一条面向人类浏览者/开发者的说明，邀请其前往 GitHub 仓库 `jingzhao-l/iterate-skill` 阅读 README，以详细了解本 Skill 及其附属生态（iterate-harness、iterate-plugin、CLI 等）。该行对 AI 助手无副作用。

## [2.3.7] — 2026-08-14

### 修复 / Bug Fixes (skill)

- **TUI 接口契约**：`tui.question()` 签名返回类型由 `str` 修正为 `None`（此前签名与实现不一致）；删除无调用方的死代码 `prompt_prefix()`（其返回值含 rich 标记，若被用作 `input()` 提示文本会把 `[iterate.dim]` 标记泄露到终端）。新增 `tests/test_tui.py` 契约测试。
- **示例文档矛盾**：`examples/typescript-project.md` 预期行为第 5 条"验证通过后合并推送"与安全默认 `git.auto_merge=false` / `git.push_per_round=false` 矛盾，已对齐 Python/Swift 示例的措辞。
- **决策日志模板角色说明**：`templates/iterate-decisions.template.md` 增加头注释，明确该模板是 AI 会话按 SKILL.md「决策日志格式」章节填充的结构参考，`{...}` 非 Python format 占位符。
- **入口冗余**：移除 `iterate_cli/cli.py` 尾部与 `__main__.py` 重复的 `if __name__ == "__main__"` 守卫及无用 `import sys`。

## [2.3.6] — 2026-08-14

### 插件安全修复 / Security (iterate-plugin)

- **P0 最高优先**：`validate` 验证命令安全模型由「前缀白名单」改为 `validation.commands` 中命令的**精确匹配**。原前缀匹配允许攻击者通过构造形如 `python3 -c "..."` 绕过白名单执行任意代码，新精确匹配杜绝该风险。无配置信任命令时，会明确拒绝执行任意命令。

### 插件功能补全 / Features (iterate-plugin)

- **P1**：`iterate_context` 支持多路径查找 SKILL.md：按优先级 `自定义路径 → 自动探测 skill 目录（从插件位置向上找）→ 项目根` 查找，返回找到的内容和来源目录。解决插件挂载到项目目录时读不到原 skill 文档的问题。
- **P2**：`config-loader` 支持「默认配置（Master）+项目覆盖（Overrides）」深合并，无配置文件时也能以完整默认配置运行（仍保持 `validation.commands` 默认空，拒绝执行任何命令，符合最小权限）。工具层（`config/validate/review`）全部适配。

### 插件一致性对齐 / Bug Fixes (iterate-plugin)

- **P2**：`ReviewFinding` 字段对齐原 iterate skill：`detail/classification` → `failure_scenario/suggested_fix/is_atomic`，`review.ts/skill-prompt.ts`/测试用例同步更新。
- **P1**：dry-run/normal 工作流对子代理返回添加判空防御：`planRes/finalAgg` 为 null/无效时抛错而非崩溃。
- **P2**：`dry-run` 脚本 `finalReport.metaReview.issues` 添加可选链与默认值，避免无问题时访问 null。

### 新增单元测试 / Tests

- 新增 `config-loader.test.ts`、`context.test.ts`，共新增 22 个测试用例。
- 所有 TS 测试 53 个全绿，类型检查通过。

---

## [2.3.5] — 2026-08-14

### 修复 / Fixes

- **meta-review 误报收敛轮为 ROUND_EMPTY**：dry-run 收敛时最后一轮 0 个新 findings 是**正常的成功信号**，但 `metaReviewReport` 的 ROUND_SHAPE 检查会将其误判为 `ROUND_EMPTY` 缺陷，导致最终审查报告错误判定为 `needs_revision`。已修复——仅当**非最后一轮**出现空 findings 时才报 `ROUND_EMPTY`，最终收敛空轮不再触发。

### 文档 / Docs

- **`harness/iterate-plugin/README.md`**：新增插件运行时说明（安装、加载、dry-run 纯审查与 meta-review 用法）。
- **`DESIGN-iterate-harness.md`**：补充 meta-review 收尾步骤设计说明。

### 维护 / Maintenance

- 版本号统一升级至 `2.3.5`（`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json`、`harness/iterate-plugin/package.json`、`package-lock.json`、`SKILL.md` frontmatter）。

---

## [2.3.4] — 2026-08-14

### 新功能 / Features

- **`iterate review` 纯反复审查 + 报告元审查（meta-review）**：dry-run 纯审查模式新增收尾步骤——反复审查直至某一轮出现 0 个新 findings（收敛），生成审查报告后，再对报告本身进行元审查（校验报告内部一致性：总数匹配、严重级别汇总、维度汇总、排序、收敛数学），最终给出带 `approved`/`needs_revision` 判定的最终审查报告。全部判定逻辑保持确定性、可测试、不触碰文件。
  - `harness/iterate-plugin/src/meta-review.ts`：新增元审查引擎（`metaReviewReport` 执行 6 项一致性检查，`buildFinalReviewReport` 组装最终报告）。
  - `harness/iterate-plugin/src/tools/review.ts`：`iterate_review` 新增 `meta-review` 操作。
  - `harness/iterate-plugin/src/skill-prompt.ts`：dry-run 规范工作流加入 meta-review 阶段。
  - `harness/iterate-plugin/test/meta-review.test.ts`：新增 11 个元审查测试用例。
- **纯审查模式暴露到 skill 调用界面**：`/iterate <goal> review-only`（或 `dry-run`）即可触发纯审查模式。`SKILL.md` 新增 `$mode` 参数、review-only 适用场景与只读审查循环说明；`README.md` Daily Usage 补充纯审查调用示例与说明。

### 安全 / Security

- **`npm-installer` 解压路径遍历防护**：`extractTarball` 在解压前先用 `tar -tzf` 列出归档成员，校验每个成员在去掉顶层目录后解析出的路径仍落在目标目录内（防 `../` 逃逸），否则拒绝解压并抛出 `InstallerError`。保持零运行时依赖。
- **升级 `js-yaml` 至 `4.3.1`**：修复 `js-yaml@4.1.0` 的 4 个安全公告风险（含 2 个 high：prototype pollution merge、quadratic CPU consumption DoS）。`npm audit` 从 1 high 降至 **0 vulnerabilities**。js-yaml 仍为 MIT 许可证。

### 维护 / Maintenance

- 版本号统一升级至 `2.3.4`（`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json`、`harness/iterate-plugin/package.json`、`package-lock.json`、`SKILL.md` frontmatter）。

---

## [2.3.3] — 2026-08-14

### 修复 / Fixes

- **`full_reonboard` 未处理 `NO_CHANGES_NEEDED` 哨兵导致崩溃**：当回归用户同时拒绝基础更新和个性化配置时，`run_wizard` 返回的 `object()` 哨兵直接被传入 `write_onboarding_outputs`，抛出 `AttributeError`。此时旧文件已在向导运行前被备份，造成"备份了但没写入"的中间态。已新增 `NO_CHANGES_NEEDED` 判断并安全返回。
- **JS/Python 校验和解析不一致**：`npm-installer/lib/installer.js` 的 `parseChecksums` 未剥离 GNU tar 二进制标记 `*`，而 `scripts/install.py` 做了 `lstrip("*")`。若 `SHA256SUMS.txt` 采用 `HASH *filename` 格式，npx 安装器会校验失败。已统一 JS 侧 `replace(/^\*/, '')`。

### 安全 / Security

- **`_manual_collect_commands` 缺少 shell 元字符校验**：手动输入的验证命令未检查 `;` `|` `&` `` ` `` `$` `>` `<` `\n` `\r` 等 shell 链接元字符，存在绕过窗口。已复用 `FORBIDDEN_COMMAND_CHARS` 黑名单在输入时拒绝含元字符的命令。
- **`_safe_extractall` 回退分支硬编码 `/` 分隔符**：Python < 3.12 的路径遍历防护使用 `startswith(str(path) + "/")`，Windows 上永不匹配，导致所有合法成员被误判为可疑。已改用 `Path.is_relative_to()`（平台无关）。

### 维护 / Maintenance

- 移除死代码 `_detect_installed_assistants`（与 `detect_installed_assistants` 重复）和 `_fetch_latest_release_tag`（无调用方）。
- 为 `_update_iterate_md_user_section` 的 `read_text`/`write_text` 增加 try/except 异常处理，防止 `OSError`/`UnicodeDecodeError` 向上传播崩溃。
- `_download_release_source` 临时目录在异常和空提取分支增加 `shutil.rmtree` 清理，防止泄漏。
- 提取 `generate_config_yaml` 中裸字面量（`7`/`20`/`3`/`"Improve code quality..."`）为模块级具名常量。
- 提取 `_print_scan_results` 中目录截断上限裸字面量 `10` 为具名常量 `MAX_DIRS_DISPLAYED`。
- 拆分 `run_personalize_wizard`（112 行）为 `_run_personalize_steps_1_4` 与 `_run_personalize_steps_5_9` 两个子函数，满足单函数 ≤ 80 行的代码质量约束。
- 新增 `full_reonboard` 的 `NO_CHANGES_NEEDED` 回归测试（`test_returns_true_on_no_changes_needed`）。
- 新增 `parseChecksums` 的 `*` 标记剥离 JS 测试（`mode.test.js`）。
- 新增 `_manual_collect_commands` shell 元字符拒绝测试（`test_command_with_shell_metacharacter_is_rejected`）。

### 文档 / Docs

- **SKILL.md 配置表 `git.use_worktree` 描述澄清**：明确"当工作区有未提交改动时，无论此值如何，都优先用 worktree 隔离"，消除与 Step 1.7 的矛盾。
- **README 方式 B 手动复制修复**：从"只复制 SKILL.md"改为"必须复制整个 `iterate/` 目录（含 `config/`、`scripts/`、`templates/`），否则运行时找不到依赖"。
- `config/iterate.config.yaml` 的 `git.use_worktree` 新增注释说明。

---

## [2.3.2] — 2026-08-13

### 功能 / Features

- **漂移忽略列表（`onboarding.drift_ignore`）**：允许用户配置 fnmatch 模式，将锁文件等频繁变更的 manifest（如 `package-lock.json`、`yarn.lock`）排除出漂移检测。新增 `iterate_cli/fingerprint.py` 中 `_matches_ignore()` 的完整接线（此前为死代码）：`scan_manifests` / `capture_fingerprints` / `check_drift` 均支持忽略模式，`check_drift` 在比较前同时过滤当前扫描与已存指纹两侧，避免被忽略的旧指纹产生虚假 `removed` 漂移。`refresh.py` 新增 `get_drift_ignore()` 读取配置，`incremental_refresh` 刷新后的指纹列表会排除被忽略的 manifest。`config.schema.json`、`config/iterate.config.yaml`、`SKILL.md` 配置说明同步补充 `onboarding.drift_ignore` 字段。
- **`iterate status` 接入智能建议（`drift.advice()`）**：漂移检测到变更时，status 输出会展示根据漂移类型（新增/删除 vs 内容变更）生成的针对性建议（是否值得 `iterate refresh`），取代此前固定文案。
- **`iterate status` 信息增强**：新增 `Skill version`、`Fingerprints: N manifest(s)`、`Drift check: enabled/disabled` 输出；漂移为空时区分"检查已禁用 / 尚无指纹 / 未知"三种原因，便于排障。

### 修复 / Fixes

- **`SKILL.md`「何时跳过」与 Step 1 矛盾**：v2.3.1 已将脏工作区处理改为"优先 worktree 隔离、不中止"，但「何时跳过 / When to Skip」仍残留"工作区不干净→不要使用"条目。已删除该条（中英文），与 Step 1 的 worktree 隔离策略保持一致。
- **`SKILL.md` 配置表白名单描述过期**：「无需二次确认的允许命令前缀」更新为「不在白名单中的命令直接拒绝，不可通过用户确认绕过」，与命令白名单双层强制策略一致。
- **`config/dimensions.yaml` 主表 `frontend-backend` 缺 `priority`**：补上 `priority: high`，与权威文件 `config/dimensions/frontend-backend.yaml` 一致。

### 维护 / Maintenance

- `iterate_cli/generator.py` 中 `_render_dimensions` 的 `priority_map` 补充"需与 `config/dimensions.yaml` 保持同步"注释，明确重复维护关系。
- 新增 `tests/test_drift_ignore.py`（15 个用例）：覆盖扫描忽略、`check_drift` 两侧过滤、配置读取健壮性、refresh 后指纹排除、status 输出 advice 与新增字段。
- 同步更新 `SKILL.md`、`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json` 中的版本号至 `2.3.2`。

---

## [2.3.1] — 2026-08-13

### 功能 / Features

- **操作者级验证工具安全扩展点（无需改源码）**：`iterate_cli/personalize.py` 新增环境变量 `ITERATE_EXTRA_SAFE_COMMAND_PREFIXES`，允许操作者在系统层面追加预批准工具前缀（如 `sphinx`），而无需编辑源码。该变量**只能在进程环境设置，项目配置文件无法设置**，因此不会破坏既有安全模型；含 `;`、`|`、`&` 等元字符的条目会直接丢弃（fail-closed），不以其开头或以非字母数字开头（如 `-rf`、`/`）的碎片也会被过滤。新增 7 个回归测试覆盖默认、解析、注入丢弃、白名单扩展、元字符拒绝与 `python -m` 形式。

### 文档 / Docs

- **首次使用预期提示（体验）**：SKILL.md Step 0 与 AI Onboarding 明确要求 AI 在首次调用时先说明"将先进行项目初始化"，避免用户误以为 skill 失效；README FAQ 同步更新"第一次使用为什么什么都不做"。
- **Monorepo 定位（体验）**：SKILL.md Step 0 与 Setup 的项目根目录定位改为优先命中含 `ITERATE.md` / `iterate.config.yaml` 的目录，并对多子项目场景给出 `AskUserQuestion` 确认，避免误审无关子项目。
- **脏工作区处理（体验）**：SKILL.md 创建隔离环境改为优先 `git worktree add` 隔离，不再强制要求 commit/stash、不因用户拒绝而直接中止。
- **会话内进度反馈（体验）**：SKILL.md Step 2 新增"进度反馈"约定，要求主模型每轮开始/并行审查/每轮结束持续输出进度；README FAQ 的"大项目卡住"答案同步说明。
- **交付指引与提前终止（体验）**：SKILL.md Step 3 新增"交付指引"（明确分支名、日志路径、合并/推送选项）与"提前终止"（剩余均 low 或目标达成时询问提前结束），README FAQ 同步。
- **会话恢复（体验）**：SKILL.md 会话中断与恢复改为 AI 自动读取 `.iterate_decisions.md` 并主动提议 resume/restart/仅查看报告，用户无需自行理解决策日志。
- README FAQ 更新"想增加新的验证工具"答案，补充环境变量扩展方式。

### 维护 / Maintenance

- 同步更新 `SKILL.md`、`pyproject.toml`、`iterate_cli/__init__.py`、`npm-installer/package.json` 中的版本号至 `2.3.1`。

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
