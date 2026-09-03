# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/)。
每个版本变更记录在下方，最新版本在最前。

---

## [3.0.0] — 2026-09-03

### 新增 / Features

- **双模式：iterate 原模式 + 防御式编程模式**（v3.0 大版本主线）：SKILL.md 新增防御式编程模式（`/iterate defensive`），面向**用户让 AI 做正常增量式编程任务**（新增功能、修 bug、重构、接入 API、补测试）——宿主 AI 从动手前到收尾**从头至尾贯彻防御式编程理念**：① 动手前（声明假设 + 前置校验）→ ② 动手时（信任边界验证 + 最小步进）→ ③ 动手后（每步后置校验）→ ④ 收尾（不变量守护 + iterate 收敛门禁，**不收敛不交付**）。iterate 原模式（`/iterate`）行为与 v2 完全一致，零回归，默认不变。
- **CLI `iterate guard pre-check [paths...]`**：动手前确定性前置校验——目标路径存在、git worktree 干净、依赖 manifest 就绪、验证命令配置安全；退出码 0 = 可以开工，1 = 禁止开工；支持 `--json` / `--dry-run`。
- **CLI `iterate guard post-check [module...]`**：动手后后置校验——精确执行 `validation.commands.<module>`（运行时唯一权威白名单，不拼装不前缀）；退出码 0 = 本次改动安全，1 = 必须先修复或回滚；支持 `--json` / `--dry-run`。
- **CLI `iterate invariant`**：项目级不变量检查——`invariants.ensure` 文件断言 + `invariants.commands` 命令列表；无 `invariants` 段时自动退化为 `validation.commands`（旧配置零破坏）；退出码 0 = 不变量成立，1 = 存在违反项；支持 `--json` / `--dry-run`。
- **配置 `mode: iterate | defensive`**：`iterate.config.yaml` 新增默认执行模式配置项（默认 `iterate`，零破坏），可用调用参数显式 `defensive` 覆盖；`iterate show` / `iterate config get|set mode` 支持读写。
- **配置 `invariants` 段**：`iterate.config.yaml` 新增 `invariants`（`ensure` 文件断言 + `commands` 精确命令列表），与 `validation.commands` / `command_whitelist` 共用安全基线（白名单校验、元字符防护）；`config/config.schema.json` 与随包分发副本同步扩展。

### 测试 / Tests

- 新增 `tests/test_guard.py`（28 例）：pre-check / post-check / invariant 的正常路径、异常路径（目标缺失、manifest 缺失、命令失败、脏 worktree、损坏配置）与边界场景（无参数、空配置、模块过滤、dry-run 预览、invariants 退化到 validation.commands、JSON 输出与退出码），并覆盖 CLI 集成（`guard` / `invariant` 子命令的 `--json` 与退出码契约）。
- 全量 Python 测试 916 个全部通过（既有 888 + 新增 28），`ruff check .` 通过。

---

## [2.12.0] — 2026-09-02

### 新增 / Features

- **`iterate config --json` 结构化输出**：非交互式配置命令新增 `--json`，供脚本/CI 场景消费——`iterate config --json` 输出全部可设键的 JSON 对象、`iterate config get KEY --json` 输出 `{"KEY": value}`、`iterate config set KEY VALUE --json` 成功时输出 `{"key": KEY, "value": <解析值>}` 确认对象；stdout 保持纯净（错误仍走 stderr + 非零码），与 `iterate status/show/doctor --json` 契约对齐。

### 修复 / Fixes

- **publish_qoder 安全加固**：`_git_archive_extract` 原先用 `os.system(" ".join(cmd))` 经 shell 执行 `git archive`，`--exclude` 用户输入被无引号拼入命令字符串，存在 shell 注入面。现改用 `subprocess.run(check=False)` 列表形式（不启动 shell）并以真实返回码判定；解压由裸 `archive.extract` 改为 `archive.extractall(members=_safe_members(...))`，`_safe_members` 拒绝绝对路径、`..` 越界、重复成员及逃逸目标目录的符号链接（zip-slip 防护，与 `install.py` 安全基线一致）。
- **install 下载根目录选择更稳**：`_download_release_source` 原返回 `extracted[0]`（临时目录迭代首个子目录），多顶层目录时可能选中非 skill 目录。现要求 release tarball 顶层目录中恰好一个含 `SKILL.md` 标记，否则拒绝并报错返回。

### 测试 / Tests

- 新增 `tests/test_publish_qoder.py::TestSafeMembers`（6 例：正常嵌套成员、`..` 越界、绝对路径、重复成员、逃逸符号链接、目录内安全符号链接）。
- 新增 `tests/test_install_script.py::TestDownloadReleaseSource`（3 例：唯一含 SKILL.md 根被选中、无标记根拒绝、多标记根拒绝）。
- 新增 `tests/test_config.py::TestConfigJson`（5 例：单键 get、全键 list、set 确认且 stdout 纯净、未知键报错、run_config_get 直调）。
- 全量 Python 测试 888 个全部通过，`ruff check .` 通过。

---

## [2.11.2] — 2026-09-01

### 修复 / Fixes

- **refresh 调和结果真正落盘**：`iterate refresh` 原本计算出的新增 `validation.commands`、`command_whitelist` 前缀与 `dimension_sets` 调和结果只用于重渲染 `ITERATE.md`，未写回 `iterate.config.yaml`，导致配置与文档跑偏。现将 `_build_refreshed_config` 改为接收完整 `OnboardingData`，把调和后的 dimension_sets / validation.commands / command_whitelist / reasoning_effort 等一并持久化，同时保留用户既有自定义字段（如自定义命令逐字保留、显式空白名单意图不覆写）。
- **doctor 畸形白名单不再绕过元字符安全网**：`command_whitelist` 为非法形态（如裸字符串 `make`）时，原先跳过了白名单合规校验，且独立的 shell 元字符安全网仅在白名单为 `None` 时运行，导致 `make; rm -rf /` 这种命令可能通过健康门禁。现检测到非法白名单时仍调用元字符检查，安全网不再被绕过。
- **wizard 重跑基础配置不再丢弃数据**：返回用户拒绝更新基础配置、但现有配置无法加载时，重新运行完整基础向导并确认的新数据，若随后未再个性化，会被「全部拒绝/无变更」守卫丢弃导致白做。现在重跑基础向导即视为"更新基础配置"，新采集的数据会正常写入。
- **validate.py 重定义区块切分双重偏移**：`_sections_for_redefinition` 用 `content[match.start():][start:]` 切分，第二次切片偏移作用在已裁剪子串上造成偏移叠加，长前置文本会跳过区块内部终止标题、让其越界吞并后续内容。改为 `content[start:]`（`start == match.end()`）直接切分，块边界正确停在下个 `## `/`### ` 标题前。
- **publish_qoder 幂等标记字符不一致**：依赖自包含说明段的幂等守卫检测单空格 `<!-- QODER:DEPENDENCIES -->`，而写入时经两次 `replace()` 得到双空格版本，导致复用已标注 `SKILL.md` 重建时重复追加。现直接嵌入 `_DEP_MARKER` 原样，重复构建幂等。

