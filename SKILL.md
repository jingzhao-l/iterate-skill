---
name: iterate
description: Fully automated multi-round code iteration with configurable N-dimension parallel review.
version: 1.0.0
---

# /iterate `<goal>` `[rounds]` `[no-limit]`

> 中文：全自动多轮代码迭代。每轮从 N 个已启用维度并行审查整个项目（默认 9 个），原子问题直接修复，架构问题经用户批准后由子代理串行执行，验证通过后合并回主分支并推送，循环直到零 findings 或达到轮数上限。
>
> English: Fully automated multi-round code iteration. Each round launches N parallel dimension reviewers across the project (default 9), fixes atomic issues directly, executes architectural issues after user approval via serial sub-agents, validates, merges into the target branch, pushes, and loops until zero findings or max rounds.

---

## 何时使用 / When to Apply

本 Skill 适用于以下场景：

- 需要系统性提升代码质量、修复潜在 bug 或安全漏洞。
- 项目进入重构、迭代收尾或发布前的审查阶段。
- 需要多维度（正确性、安全、性能、架构等）并行审查。
- 希望将原子问题自动修复，将架构问题经审批后修复。

This Skill is appropriate when:

- You need a systematic code quality improvement, bug fix, or security hardening pass.
- The project is in refactoring, pre-release, or iteration wrap-up phase.
- You want parallel multi-dimension review (correctness, security, performance, architecture, etc.).
- You want atomic issues fixed automatically and architectural issues fixed after approval.

## 何时跳过 / When to Skip

本 Skill 不适用于以下场景：

- 仅需要单次、简单的代码编辑（不需要多轮审查）。
- 项目工作区不干净、存在未提交改动或冲突。
- 没有可用的验证命令（`validation.commands` 未配置）。
- 只需要 UI/UX 设计建议（请使用 UI/UX Pro Max 等专业设计 Skill）。

Do **not** use this Skill when:

- A single, simple edit is sufficient (no multi-round review needed).
- The working tree is dirty, has uncommitted changes, or unresolved conflicts.
- No validation commands are configured in `validation.commands`.
- You only need UI/UX design advice (use a dedicated design Skill like UI/UX Pro Max).

---

## 参数 / Parameters

调用格式 / Invocation: `/iterate <goal> [rounds] [no-limit]`