### 内部 / Internal

- `iterate_cli/refresh.py::_build_refreshed_config` 签名由 `(existing_config, new_fingerprints)` 改为 `(existing_config, data: OnboardingData)`；局部用具名拷贝替换 `**dict` 解包以消除 mypy type 错误。

### 测试 / Tests

- 新增 `tests/test_refresh_reconcile.py::TestIncrementalRefreshPersistsReconciledData`（4 例：命令/白名单落盘、dimension_sets 落盘、_build_refreshed_config 直接同步、自定义命令保留）。
- 新增 `tests/test_validate.py::TestSectionsForRedefinition`（2 例：块止于下个三级标题、两个连续重定义块互不吞并）。
- 新增 `tests/test_publish_qoder.py`（2 例：幂等标记逐字一致、普通文件仅追加一次）。
- 全量 Python 测试 874 个全部通过，`ruff check .` 通过。

---

## [2.11.1] — 2026-08-31

### 修复 / Fixes

- **偏门范围重定义「禁抄预设」**：`SKILL.md` Phase 0 明确——未命中任何命名维度集的 goal，必须从根（维度全集）重新推导维度方案，禁止以全局 `dimensions` 或任一已有维度集为起点筛选/微调；每个选中维度必须给出本范围特有的独立理由（与某预设集雷同即视为套用、推翻重想），并可新增非标准临时维度。范围路由（命中预设）与重定义（未命中）两条路径彻底分离，防止 AI 惰性沿用预设。

### 新增 / Features

- **`scripts/validate.py decisions` 新增重定义记录机器校验**：`.iterate_decisions.md` 中出现 `### Scope Dimension Redefinition (on-the-fly)` 小节时，强制要求 `**Origin scope:**` 与 `Dimension / Independent reason` 表格，且每个维度的理由不得照抄 `config/dimensions/<dim>.yaml` 默认 focus（去空白/大小写归一化后比对）。为「禁抄预设」提供可执行的第二道闸。决策日志模板同步新增该小节示例。

### 内部 / Internal

- `pyproject.toml` 的 ruff `extend-exclude` 收录 `.awesome-claude-skills`（第三方 marketplace 校验用 submodule，本地检出会导致 `ruff check .` 假阳性，CI 未检出子模块不受影响）。

### 测试 / Tests

- 新增 `tests/test_validate.py::TestValidateScopeRedefinitions`（8 例：缺 Origin / 空 Origin / 理由抄默认 focus / 理由为空 / 缺表头 / 无数据行 / 合法通过）；全量 Python 测试 862 个全部通过，`ruff check .` 通过。

---

## [2.11.0] — 2026-08-31

### 新增 / Features

- **范围审查蓝图 `dimension_sets`**：新增「按审查范围预设的维度集」能力。用户在 onboarding 时可按 `frontend` / `api` / `security` / `performance` / `style-tests` 等命名集预设维度组合（扫描器按项目实际技术栈筛除不存在 UI/API 层的集）；`iterate.refresh` 保留用户自定义集并增量补入新检测出的层集；校验与健康检查（`scripts/validate.py`、`iterate doctor`）校验集名字符集、维度合法性及 `focus` 一致性。schema（`config/config.schema.json` 与 `iterate_cli/data/config.schema.json`）已同步 `dimensionSet` 定义。
- **`ITERATE.md` 新增「推荐审查蓝图（按范围）」段**：渲染命名维度集供整仓与分范围审查使用；全局 `dimensions` 列表仍是整仓审查默认，指定范围命中蓝图时按该集路由。
- **范围路由运行时支持（SKILL.md Phase 0）**：指定目标的审查优先匹配对应命名维度集；未命中任一律时按该范围动态重定义维度并写入 `.iterate_decisions.md`（带边界记录）。

### 内部 / Internal

- `iterate_cli/dimension_sets.py`：命名集建议/规范化/合并逻辑（新增模块）。
- `mypy strict` 全量归零、`ruff` 全部通过；新增 `tests/test_dimension_sets.py`（19 例覆盖键名/规格规范化、扫描剪枝、refresh 合并）。

### 测试 / Tests

- 新增 `tests/test_dimension_sets.py`（19 例）与 `tests/test_doctor.py`、`tests/test_validate.py` 的 `dimension_sets` 一致性用例；全量 Python 测试 854 个全部通过。

---

## [2.10.0] — 2026-08-30

### 新增 / Features

- **`reasoning_effort` 端到端 CLI 支持**：onboarding 向导新增「推理努力度」配置项（`low`/`medium`/`high`，默认留空跟随 provider），生成的 `iterate.config.yaml` 输出该字段；`iterate show` 展示、`iterate doctor` 校验并自动修复非法值、`iterate refresh` / re-onboard 保留用户自定义值。schema（`config/config.schema.json` 与 `iterate_cli/data/config.schema.json`）已同步。
- **新增 `iterate config` 非交互式配置子命令**：`iterate config` 列出全部可设值，`iterate config get [KEY]` 读取单个（或全部）解析值，`iterate config set KEY VALUE` 校验并写回单个配置项（写入前自动生成时间戳备份）。支持扁平键（`goal`/`max_rounds`/`reasoning_effort`/`language`/`dimensions`）与嵌套段（`atomic.*`/`git.*`/`review.scope`/`reviewer.*`），损坏配置拒绝覆写。修复了 flat 键读取返回整份配置的 bug。

### 测试 / Tests

- 新增 `tests/test_config.py`（24 例）覆盖值解析器、`get`/`set` 正常与异常路径、嵌套写入、备份生成、损坏配置保护与 CLI 退出码；全量 Python 测试 820 个全部通过。

---

## [2.9.1] — 2026-08-27

### 修复 / Bug fixes

- **onboard 不再覆盖手动编辑区**：重新引导时若现有 `ITERATE.md` 缺少 USER-OWNED 区标记，拒绝继续并提示改用 `iterate reonboard`（会先备份），避免静默替换用户手写内容。
- **损坏配置干净报错**：`iterate personalize`（保存与 `--clear` 两条路径）遇到无法解析的 `iterate.config.yaml` 时以清晰错误返回非零码，不再把损坏配置当作「无可清除内容」（返回 0）或抛出裸 traceback。
- **配置写入权限保留**：`atomic_write` 保留原文件权限位（如 0600 的受限配置），不再因临时文件按 umask 生成而悄悄放宽权限。
- **命令校验安全网**：`doctor` 对未配置 `command_whitelist` 的 `validation.commands` 也检查 shell 元字符；已配置白名单时，含元字符的命令同样以错误（而非警告）拦截，防止 `pytest; rm -rf /` 这类命令链通过健康检查。
- **维度校验加固**：`dimensions` 为非列表（如手写标量字符串）时 `doctor` 报错而非静默回退为全部规范维度。
- **个性化一致性校验修正**：缺失/空 `dimension` 的条目不再误报「指向禁用维度 None」（与 `scripts/validate.py` 行为一致）。
- **skill_version 缺失提示修正**：未记录版本时 `doctor` 输出「nothing to compare」，不再误报「匹配」。
- **re-onboard 读取失败中止**：ITERATE.md 无法读取时中止 re-onboarding 并保留 `.bak` 备份，不静默重建丢手动内容。
- **fingerprint 宽容解析**：畸形条目（非字典、缺 path/sha256）被跳过而非抛异常，手写配置降级为「无漂移」而非崩溃。
- **show 损坏配置标记**：`iterate show` 在配置缺失/损坏时标记 `config_error` 并提示运行 `iterate doctor`。
- **status 拆分与 drift 复用**：抽取 `_render_status_tui`，drift 摘要/建议经 `drift_summary`/`drift_advice` 单次计算复用。
- **refresh 保留 reviewer 调优**：`_build_refresh_data` 拆分，channel 非字符串规范化，保留 reviewer 的 output/evidence/coverage/scope_chunk_size 自定义值。
- **scan 建议去重**：Java/Kotlin 多语言条目只生成一次构建工具建议；API 层指示目录提取为具名常量。
- **TUI 渲染改进**：`_display_width` 处理组合记号/变体选择符/Emoji 宽度；`status` 非交互终端返回 no-op；`error` 默认缩进统一为 2；删除未用符号常量。
- **installer 交互与安全加固**：`scripts/install.py` 原子写配置、下载响应大小上限、解压硬链接越界拒绝、`install/uninstall/update` 退出码语义统一、删除死代码 `_render_arrow_select`、网络错误原因透传；`npm-installer` 下载超时（`--max-time 120`）、tarball 下载进度、`--target` 相对路径解析、checksum 解析与 Python 侧一致、魔法字符串提取为常量。
- **wizard 细节修正**：非交互 stdin 明确报错、扫描结果双语标签、默认常量引用（target_branch/review_scope/language/scope_chunk_size）。

### 测试 / Tests

- 新增 doctor 元字符安全网、维度类型、个性化一致性、onboard USER-OWNED 保护、personalize 损坏配置、atomic_write 权限、TUI 宽度（emoji/组合字符）、installer 退出码等用例；Python 测试 778 个全部通过，npm-installer 测试通过。

---

## [2.9.0] — 2026-08-26

### 修复 / Bug fixes

- **CLI 全局标志可放子命令后**：`iterate status --no-banner`、`iterate doctor -p <dir>` 等写法现在与 `iterate --no-banner status` 等价；此前子命令默认值会覆盖全局标志（`-p`/`--no-banner` 放在子命令前会被忽略）。
- **reviewer 配置完整保留**：onboarding 生成的 `iterate.config.yaml` 现在写入完整的 `reviewer` 段（`evidence_validation`、`coverage_validation`、`scope_chunk_size` 与 `output_schema_validation` 一起），`iterate refresh` / re-onboard / 返回用户更新基础配置时均保留用户自定义值，不再静默重置。
- **show 展示补齐**：`iterate show` 的 TUI 与 `--json` 输出补充 `evidence_validation` 字段渲染。
- **安装器箭头菜单重绘修复**：`npx iterate-skill-installer` 交互式选择 AI 工具时，raw 终端模式下 `\n` 只换行不回车，导致每次按键后菜单逐行向右错位（"螺旋阶梯式"重复打印）。重绘改用 `\r\n` 分隔，并提取 `_arrow_redraw_output` 纯函数 + 模拟终端回归测试。
- **配置解析加固**：各配置加载点对嵌套配置段做类型检查，非字典段不再导致崩溃，统一降级为空字典并保持其余字段可用；新增回归测试覆盖。
- **命令白名单放宽**：`go test` 白名单条目改为 `go`，使 `go vet`、`go build` 等所有以 `go` 开头的命令都能通过命令白名单校验，不再误拒。
- **npm-installer 参数校验**：`--ai` / `--target` / `--token` 的参数值若以 `-` 开头（疑似误传后续标志）直接报错，防止静默吞掉标志。
- **workflow_dispatch 支持指定 tag**：`release.yml` 手动触发时可通过 `inputs.tag` 指定构建/发布目标 tag，与 Release published 路径行为一致。
- **内置 schema 同步**：内置 `iterate_cli/data/config.schema.json` 与根 `config/config.schema.json` 保持一致。
- **README badge 链接修正**：SkillHub badge 指向正确链接。

### 重构 / Refactor

- **死代码清理**：移除重复 import 与未使用代码，保持 ruff/mypy 干净。

---

## [2.8.1] — 2026-08-23

### 修复 / Bug fixes

- **命令校验字符集统一收敛**：`personalize` / `doctor` / `validate` 三处 shell 元字符禁止集收敛为同一权威集合，杜绝「个性化阶段放行、白名单阶段拒绝」的矛盾；新增回归测试强制三方同步。
- **schema 文档同步**：内置 `iterate_cli/data/config.schema.json` 与根 `config/config.schema.json` 描述一致，新增测试防漂移。
- **安装检测逻辑统一**：`install.py` 的 `detect_installed_assistants`（菜单预选 / 自动 update）改用与卸载/升级一致的 `SKILL.md` 标记判定，多路径行为一致。
- **downloads badge 响应限流**：`update_downloads_badge.py` 对上游响应体施加 5 MiB 截断读保护，避免无界内存占用。
- **平台 SKILL 文档对齐**：claude / cursor 变体补齐 review-only (dry-run) 只读审查模式说明，与根 `SKILL.md` 及 trae 变体一致。
- **测试覆盖补齐**：scan / fingerprint / refresh 的异常分支与边界场景新增用例。

---

## [2.8.0] — 2026-08-22

### 新增 / Features

- **unattended CLI 子命令**：接线 schedule / hook / cron 无头调用路径，方便脱离对话在定时/钩子场景复用同一闭环。

### 修复 / Bug fixes

- **refresh 版本同步**：`iterate refresh` 现在把 `onboarding.skill_version` 同步到已安装版本，消除 `iterate doctor` 反复提示版本更新的告警（此前刷新不更新该记录）。
- **reonboard 结果区分**：区分「用户取消」与「失败」，不再混用含糊的 "cancelled or failed" 消息。
- **status 一致快照**：`iterate status` 改为单次读取 onboarding 状态/config/drift，JSON 与 TUI 两条渲染路径共享同一数据源。
- **类型安全收敛**：personalization 行号钳制、show 可选配置段解析做类型收窄，满足 ruff PLR1730 与 mypy。
- **webui**：浮出 workspace 删除错误，统一报告尺寸格式化。