参数通过 [Agent Skills](https://agentskills.io/) 标准占位符注入：

| 占位符 / Placeholder | 含义 / Meaning | 默认值 / Default |
|---------------------|----------------|------------------|
| `$goal` / `$0` | 迭代目标 / Iteration goal | required |
| `$rounds` / `$1` | 最大轮数 / Max rounds | `7` |
| `$limit_mode` / `$2` | 若设为 `no-limit`，则最大轮数为 50（硬上限）/ Set to `no-limit` for hard cap 50 | — |
| `$ARGUMENTS` | 用户输入的全部参数原样字符串 / Raw argument string | — |

示例 / Examples：
- `/iterate improve error handling`
- `/iterate improve error handling 10`
- `/iterate improve error handling no-limit`

---

## 问题分类标准 / Issue Classification

### 原子问题（Atomic） / Atomic Issues

满足以下**全部**条件：

- 改动在**单个文件**内。
- 改动在**单个函数/方法**内（或最多 3 个相邻的同类方法）。
- 预计改动 ≤ **20 行**（可通过配置调整）。

原子问题**不进入用户审批流程**，由主模型直接修复。

An issue is atomic when **all** of the following are true:

- Changes are within a **single file**.
- Changes are within a **single function/method** (or ≤3 adjacent similar methods).
- Expected changes are ≤ **20 lines** (configurable).

Atomic issues are **fixed directly by the main model** without user approval.

### 架构问题（Architectural） / Architectural Issues

满足以下**任一**条件：

- 跨多个文件。
- 涉及 API / 协议 / 数据模型变更。
- 需要新增类 / 模块 / 文件。
- 预计改动 > **20 行**。

架构问题**必须经用户批准后**才能执行，由子代理串行完成。

An issue is architectural when **any** of the following is true:

- Cross-file changes.
- API / protocol / data model changes.
- New classes / modules / files needed.
- Expected changes are > **20 lines**.

Architectural issues **require user approval** and are executed by sub-agents serially.

**关键原则 / Key Principle**：原子问题和架构问题同样重要，都必须修复。区别仅在于是否需要用户批准以及由谁执行。

---

## 核心流程 / Core Workflow

```text
Setup
  └─ Extract goal → load config → read project context → create isolated branch/worktree

Loop (round = 1 .. max_rounds)
  ├─ Phase 1: N-dimension parallel review (N = enabled dimensions count, default 9)
  ├─ Phase 2: Atomic fixes (direct)
  ├─ Phase 3: Architectural fixes (approval → serial sub-agents)
  ├─ Phase 4: Record round results
  └─ Phase 5: Validate → merge → push

Summary
```

---

## Step 1 — 设定目标与隔离 / Setup

1. **提取目标 / Extract goal**
   - 从 `$0` / `$goal` 读取迭代目标；若缺失则反问用户。
   - Read iteration goal from `$0` / `$goal`; ask if missing.

2. **确定轮数 / Determine max rounds**
   - `maxRounds = $1` / `$rounds`，默认 `7`。
   - 若 `$2` / `$limit_mode` 为 `no-limit`，则 `maxRounds = 50`（硬上限）。
   - 解析失败时默认 `7` 并提示用户。

3. **确定项目根目录 / Locate project root**
   - 以当前工作目录为起点，向上查找包含 `.git`、`iterate.config.yaml` 或 `CLAUDE.md` 的目录。
   - 若向上查找到文件系统根仍未找到，则使用当前工作目录作为项目根目录，并提示用户确认。
   - 该目录即为项目根目录，后续所有文件读取和命令执行均以此为准。

4. **读取配置 / Load configuration**
   - **Master + Overrides 模式**：先加载技能安装目录下的 `config/iterate.config.yaml`（Master），再读取项目根目录的 `iterate.config.yaml`（Overrides）递归覆盖同名字段。
   - 合并规则为**深度合并（deep merge）**：对象字段递归合并键值；Overrides 中的列表字段会**完全替换** Master 中的同名列表（如 `dimensions`、`command_whitelist`）。
   - 若项目根目录不存在 Overrides，则完全使用 Master。
   - 将配置合并到运行参数；若合并后配置无法通过 schema 校验，立即报告错误并中止迭代。

5. **读取项目上下文 / Read project context**
   - 按优先级查找项目根目录的上下文文件：`CLAUDE.md` → `PROJECT.md` → `README.md`。
   - 提取项目名、架构、技术栈、代码规范；若都不存在，使用简要描述。
   - 构造 `projectContext` 字符串供后续使用。
   - 绝不读取 `.env`、`.env.*`、`*.{key,pem,p12,crt,cer}`、`credentials.json`、`.aws/`、`.ssh/` 等敏感文件。

6. **创建隔离环境 / Create isolated environment**
   - 检查 `git status`，工作区必须干净（无未跟踪文件、无未提交修改、无未解决冲突）。
   - 若工作区不干净，询问用户是否 commit/stash；若用户拒绝或取消，**中止本次迭代**。
   - 记录当前分支名，作为迭代结束后的返回目标。
   - 创建迭代分支：`iterate/<goal-slug>-<timestamp>`。
   - 或创建 git worktree：`git worktree add ../<name> -b iterate/<goal-slug>-<timestamp>`。
   - 若分支/worktree 创建失败（如名称冲突），尝试追加递增序号后重试，最多 3 次；仍失败则中止并告知用户。
   - 所有后续操作都在该分支/worktree 中进行。

7. **初始化决策日志 / Initialize decision log**
   - 在隔离环境根目录创建 `.iterate_decisions.md`，写入文件头。
   - Initialize `deferredArchitectural = []` for cross-round carry-over.

---

## Step 2 — 迭代循环 / Iteration Loop

```
round = 1
while round <= maxRounds:
```

### Phase 1 — 并行审查 / Parallel Review

启动 **N 个并行审查子代理**（N = 启用的 dimensions 数量，默认 9），每个审查一个维度。

Launch **N parallel reviewer sub-agents** (N = enabled dimensions count, default 9), one per dimension.

#### 可用审查维度 / Available Review Dimensions

以下维度可通过 `dimensions` 列表启用或禁用（默认 9 个）。每个维度的中文名、英文名、优先级和 focus prompt 定义在 `config/dimensions/<key>.yaml` 中；`config/dimensions.yaml` 保留为聚合兼容文件。

| 维度 / Dimension | 优先级 / Priority | 关注点 / Focus |
|------------------|-------------------|---------------|
| correctness | critical | 崩溃风险、逻辑错误、竞态条件、类型不匹配、静默吞错 |
| security | critical | 注入、路径遍历、硬编码密钥、输入校验、权限提升 |
| performance | high | N+1 查询、主线程阻塞、循环引用、O(n²)、启动瓶颈 |
| architecture | high | 模块边界违规、循环依赖、God Object、缺失抽象 |
| style-tests | medium | 函数 >80 行、圈复杂度 >15、嵌套 >3、魔法数字、缺失测试 |
| tech-debt | medium | TODO/FIXME/HACK、废弃 API、临时方案、硬编码配置 |
| spec-compliance | high | 对照 specs/ 目录，发现未实现功能、规范偏离 |
| frontend-backend | high | API/RPC 一致性、数据字段、错误传播、事件流覆盖 |
| ui-ux | medium | 加载/空/错误状态、导航、响应式断点、无障碍 |

每个子代理的任务提示：

```text
Review the codebase for {DIMENSION} issues ONLY.

Scope: {review.scope}
- "full"      → review the ENTIRE codebase.
- "changed-only" → review ONLY files changed in the current round (git diff against {git.target_branch}).
- 当 `review.scope` 为 `changed-only` 且本轮相对于 `target_branch` 无改动文件时，自动 fallback 为 `full`。

Focus: {focus description}

Project context: {projectContext}

For each finding, report:
- file, line (if applicable), severity (critical/high/medium/low)
- dimension, summary, failure_scenario, suggested_fix
- is_atomic (boolean): true if fix is ≤{atomic.max_lines} lines within a SINGLE function/file;
  false if cross-file, new files, API changes, or large refactoring.

Return strictly as JSON: { "findings": [...] }
Each finding object must contain: file, severity, dimension, summary, failure_scenario, suggested_fix, is_atomic.
If no issues are found, return { "findings": [] }.
```

#### 工具映射 / Tool Mapping

| 工具 / Tool | Trae | Claude Code | Cursor / Generic |
|-------------|------|-------------|------------------|
| 并行审查子代理 | `Task` × N (type: `search` or `general_purpose_task`) | `Workflow` / `Agent` × N | 手动或脚本并行运行 |
| 按目录拆分审查 | `Task` per directory/module | `Agent` per directory/module | 脚本分组 |
| 结果汇总 | `Task` (type: `general_purpose_task`) | `Agent` synthesize | 人工汇总 |
| reviewer 输出 schema 校验 | 主模型 JSON parse + field check | 主模型 JSON parse + field check | 脚本校验 |
| 用户审批 | `AskUserQuestion` | `EnterPlanMode` / `ExitPlanMode` | 对话确认 |
| 文件编辑 | `Read` / `Edit` / `Write` | `Read` / `Edit` / `Write` | IDE 编辑 |
| 执行命令 | `RunCommand` | `Bash` | Terminal |
| 配置校验 | `python scripts/validate.py config ...` | `python scripts/validate.py config ...` | 同左 |

#### 支持的 AI 助手与安装路径 / Supported Assistants

使用 `scripts/install.py install --ai <name> --target <project>` 即可安装到对应目录：

| AI 助手 / Assistant | 安装路径 / Install Path |
|---------------------|------------------------|
| Trae | `.trae/skills/iterate/` |
| Claude Code | `.claude/skills/iterate/` |
| Cursor | `.cursor/skills/iterate/` |
| Windsurf | `.windsurf/skills/iterate/` |
| GitHub Copilot | `.github/skills/iterate/` |
| OpenAI Codex | `.codex/skills/iterate/` |
| Roo Code | `.roo/skills/iterate/` |
| Qoder | `.qoder/skills/iterate/` |
| Gemini CLI | `.gemini/skills/iterate/` |
| OpenCode | `.opencode/skills/iterate/` |
| Continue | `.continue/skills/iterate/` |
| Augment | `.augment/skills/iterate/` |
| Warp | `.warp/skills/iterate/` |

安装脚本会自动复制 `SKILL.md`、配置、维度定义、校验脚本和模板到对应目录；`--ai all` 一次性安装到所有支持的助手目录。

常用 CLI 选项：
- `--force`：覆盖已存在的 skill 文件。
- `--global`：安装到用户主目录（如 `~/.trae/skills/iterate/`），供所有项目复用。
- `uninstall --yes`：卸载已安装的 skill；不加 `--yes` 时会要求二次确认。
- `update`：检测已安装的助手并从 GitHub 最新 release 下载源码刷新文件；下载失败时回退到本地源码。

#### 按模块/目录拆分 / Split by Module or Directory

当项目较大时，可将一个维度拆分为多个子任务，每个任务只审查一个模块或目录：

```text
Split dimension {DIMENSION} review by top-level directories.
For each directory, launch a reviewer with scope "changed-only" or "full".
Merge findings, removing duplicates across directory boundaries.
```

#### 子代理失败处理 / Sub-agent Failure

若某个 reviewer 子代理失败、超时或返回无效输出：

1. 若输出非严格 JSON 且 `reviewer.output_schema_validation` 为 true，针对该子代理最多重试 2 次，每次在 prompt 中强调返回严格 JSON。
2. 若仍失败，记录失败原因到 `.iterate_decisions.md`。
3. 使用 `AskUserQuestion` / 对话确认询问用户：
   - 继续（continue）：忽略该失败，按当前已收集的 findings 继续。
   - 跳过该维度（skip）：该维度本轮不产生 findings。
   - 中止本轮（abort round）：直接退出本轮循环，进入 Phase 4 记录后结束。

> 若选择 skip 或 abort，仍应将失败原因写入决策日志，避免遗漏审查维度。

#### 汇总与分类 / Synthesize and Classify

使用一个汇总子代理：

```text
Synthesize findings from all reviewers.

Goal: {goal} / Round: {round}

Steps:
1. PARSE each reviewer output as JSON; if invalid and reviewer.output_schema_validation is true, retry that reviewer up to 2 times.
2. REMOVE duplicates (same defect, same file → keep most detailed)
3. REMOVE false positives (clearly wrong or unactionable)
4. RE-VALIDATE is_atomic flag for each finding
5. CLASSIFY into atomic and architectural
6. SORT each group by severity (critical → high → medium → low)
7. TRIM each group to 20 max

Return: { "empty": boolean, "atomic": [...], "architectural": [...] }
```

停止条件检查：

```text
if empty AND deferredArchitectural is empty:
    写入 .iterate_decisions.md: "Round {round}: 0 findings, iteration complete."
    输出: "✅ Round {round}: 0 findings, iteration complete."
    break
```

> **注意 / Note**：如果所有 reviewer 都返回空但代码中明显存在问题，主模型应基于自身判断补充 findings。

---

### Phase 2 — 原子问题直接修复 / Atomic Fixes

若存在原子问题：

1. **计划（内部，不中断） / Plan internally**
   - 分析所有原子 findings。
   - 合并对同一文件的修改。
   - 按严重程度和依赖排序。
   - 输出简短计划列表告知用户。

2. **顺序执行 / Execute sequentially**

   ```text
   for each atomic finding:
       Read target file
       Apply fix using Edit/Write (ensure ≤ atomic.max_lines, single function scope)
       Record completion status
   ```

3. **验证原子修复 / Validate atomic fixes**

   根据改动的模块跑对应检查（从 `validation.commands` 读取，键名为示例）：

   - 确定本轮修改涉及的模块集合：根据修改文件的路径、扩展名或目录结构匹配 `validation.commands` 中的模块键名。
   - 若改动涉及多个模块，依次执行每个模块对应的命令列表。
   - 若某模块未在 `validation.commands` 中配置命令，跳过并提示用户补充配置。
   - 任一模块验证失败即停止后续检查，进入失败处理流程。

   示例 / Examples：

   - `python/`：`ruff check src/ && mypy src/ --ignore-missing-imports && pytest tests/ -x -q --timeout=60`
   - `swift/`：`swift build -c debug`
   - `typescript/`：`npm run compile`

   执行前检查命令前缀是否在 `validation.command_whitelist` 中；不在白名单中的命令必须二次确认。

   若验证失败：
   - 追加 `.iterate_decisions.md`：`Atomic fix validation failed: {details}`
   - 输出：`❌ Round {round}: atomic fix validation failed, stopping iteration`
   - **回滚本轮所有原子修改**：`git reset --hard HEAD`（仍在迭代分支上，不影响 main/master）。
   - 将本轮已识别但未执行的架构问题保留在 `deferredArchitectural` 中，供下次 `/iterate` 会话处理。
   - `break`

---

### Phase 3 — 架构问题修复 / Architectural Fixes

若存在架构问题（含 `deferredArchitectural`）：

1. **文件碰撞检测 / File conflict detection**
   - 收集 Phase 2 修改过的所有文件。
   - 对每个架构 finding，检查其文件是否与原子修复文件重叠。
   - 重叠 → 移入 `deferredArchitectural`（下一轮处理）。
   - 不重叠 → 移入 `executableArchitectural`。

2. **分组与排序 / Group and sort**
   - 按模块依赖顺序排序（先被依赖，后依赖者）。
   - 合并同一模块/文件组的 finding 为一个 task。
   - 检测 `executableArchitectural` 内部 task 之间的文件重叠；如有重叠，按依赖顺序拆分为串行 task 或合并为单一 task。
   - 最终确保不同 task 之间的文件集互不重叠。

3. **用户审批 / User approval**

   呈现给用户：

   ```text
   可执行的架构修复 / Executable architectural tasks:
   - {files} | {description} | {severity} | {approach}

   延迟的架构修复 / Deferred tasks:
   - {files} | {description} | {reason}

   Approve these {N} architectural fixes?
   ```

   - 批准 → 继续执行。
   - 拒绝 → 全部 executable 移入 `deferredArchitectural`，跳到 Phase 4。

4. **串行委派子代理 / Execute serially via sub-agents**

   ```text
   for each task in executableArchitectural:
       Use sub-agent with prompt:

       "You are fixing an architectural issue.

       Goal: {goal} / Round: {round}
       Project context: {projectContext}

       Task: {task description with file paths, findings, approach}

       Workflow:
       1. Read all affected files, their callers, and callees.
       2. Apply the fix using Edit/Write tools.
       3. Report: success/failure, files_changed, summary, notes.

       Previous tasks in this round may have changed some files.
       Read files fresh before editing — they may have been modified.
       Do NOT run build/test commands."

       Wait for completion before starting the next task.
       If a sub-agent fails, log the reason, report it to the user, and ask whether to continue, skip, or abort the round.
   ```

5. **整体验证 / Full validation**

   根据改动模块跑完整验证（同 Phase 2，但覆盖所有改动模块）。

   执行前同样检查 `validation.command_whitelist`。

   若失败：
   - 追加 `.iterate_decisions.md`：`Full validation failed: {details}`
   - 输出：`❌ Round {round}: full validation failed, stopping iteration`
   - **回滚本轮所有修改**（原子 + 已执行架构）：`git reset --hard iterate/round-{round}-backup`（或 `git reset --hard HEAD`），仍在迭代分支上，不影响 main/master。
   - 将未执行的架构问题保留在 `deferredArchitectural` 中。
   - `break`

---

### Phase 4 — 记录本轮结果 / Record Round Results

追加到 `.iterate_decisions.md`：

- 原子修复列表 + 状态
- 架构修复列表（已执行 + 延迟 + 原因）
- 修改范围审计：本轮修改的文件清单、每个文件对应的 task/reviewer、审批状态
- AI 重要决策

输出：`✅ Round {round} complete`

---

### Phase 5 — 验证、合并、推送 / Validate, Merge, Push

每轮验证通过后：

1. **Backup tag / 备份标签**
   - 在 commit 前为当前迭代分支打标签：`git tag iterate/round-{round}-backup`
   - 若后续需要回滚，可 `git reset --hard iterate/round-{round}-backup`（仅用于迭代分支，不用于 main/master）。

2. **Commit / 提交**
   - `git add <changed files>`
   - `git commit -m "fix: iterate round {round} — {brief summary}"`

3. **Merge / 合并**
   - `git checkout {target_branch}`
   - `git merge iterate/<goal-slug>-<timestamp>`
   - 如有冲突，先尝试自动解决；若无法自动解决，**停止合并并询问用户**手动解决或跳过本轮。
   - 冲突解决后重新验证，验证失败则切回迭代分支，**不推进 main/master**。

4. **Push / 推送**
   - 若 `git.push_per_round` 为 `true`：
     - `git push origin {target_branch}`
     - 若被拒绝，先 `git pull --rebase`，解决冲突，重新验证，再 push。
     - push-pull-rebase 循环最多执行 3 次；超过仍失败则停止并告知用户手动处理。
     - **绝不 force-push 到 main/master**。
   - 若 `git.push_per_round` 为 `false`：
     - 本轮回不 push，只保留本地 merge。
     - 在最后一轮或会话结束时，一次性 `git push origin {target_branch}`；同样遵循 3 次循环限制。

5. **切回迭代分支 / Switch back**
   - `git checkout iterate/<goal-slug>-<timestamp>`
   - 继续下一轮。

6. **记录 / Log**
   - 在 `.iterate_decisions.md` 中记录 backup tag、commit hash、merge 结果、冲突处理。

```
round += 1
```

---

## Step 3 — 汇总报告 / Summary Report

迭代结束后输出：

- 总轮数 / Total rounds
- 停止原因 / Stop reason
- 每轮原子修复数 + 架构修复数 / Per-round atomic + architectural fix counts
- 剩余延迟架构问题（如有）/ Remaining deferred architectural issues
- `.iterate_decisions.md` 路径 / Decision log path
- 迭代分支名 / Iteration branch name

---

## Git 隔离工作流 / Git Isolation Workflow

**规则 / Rule**：每次 `/iterate` 会话必须在隔离的本地分支或 worktree 中运行；每轮修复验证通过后，必须合并回本地主分支、解决冲突并推送到远程。**绝不直接在 main/master 上提交**。

**Why**：
- 保持主工作区稳定。
- 每轮都是独立可审查、可回滚的 commit。
- 远程始终保存最新验证状态。

### 每会话流程 / Per-Session Flow

```bash
# 1. Setup
git status                                          # 必须干净
git checkout -b iterate/<goal>-<date>               # 或 git worktree add ../<name> -b iterate/<goal>-<date>

# 2. Each round (after validation passes)
git add <changed files> && git commit -m "fix: iterate round {N} — ..."
git checkout <target-branch>
git merge iterate/<goal>-<date>                     # 解决冲突，重新验证
git push origin <target-branch>
git checkout iterate/<goal>-<date>                  # 继续下一轮

# 3. Session end
# 确保所有改动已合并推送
# 可询问用户是否删除已合并的迭代分支
```

### 会话中断与恢复 / Session Interruption and Resume

若会话因用户关闭、AI 异常或验证失败而中断：

1. 保留当前迭代分支和 `.iterate_decisions.md`，不要删除。
2. 下次调用 `/iterate` 时，先读取 `.iterate_decisions.md` 确定：
   - 上次的迭代分支名。
   - 已完成的轮数、`deferredArchitectural` 列表。
   - 是否有未 push 的本地 merge。
3. 若工作区干净且迭代分支存在，询问用户：
   - 继续上次会话（resume）：切回迭代分支，从下一轮开始。
   - 重新开始（restart）：创建新迭代分支，`deferredArchitectural` 可继承或清空。
4. 若上一轮已合并到 main/master 但未 push，在 resume 时先完成 push。

### 护栏 / Guardrails

- 循环中绝不直接提交到 main/master。
- 绝不 force-push 到 main/master。
- Push 被拒绝时，先 `git pull --rebase`，解决冲突，重新验证，再 push。
- 若某轮验证失败，**不要合并该轮**，留在迭代分支上并告知用户。

---

## 决策日志格式 / Decision Log Format

文件路径：`.iterate_decisions.md`

```markdown
# Iterate Decision Log

Goal: {goal}
Max rounds: {maxRounds}
Started: {timestamp}
Branch: {iteration-branch}

---

## Round {N} — {timestamp}

### Atomic Fixes (Direct)
| # | File | Summary | Severity | Status |
|---|------|---------|----------|--------|
| 1 | x.swift | Fix null pointer | high | ✅ |

### Architectural Fixes (Approved + Executed)
| # | File(s) | Summary | Severity | Status |
|---|---------|---------|----------|--------|
| 1 | y.swift, z.swift | Unified error handling | critical | ✅ Executed |

### Architectural Fixes (Deferred to Next Round)
| # | File(s) | Summary | Defer Reason |
|---|---------|---------|-------------|
| 1 | a.swift, b.swift | Refactor data flow | File conflict with atomic fix |

### Reverted Fixes
| # | File(s) | Summary | Revert Reason |
|---|---------|---------|---------------|
| 1 | shared/error_codes.json | Merge v1 codes | Conflict with authoritative v2.0 numbering |

### AI Important Decisions
| # | Decision | Reason |
|---|---------|--------|
| 1 | Merged 5 findings into 1 task | Same module |

### Validation
- ruff check src/ → 0 errors
- mypy src/ → Success
- pytest tests/ → 2600 passed, 0 failed
```

---

## Skill 目录结构 / Skill Directory Layout

一个完整的 iterate skill 目录应包含以下文件（相对 `SKILL.md` 的路径固定）：

```text
iterate/
├── SKILL.md                          # 技能入口与使用说明
├── config/
│   ├── iterate.config.yaml           # 默认配置
│   ├── config.schema.json            # iterate.config.yaml 的 JSON Schema
│   ├── dimensions.yaml               # 聚合版维度定义（兼容旧版）
│   └── dimensions/                   # 数据驱动的维度定义
│       ├── correctness.yaml
│       ├── security.yaml
│       ├── performance.yaml
│       ├── architecture.yaml
│       ├── style-tests.yaml
│       ├── tech-debt.yaml
│       ├── spec-compliance.yaml
│       ├── frontend-backend.yaml
│       └── ui-ux.yaml
├── scripts/
│   ├── install.py                    # CLI：安装、卸载、配置、校验
│   ├── validate.py                   # 配置、决策日志、维度校验脚本
│   └── requirements.txt              # 校验脚本依赖
├── templates/
│   └── iterate-decisions.template.md # 决策日志模板
├── tools/
│   ├── SKILL.trae.md                 # Trae 专属 prompt/workflow 示例
│   ├── SKILL.claude.md               # Claude Code 专属 workflow 示例
│   └── SKILL.cursor.md               # Cursor 专属 prompt 示例
├── tests/
│   └── test_validate.py              # pytest 测试
└── README.md / CONTRIBUTING.md       # 用户与贡献者文档
```

运行时优先读取**项目根目录**的 `iterate.config.yaml`；若不存在，则使用 skill 目录下的 `config/iterate.config.yaml` 作为默认配置。校验脚本路径以 `${CLAUDE_SKILL_DIR}/scripts/validate.py`（Claude Code）或 skill 安装目录相对路径解析。

---

## 配置说明 / Configuration

默认配置见 [`config/iterate.config.yaml`](./config/iterate.config.yaml)。

| 配置项 / Key | 类型 / Type | 默认值 / Default | 说明 / Description |
|--------------|-------------|------------------|--------------------|
| `goal` | string | `"Improve code quality"` | 迭代目标 |
| `max_rounds` | int | `7` | 最大轮数 |
| `language` | string | `"en"` | 输出语言 `zh` / `en` |
| `dimensions` | list | 全部 9 维度 | 启用的审查维度 |
| `review.scope` | string | `"full"` | 审查范围：`changed-only` / `full` |
| `atomic.max_lines` | int | `20` | 原子问题行数上限 |
| `atomic.max_adjacent_methods` | int | `3` | 相邻方法数上限 |
| `git.target_branch` | string | `"main"` | 合并目标分支 |
| `git.use_worktree` | bool | `false` | 是否使用 worktree |
| `git.push_per_round` | bool | `true` | 每轮通过后是否立即 push |
| `validation.command_whitelist` | list | 常见命令前缀 | 无需二次确认的允许命令前缀 |
| `validation.commands.<module>` | list | 示例命令 | 各模块验证命令 |
| `reviewer.output_schema_validation` | bool | `true` | 是否校验 reviewer JSON 输出并自动重试 |

---

## 安全与敏感信息保护 / Security & Sensitive Data

1. **所有 AI 操作不读取敏感文件 / No sensitive file access**
   - 主模型、reviewer 子代理、架构修复子代理均不得读取敏感文件，包括但不限于：
     `.env`、`.env.*`、`*.key`、`secrets/`、`*.pem`、`*.p12`、`*.crt`、`*.cer`、
     `credentials.json`、`.aws/`、`.ssh/`。
   - `projectContext` 中不得包含 API 密钥、密码、Token、数据库连接字符串、私钥内容。
   - 执行命令时避免将敏感文件作为参数或输出内容。

2. **命令白名单 / Command whitelist**
   - 默认白名单：`ruff`, `mypy`, `pytest`, `swift`, `npm run`, `yarn`, `pnpm`, `go test`, `cargo`, `python`, `python3` 等已知前缀。
   - 不在白名单中的 `validation.commands` 必须经用户二次确认后方可执行。
   - 可用 `python scripts/validate.py config <path>` 提前检查命令合规性。

3. **修改范围审计 / Modification scope audit**
   - 每轮 `.iterate_decisions.md` 必须记录：本轮修改的文件、对应 task/reviewer、用户审批状态。
   - 子代理只允许修改任务描述中的文件；越权修改必须报告并中止。

4. **No force-push / No direct main commits**
   - 绝不 force-push 到 `main`/`master`。
   - 绝不直接在 `main`/`master` 上提交。

## Reviewer Prompt 质量检查清单 / Reviewer Prompt Quality Checklist

在启动 reviewer 前确认：

- [ ] 已注入 `projectContext`，但不含密钥。
- [ ] 已明确 `review.scope`（`changed-only` 或 `full`）。
- [ ] 已说明 `atomic.max_lines` 和 `atomic.max_adjacent_methods`。
- [ ] 已要求返回严格 JSON 并列出必填字段。
- [ ] 已说明禁止读取敏感文件。
- [ ] 大项目已按目录/模块拆分 reviewer 任务。

## 重要注意事项 / Important Notes

1. **项目上下文动态读取 / Dynamic context**：从 `CLAUDE.md` 或 `iterate.config.yaml` 读取，不硬编码。
2. **原子修复不中断 / Atomic fixes are non-blocking**：主模型直接执行，不需要用户批准。
3. **架构修复串行 / Architectural fixes are serial**：按依赖顺序逐个执行，后面的子代理能看到前面的改动。
4. **文件碰撞显式延迟 / File collisions are explicitly deferred**：不依赖 reviewer 再次发现。
5. **原子验证失败立即停止 / Atomic validation failure stops iteration**：不进入 Phase 3。
6. **主模型可补充 findings / Main model can supplement findings**：当 reviewer 遗漏明显问题时。
7. **Git 隔离强制 / Git isolation is mandatory**：所有工作发生在 `iterate/*` 分支或 worktree；每轮验证后合并并推送。
8. **完整审计 / Full audit trail**：`.iterate_decisions.md` 记录所有修复、延迟、回滚和重要决策。
9. **验证命令安全 / Validation command safety**：`iterate.config.yaml` 中的 `validation.commands` 由 AI 助手读取后执行；执行前检查 `validation.command_whitelist`，不在白名单的命令需用户确认。