---

## [2.7.0] — 2026-08-22

### 发布 / Release

- **主技能版本对齐**：配合插件发布线（iterate-plugin 2.11.0）推进到 2.7.0，将与贴身 harness（iterate-harness 1.13.0）保持同源的强化后状态；无破坏性 API 变更。

---

## [2.6.0] — 2026-08-21

### 修复 / Bug fixes (审查收敛：UX 与一致性)

- **CLI 优雅中断**：交互命令期间 Ctrl+C / Ctrl+D(EOF) 不再抛裸 traceback，统一转为"已中断/输入已结束，未写入任何文件"提示并退出码 1；命令分发集中到 `_dispatch_command` 统一包裹。
- **`--version` 横幅一致性**：`--no-banner` / `ITERATE_NO_BANNER` 现在同样抑制 `--version` 的 ASCII 横幅，仅保留版本信息。
- **doctor 警告态总结**：末尾总结区分三态——存在 error 显示"error(s) found"，仅 warning 显示"healthy but with N warning(s) — non-blocking"，干净显示"healthy (N checks passed)"，避免与上方 findings 自相矛盾。
- **doctor config.schema 可用性**：schema 文件/jsonschema 不可用时降为 warning 而非假"完全匹配"成功（`_schema_violations` 返回语义从空 list 改为 `None`）。
- **doctor 命令元字符过滤扩展**：白名单命令校验扩充过滤集，并改为一次性严格拒绝含元字符的命令。
- **doctor 空维度早退**：空 `dimensions` 报错后提前 return，不再同一次运行再报成功行自相矛盾。
- **doctor 个性化字符串守卫**：手写的字符串 `fix_priority_order` 不再被逐字符误判为断裂维度。
- **doctor onboarding 消息精确化**：缺失提示精确反映仅检查 ITERATE.md（config 由 `config.parse` 单独校验）。
- **`iterate show` 生效配置修正**：此前从 `onboarding` 区段读取生效键导致部分键反映错误值；改为从各自规范位置（顶层 + git/review/atomic/reviewer 嵌套区段）读取。
- **`iterate show` 漂移建议**：检测到漂移时 TUI 追加 `Suggested: ...` 行动建议，`--json` 新增 `drift_advice` 字段。
- **`iterate show` 维度渲染**：`dimensions` 按 list 渲染（原先按 dict 分支永不匹配，实际不显示）。

### 测试 / Tests

- 新增 doctor 警告态总结、CLI 优雅中断、`--version` 横幅、show 漂移建议等回归测试。
- 全量 `tests/` **675 passed**。

---

## [2.5.0] — 2026-08-21

### 新增 / Features

- **`iterate show`**：只读查看合并后的生效配置与个性化详情（onboarding 元数据、生效 config、漂移状态、全部 9 类个性化）。TUI 输出面向人，`--json` 输出结构化数据供脚本/CI/快速 diff。不写任何文件。
- **`iterate personalize --clear [--yes]`**：一次性清空所有个性化——结构化规则从 `iterate.config.yaml` 移除、由个性化所有权新增的验证命令从 `validation.commands` 清理（空模块自动剔除）、`ITERATE.md` 用户区中的个性化段落移除而保留手工内容。原子写入 + 失败回滚，跨文件保持一致；无个性化可清空时友好提示并退出码 0。`--yes` 跳过确认。

### 修复 / Bug fixes (审查收敛)

- **doctor 配置安全与逻辑**：修复浅拷贝共享原配置对象的隐患（改用 `copy.deepcopy`）；修复 `set.add()` 返回值误用（原本 `None` 可能被判为重复）；个性化维度/命令检查改为类型安全（非 list 值不再崩溃）。
- **wizard 再入一致性**：返回用户更新基础配置时保留已有高级字段（language/goal/max_rounds 等），不静默重置；确认的语言立即生效到验证命令建议/白名单/维度默认；统一确认提示默认值；`drift_ignore` 在再 onboarding 时正确持久化。
- **fingerprint/scan 健壮性**：清单文件在存在检查后消失、不可读、非 UTF-8 时不再抛未捕获 `OSError`，降到 stderr 警告并跳过；顶层目录列表失败同样容错。
- **validate.py UX**：未显式指定维度目录且默认回退目录不存在时，明确提示"维度校验被跳过"而非静默跳过；清理无占位符的 `f` 前缀。
- **show/personalize 边界**：未 onboarding 时 `show` 友好提示；`--clear` 取消确认不做任何变更。

### 文档 / Docs

- `SKILL.md` frontmatter 版本与 CLI 子命令列表补 `iterate show`、`iterate personalize --clear`。
- `README.md` 新增 `iterate show` 与 `iterate personalize --clear` 小节（含 `--json` / `--yes` 用法与退出码）。

### 测试 / Tests

- 新增 `iterate show` 与 `personalize --clear` 相关测试（含 TUI/JSON 渲染、纯函数移除语义、CLI 端到端清理、取消确认不落地、无个性化可清空）。
- 全量 `tests/` **657 passed**，`ruff check` 干净。

### 审查收敛（第二轮：UX 与一致性 / 本轮）

- **CLI 优雅中断**：交互命令期间 Ctrl+C / Ctrl+D(EOF) 不再抛裸 traceback，统一转为"已中断/输入已结束，未写入任何文件"提示并退出码 1；命令分发集中到 `_dispatch_command` 统一包裹。
- **`--version` 横幅一致性**：`--no-banner` / `ITERATE_NO_BANNER` 现在同样抑制 `--version` 的 ASCII 横幅，仅保留版本信息。
- **doctor 警告态总结**：末尾总结区分三态——存在 error 显示"error(s) found"，仅 warning 显示"healthy but with N warning(s) — non-blocking"，干净显示"healthy (N checks passed)"，避免与上方 findings 自相矛盾。
- **doctor config.schema 可用性**：schema 文件/jsonschema 不可用时降为 warning 而非假"完全匹配"成功（`_schema_violations` 返回语义从空 list 改为 `None`）。
- **doctor 命令元字符过滤扩展**：白名单命令校验扩充过滤集（`\` `#` `*` `?` `~` `"` `'` `{}` `()` `[]`），并改为一次性严格拒绝含元字符的命令。
- **doctor 空维度早退**：空 `dimensions` 报错后提前 return，不再同一次运行再报"all dimensions canonical"的成功行自相矛盾。
- **doctor 个性化字符串守卫**：手写的字符串 `fix_priority_order` 不再被逐字符误判为断裂维度。
- **doctor onboarding 消息精确化**：缺失提示改为精确反映仅检查 ITERATE.md（config 由 `config.parse` 单独校验）。
- **`iterate show` 生效配置修正**：此前从 `onboarding` 区段读取生效键导致 `atomic_*`/`auto_merge`/`target_branch`/`review_scope`/`output_schema_validation` 等反映错误值；改为从各自规范位置（顶层 + git/review/atomic/reviewer 嵌套区段）读取。
- **`iterate show` 漂移建议**：检测到漂移时 TUI 末尾追加 `Suggested: ...` 行动建议，`--json` 新增 `drift_advice` 字段。
- **`iterate show` 维度渲染**：`dimensions` 按 list 渲染（原先按 dict 分支永不匹配，实际不显示）。
- **测试**：新增 doctor 警告态总结、CLI 优雅中断、`--version` 横幅、show 漂移建议等回归测试；全量 `tests/` **675 passed**。

---

## [2.4.5] — 2026-08-20

### 修复 / Bug fixes (CLI 一致性、安全与文档)

- **refresh 幂等性**：增量刷新复用上次 `completed_at` 时间戳，未变化时逐字节 no-op；`_diff_stats` 跳过 `--- /+++` 文件头行，改动行数统计不再虚高。
- **拒绝静默覆盖手写 ITERATE.md**：缺失 `USER-OWNED` 区块标记时 refresh 抛错拒写而非销毁用户内容（`generate_refreshed_md` 两侧都校验）。
- **personalize 删除同步**：删除个性化验证命令时同步清理 `validation.commands`（按旧归属精准删除、非个性化命令保留），不再残留死命令。
- **doctor 重构为模块化检查**：单一 `run_doctor` 拆分为 `_check_onboarding`/`_check_config_parse`/`_check_config_schema` 等单职责函数，两个致命检查短路后续。
- **validate.py 健壮性**：`command_whitelist` 非字符串条目不再崩溃（过滤+报错），schema 缺失/损坏时优雅降级并报告。
- **CLI schema 同步**：`iterate_cli/data/config.schema.json` 补回 `reviewer.evidence_validation`/`coverage_validation`/`scope_chunk_size`，与主 `config/config.schema.json` 完全一致。
- **install.py 安全加固**：`copy_skill_files` 增加目标路径穿越防护、符号链接目标先 unlink 再替换；`_safe_extractall` 拒绝 symlink 目标逃逸；`_parse_checksum` 支持 `./` 前缀；`update` 移除死参数 `--force` 并接入 `_validate_github_token` 前置校验，畸形 token 快速失败。
- **npm-installer**：新增 `--version/-v` 与 `--help/-h`；tar 解压强制单一顶层目录契约；新增 `LICENSE` 随包分发；CI 增加 node 测试 job。

### 文档 / Docs

- `SKILL.md` 项目结构补齐 `doctor.py`/`personalize.py`/`tui.py`/`data/`；CLI 子命令列表补 `iterate doctor`。
- `README.md` 补充 UX 文档缺口：新增 `iterate doctor` 详述（10 项检查表 + `--json`/`--json-out`/`--fix` 用法与退出码）、常见边界场景（onboarding 中途取消原子写入、无 `USER-OWNED` 标记拒写、非 Git 项目、空项目漂移、配置损坏处理、Early Stop 收敛）、新手推荐路径（安装 → onboarding → doctor → personalize → /iterate）。
- `tools/SKILL.{trae,claude,cursor}.md` 三份平台适配版同步 2.4.x 特性：reviewer prompt 注入 `EVIDENCE RULE`、meta-review 硬证据门禁（`EVIDENCE_VIOLATION`→`needs_revision`）、覆盖率提示（`COVERAGE_GAP`）、onboarding/personalization 指引。

### 测试 / Tests

- 新增 TUI 渲染与 banner 测试（`_display_width` CJK 双宽、各渲染方法、`--no-banner`/`ITERATE_NO_BANNER` 开关逻辑）。
- 新增 install.py 畸形 token 快速失败、空 token 视为缺省测试；refresh 缺 USER-OWNED 标记拒写测试。
- 全量 `tests/` **647 passed**，`ruff check` 干净。

---

## [2.4.4] — 2026-08-20

### 修复 / Bug fixes (安装器 TUI 重绘)

- **箭头多选菜单根治「阶梯式螺旋」**：此前即使有滚动窗口，长标题在窄终端换行后 `move_up` 用逻辑行数上移不足、且重绘未回归列首，逐帧下坠挤压成螺旋。现重绘改为：按每行实际显示宽度（含 CJK 双宽）计算**物理行数**、精确回退光标、`\r` 归列 `\x1b[0J` 清屏后整帧重写；宽度计算用可剥离任意 CSI（光标/清除/颜色）的 `_strip_ansi` 与依赖自由的 `_wcwidth_display_cols`。另隐藏光标避免闪烁，退出时恢复。

### 测试 / Tests

- 新增 `TestTuiRedrawHelpers` 六条用例：CSI 全序列剥离、CJK 双宽计数、窄终端换行物理行不塌缩、物理行数恒 ≥ 逻辑行数。
- 全套 `tests/test_install_script.py` 现 **85 passed**。

---

## [2.4.3] — 2026-08-20

### 新增 / Features (安装器 --no-cli)

- **新增 `--no-cli` 开关**：只想安装 skill、不想要全局 `iterate` CLI 的用户可用 `npx iterate-skill-installer --no-cli` 跳过 CLI 安装。`parseArgs` 从 `bin/cli.js` 抽取到 `lib/installer.js` 并导出，可独立单测。
- **自动装 CLI 更透明**：不再静默预装 CLI。安装 skill 后明确提示即将安装 `iterate` CLI（并说明可用 `--no-cli` 跳过）；使用 `--no-cli` 时改打印「稍后如何手动安装 CLI」的指引。

### 测试 / Tests

- `mode.test.js` 新增 `parseArgs` 用例：`--no-cli` 默认关闭、单独开启、与其它 flag 组合保持；并回归 target 强制 project 模式等既有 flag 面。

---

## [2.4.2] — 2026-08-20

### 修复 / Bug fixes (安装器交互体验)

- **箭头菜单不再螺旋排列**：`scripts/install.py` 选择安装工具的箭头多选菜单在选项超过终端高度时曾逐行错位成阶梯式螺旋。现新增滚动窗口（`MAX_WINDOW=6`），仅渲染当前可见选项，重绘按恒定行数上移光标，菜单高度固定、任何终端都不会溢出或错位。
- **陈旧版本不再静默跳过**：此前目标目录已存在 iterate-skill 安装（可能为旧版本）时会静默跳过，用户无法感知。现在交互终端会询问「是否覆盖升级到最新版」，非交互模式保留现有拷贝并提示使用 `--force`。另按目标目录去重，避免共享目录重复安装。

### 测试 / Tests

- 新增滚动窗口跟随光标、Done 行显示末页、渲染高度固定三组用例；新增陈旧版本升级确认（交互分支）用例。

---

## [2.4.1] — 2026-08-19

### 新增 / Features (强制子代理逐文件读取审查范围 + 覆盖率校验)

- **审查范围强制逐文件读取**：`plan` 在 `full` 范围下预先收集源码清单并按 `reviewer.scope_chunk_size`（默认 25 个）分批；reviewer prompt 注入 `COVERAGE RULE`，要求子代理必须先以 `read_file` 打开负责清单中的**每一个**文件再作判断，不得跳过、臆测或在未读的情况下下结论，并在返回 JSON 中附带 `readFiles` 数组如实罗列实际打开的文件。`changed-only` 范围同样强制逐条读取更动文件清单。
- **覆盖率提示性校验（meta-review）**：meta-review 把各子代理自报的 `readFiles` 与分配到的审查清单比对，明显缺口以 `medium` 的 `COVERAGE_GAP` 提示浮出，推动子代理逐文件读取自身负责范围；该提示**绝不反转最终判定**，保持裁决稳定性。
- **配置开关**：新增 `reviewer.coverage_validation`（默认 `true`）与 `reviewer.scope_chunk_size`（默认 `25`）。设 `coverage_validation=false` 可关闭覆盖率提示；调整 `scope_chunk_size` 可控制 full 范围单批文件数。

### 修复 / Bug fixes

- `EVIDENCE_VIOLATION` 报告现在定位到具体产生该问题的 review round，便于追责。校验两个策略下的一致实现。
- 证据校验双端（Python/TypeScript）对齐：二进制文件（含 NUL 字节）的锚定行号判为无效，行计数正则与 Python `str.splitlines()` 完全一致。
- 修复非连续轮号时 `findings_by_round` 数组定长与收敛判定逻辑，代理 `aggregateRounds`/`computeConvergence`。

---

## [2.4.0] — 2026-08-19

### 新增 / Features (强制实读到代码的证据审查)

- **强制子代理实际读文件再审查，禁止推测**：reviewer prompt（SKILL.md 审查模板）注入强制 `EVIDENCE RULE`——必须先以 `read_file` 读过待报告的每个文件，才能对其下结论；禁止报告从未读过的代码，编造的文件路径/行号一律视为 poisoned evidence。`line` 对行级问题改为必填（精确读到的行号），整文件/模块级问题用 `0`。
- **硬证据门禁（meta-review）**：`meta-review` 在既有内部一致性校验之外，新增代码证据校验，逐条核对 finding 的 `file`/`line` 是否真实存在于磁盘代码中；任何伪造路径或越界行号都会作为 critical 的 `EVIDENCE_VIOLATION` 浮出，并把最终裁决强制翻转为 `needs_revision`。
- **配置开关**：新增 `reviewer.evidence_validation`（默认 `true`）。设 `false` 可关闭硬门禁，用于不需要严格证据校验的场景。

### 文档 / Docs

- **[SKILL.md](SKILL.md)**：dry-run 审查模板注入 EVIDENCE RULE 并把 `line` 明确为必填；meta-review 说明硬证据门禁；审前 checklist 增加「已注入 EVIDENCE RULE」「已确认证据门禁」验收项。
- **[config.schema.json](config/config.schema.json)** / **[iterate.config.yaml](config/iterate.config.yaml)**：新增 `reviewer.evidence_validation` 字段与默认值、中英释义。

### 测试 / Tests

- 补充证据校验模块测试（文件存在性、行号上下界、read-trace 交叉、整文件/模块级 0 行）与 harness/plugin 两侧对称用例，全套 Python 测试通过。

## [2.3.20] — 2026-08-19

### 新增 / Features (onboarding 高级配置 + 数据一致性)

- **[wizard.py](iterate_cli/wizard.py)**：onboard 向导新增**可选高级配置步骤**（默认关闭），暴露 8 个此前隐藏的旋钮：迭代目标、最大轮数（1–50）、输出语言（zh/en）、原子改动阈值（最大行数/相邻方法数）、git 隔离（worktree / 自动合并）、reviewer 输出 schema 校验、漂移忽略 glob。每个提示以当前值为默认，直接回车即保持原值。输入边界与 `config.schema.json` 约束一致，非法输入保持原值而非崩溃。
- **[generator.py](iterate_cli/generator.py)**：`OnboardingData` 新增 `drift_ignore` 字段并在 `generate_config_yaml` 持久化到 `onboarding.drift_ignore`，保证再次 onboarding/re-onboarding 不再静默丢弃漂移忽略规则。
- **[refresh.py](iterate_cli/refresh.py)**：`_build_refresh_data` 从既有配置回读 `drift_ignore`，增量刷新时保留用户设置的漂移忽略项。
- **[personalize.py](iterate_cli/personalize.py)**：新增**事务化保存** `save_personalization` —— config.yaml 与 ITERATE.md 双文件原子写入；若第二文件写入失败则回滚第一文件至原内容，保证两文件状态一致；回滚自身失败时显式暴露错误而非静默吞掉。`cli.py` 的 `_cmd_personalize` 改用该事务化保存，移除旧的分离式 `_update_iterate_md_user_section`。

### 测试 / Tests

- 新增 `TestSavePersonalizationTransactional`（双文件写入、ITERATE.md 缺失跳过、config 缺失抛错、写入失败精确回滚、回滚失败显式暴露）与 `TestAdvancedConfigWizard`（拒绝保持默认、接受全量变更、空输入保持原值、`_read_optional_int`/`_read_language`/`_read_optional_text`/`_read_drift_ignore` 边界与去重）。
- 全套 Python 测试 **582 全绿**（含既有 drift_ignore 用例，均在本地挂载卷复跑通过）。

## [2.3.19] — 2026-08-18

### 修复 / Fixes (skill CLI + 核心模块)

- **[personalize.py](iterate_cli/personalize.py)**：统一「已知意图 / Known Intentional」段的写入标题，修复该段标题后缀不匹配 `PERSONALIZATION_SECTION_HEADERS` 导致刷新时整段重复累积到 ITERATE.md 的问题。
- **[refresh.py](iterate_cli/refresh.py)**：新增 `_load_refresh_config` 区分配置不存在与配置已损坏（存在但无法解析）。损坏配置改为中止刷新并明确报错，不再被默认值整体覆盖。
- **[cli.py](iterate_cli/cli.py)**：`--version` 改为通过返回值返回 `0`（由 `__main__.py` 以 `sys.exit(main())` 承接），不再直接 `raise SystemExit`；刷新前若无法读取现有 ITERATE.md 则提示并中止，避免静默覆盖手动编辑区。
- **[generator.py](iterate_cli/generator.py)**：原子写入临时文件改为带 uuid 后缀，避免并发冲突；清理/回滚失败不再静默吞错，改为记录日志后抛出。
- **[scan.py](iterate_cli/scan.py)**：TypeScript 项目建议白名单补充 `npm` 前缀，修复 `suggest_command_whitelist` 建议的 `npm run` 无法匹配 `npm test` 等命令的问题。
- **[doctor.py](iterate_cli/doctor.py)**：JSON Schema 校验捕获 `Draft202012Validator` 构造可能抛出的 `SchemaError`，避免 schema 异常时崩溃。
- **[install.py](scripts/install.py)**：`update` 命令语义为「刷新到最新版本」，强制覆盖已安装副本（此前默认跳过已存在文件却仍报成功，产生假成功）。
- **[validate.py](scripts/validate.py)**：命令白名单额外拒绝命令本体中的 shell 链接元字符（`;`、`|`、`&`、`$`、反引号、`>`、`<`、换行等），防止 `白名单前缀; 恶意命令` 绕过后缀拼接。
- **示例与依赖**：`examples/typescript-project.md` 白名单补 `npm`；`examples/python-project.md` 移除无 `specs/` 目录却启用的 `spec-compliance` 维度；`scripts/requirements.txt` 的 jsonschema 统一为 `4.26.0`。

### 测试 / Tests

- 更新 `test_version_flag`（`--version` 返回码而非 SystemExit）与 `test_update_detects_installed_assistants`（update 覆盖语义）两处与旧行为耦合的用例。
- 全套 Python 测试 **536 全绿**。

## [2.3.18] — 2026-08-17

### 修复 / Fixes (skill CLI + validate 脚本)

- **`validation.command_whitelist` 改为可选**：[scripts/validate.py](scripts/validate.py) 此前强制要求该字段为非空列表，与 [config.schema.json](config/config.schema.json)（非必填）及 `iterate doctor`（按可选处理）不一致。现对齐三者：未配置白名单视为可选、跳过白名单结构/合规性校验（运行时仍以 `validation.commands` 为唯一信任源）；已配置但为空列表仍报错。新增 `test_absent_whitelist_is_optional` / `test_absent_whitelist_still_rejects_malformed_commands` 回归用例。
- **GitHub release tarball 不再携带 `harness/`**：[release.yml](.github/workflows/release.yml) 的 `git archive` 此前将整个 `harness/` 打入发布包，与 2.3.17「skill 分发包不携带 harness 源码」的规范不一致。现通过 pathspec `:!harness` 在源头上剔除该目录。
- **ruff 全绿**：清理 `iterate_cli/personalize.py`（SIM102）、`iterate_cli/wizard.py`（SIM114）、`tests/test_install_script.py`（I001/RUF100/SIM117）共 5 处 lint 违规，消除 CI 中 `ruff check scripts/ tests/ iterate_cli/` 的潜在失败。

### 测试 / Tests

- 全套 Python 测试 536 全绿。

## [2.3.17] — 2026-08-17

### 发布规范 / Release (skill CLI + installer)

- **skill 发布包不再携带 `harness/` 源码**：ClawHub / ModelScope / SkillHub 的分发包此前一直夹带 `harness/iterate-plugin`（dsh 插件源码），skill 包不应包含 harness 下两个独立分发子项目的源码。现从所有分发包中剔除整个 `harness/` 目录（ModelScope 精简包 72→51 文件、SkillHub 包 49 文件），并统一升版至 2.3.17 以覆盖 SkillHub 的版本锁。
- 更新 `rebuild_ms.py`（去 harness 出 ModelScope 包）与 `rebuild_skillhub.py`（去 harness + 去 LICENSE 出 SkillHub 包）构建脚本。

## [iterate-plugin 2.6.0] — 2026-08-17（独立版本线）

### 新增 / Features (iterate-plugin)

- **`iterate_history` 历史审计工具**：读取决策日志（支持按 `type` / `since` / `limit` 过滤，默认最新 50 条、上限 200 条）+ 修复注册表汇总（各轮 fixed/failed 计数）。只读不落盘，用于审查运行过程、审计日志、盘点修复明细。
- **`iterate_prune` 运行时清理工具**：清理过期决策日志条目（`retainDays` 默认 30 天）、陈旧断点、孤儿修复备份与空轮次；默认 dry-run 只报告不删除，显式 `dryRun:false` 才真正清理，每次清理写入决策日志。
- **UX — 收敛看板修复计数徽章**：normal 模式在看板显示已修复原子问题计数徽章。
- **UX — 分诊面板一键全选**：可对所有 findings（非仅当前筛选集）批量 y/n/a 判定。
- **UX — 设置区运行时状态概览**：展示 `.iterate/` 产物布局与 `iterate_status` / `iterate_history` / `iterate_prune` 查看/清理指引，支持一键清空分诊数据。

### 代码质量 / 安全 / Security (iterate-plugin)

- 修复多处静默 catch 块：统一记录上下文并向上抛出可诊断错误，杜绝空 catch。
- `iterate_fix` 对 `content` 设字符上限、`iterate_triage` 对 `entries` 设数量上限，防止异常超大负载。
- `applyEntries` 失败回滚逻辑加固，配置写入失败时还原现场。

### 文档 / Docs (iterate-plugin)

- README 全面重写：工具数更新为 13 个并逐条列明、UI 层 6 组件挂载槽位与功能表、`.iterate/` 目录布局图、安全模型（路径防护 / 备份回滚 / dry-run / 参数上限）说明。

### 测试 / Tests (iterate-plugin)

- 新增 `allVerdictKeys`、`buildRuntimeStatusGuide`、`iterate_history`、`iterate_prune` 等用例，共 **212 个单元测试全绿**，类型检查通过。

## [2.3.16] — 2026-08-17

### 修复 / Fixes (skill CLI + installer)

- `install.py`：校验子进程同时解析 stdout + stderr（stdout 诊断不再被吞掉，统一为结构化错误列表）。
- `install.py`：`_validate_github_token` 校验 GitHub PAT 前缀（`ghp_/gho_/ghu_/ghs_/ghr_/github_pat_`）与长度范围（20–256），写入 `--token` 前 fail fast。
- `install.py`：卸载 / 更新删除前新增 `_is_iterate_install_dir` 标识防护，确认目标目录含 `SKILL.md` 才允许 `rmtree`，防止误删非 skill 目录。
- `install.py`：Windows 无 `termios` 环境回退到数字选择，不再崩溃。
- `install.py`：删除未使用的死代码 `_key_value`；stdout 解析改用 `str.removeprefix`（消除 ruff FURB188）。
- `iterate_cli/personalize.py`：`load_personalization_from_config` 拒绝 `fix_priority_order` / `forbidden_fixes` 的标量字符串值，防止手动编辑的 config 被逐字符膨胀进列表。

### 新增 / Features (skill CLI + installer)

- `iterate doctor --json-out <PATH>`：把结构化 Dr.Report 导出到文件（自动创建父目录），便于 CI / 脚本消费健康报告。

### 测试 / Tests

- 新增 `--json-out` 文件导出、`fix_priority_order`/`forbidden_fixes` 标量字符串防御等用例。
- 全套 Python 测试 534 全绿。

## [2.3.15] — 2026-08-16

### 重构 / Refactor (skill CLI installer)

- `install.py` 全部交互函数（`prompt_choice/text/int/bool/int_in_range/dimensions`、`interactive_config`、`config_command`）接入可注入的 `input_func`（默认 `input`），安装 / 更新 / 卸载 / config 向导可无需真实 stdin 端到端测试，UX 输出保持不变。

### 测试 / Tests

- 新增 `tests/test_install_script.py`（75+ 项）：覆盖文件拷贝（必选/可选、dry-run、force）、助手检测与选择、config 管理（init/list/set/交互向导，含校验失败原子回退）、update 发布下载与校验和强制校验、`_safe_extractall` 路径穿越防护、全部交互 prompt。
- 修复测试设置，使向导/`--set` 生成的 config 能通过真实 schema 校验（以真实 master config + 真实 dimensions 作为默认值基准）。
- 全套 Python 测试 532 全绿。

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

## [2.3.14] — 2026-08-16

### 新功能 / Features (skill CLI)
- **`iterate doctor` 全量 JSON Schema 校验**：`run_doctor` 新增 `config.schema` 检查，将 `iterate.config.yaml` 与 `config/config.schema.json` 逐项比对（`additionalProperties:false` 全覆盖），不匹配时以 warn 级别列出前 N 条违规路径，与 `scripts/validate.py` 保持一致。
- **`iterate refresh --dry-run` 预览**：新增 `refresh.preview_refresh`，仅计算不写入，展示 ITERATE.md 增减行数与 iterate.config.yaml 是否变更，用户可在实际刷新前确认影响面。
- **非交互式优雅降级**：`onboard`/`personalize` 向导新增终端交互性检测（`_ensure_interactive`），在管道/重定向/CI 环境下打印指引并以非零状态退出，不再因 `input()` 抛 `EOFError` 崩溃。
- **原子写**：`generator.atomic_write`（临时文件 + `os.replace`）统一应用于 onboarding、refresh、reonboard 的写入路径，配合失败回滚，杜绝半写文件。

### 修复 / Bug Fixes (skill CLI)
- **Bug A — 返回用户自定义配置丢失**：`wizard._load_existing_onboarding_data` 现完整保留 goal/max_rounds/atomic/git/reviewer 等自定义字段，返回用户更新配置时不再静默丢弃。
- **Bug B — `doctor --fix --json` 输出污染**：修复信息整合进 JSON 报告的 `fixes` 字段，移除混入 stdout 的 TUI 文本，保证 `--json` 输出纯净可解析。
- **refresh 幂等化**：`_build_refreshed_config` 仅在指纹实际变化时重写 `completed_at`；`generate_refreshed_md` 原样拼接用户区块（保留原有空行布局）。未漂移时刷新为字节级 no-op，`--dry-run` 正确报告"无需变更"。
- **`_write_refresh_outputs` 引用修复**：统一改用 `atomic_write`，消除重构遗留的未定义 `_atomic_write` 引用。

### 测试 / Tests
- 新增 `config.schema`、`validation.whitelist` 合规、`personalization.consistency`、`refresh --dry-run` 预览、非 TTY 降级等测试；适配原子写后的回滚测试（改 monkeypatch `atomic_write`）。全套 457 个测试通过。

---

## [2.3.13] — 2026-08-16

### 修复 / Bug Fixes (distribution)

- **ClawHub 显示名回归修正**：此前发布流程未显式传 `--name`，导致 ClawHub 上 skill 显示名被默认取为发布目录 basename（`Clawhub Stage 2.3.12`）。本次发布显式指定 `--name Iterate`，恢复为正确显示名 `Iterate`。版本号统一升至 2.3.13 以确保三平台（ClawHub / ModelScope / SkillHub）版本一致。

---

## [2.3.12] — 2026-08-16

### 新功能 / Features (skill CLI)

- **`iterate doctor --fix` 安全自动修复**：补齐"诊断→修复→确认"闭环。`--fix` 仅修复确定性、无损、可逆的配置问题（重复/空维度、非法 language、越界/非整数 max_rounds、空 target_branch、skill_version 漂移），写前自动生成 `.doctorfix-<timestamp>` 备份，随后重跑诊断确认健康。新增 `doctor.apply_safe_fixes` 与 `doctor.run_doctor_fix`。

### 修复 / Bug Fixes (skill CLI)

- **`iterate refresh` 失败提示误导**：此前失败时一律提示 `ITERATE.md not found`，但 `incremental_refresh` 对读取失败、写失败（已打 stderr）同样返回失败。现改为中性的 `Could not read or write ITERATE.md / iterate.config.yaml (see stderr)`，准确反映各类失败原因。
- **`iterate reonboard` 无变更时提示夸大**：`full_reonboard` 对"正常完成"与"返回用户拒绝全部更新（NO_CHANGES_NEEDED）"均返回 True，导致无写入场景也提示 `Full re-onboarding complete`。现将返回值改为 `REONBOARD_*` 状态码（`completed`/`no-changes`/`cancelled`/`failed`），`_cmd_reonboard` 据此输出准确提示。
- **清理死代码**：删除 `doctor._COMMAND_MODULES_KEYS` 未使用常量（其取值 `commands.validation` 本身为错误键名）。

### 新增单元测试 / Tests

- `tests/test_onboarding.py` 的 `full_reonboard` 相关断言更新为 `REONBOARD_*` 状态码；`tests/test_doctor.py` 保留既有 `apply_safe_fixes` / `run_doctor_fix` / CLI `--fix` 用例；全测试集 441 个全绿。

---

## [2.3.11] — 2026-08-16

### 新功能 / Features (skill CLI)

- **`iterate doctor` 补齐 schema 对齐检查**：新增 `max_rounds` 边界（1–50）、`language` 枚举（zh/en）、`dimensions` 非空与唯一性、`validation.command_whitelist` 非空唯一字符串等健康检查，与 `config/config.schema.json` 约束逐一对齐。

### 修复 / Bug Fixes (skill)

- **`jsonschema` 缺失运行时依赖**：`validate` 模块依赖 `jsonschema` 但未在 `pyproject.toml` 声明，导致任意安装用户执行 schema 校验必失败。已补入依赖并固定版本。

### 新增单元测试 / Tests

- `tests/test_doctor.py` 新增空维度、重复维度、越界 `max_rounds`、非法 `language`、非法/合法 `command_whitelist` 等用例；全测试集 429 个全绿。

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
