---
name: iterate
description: |
  Multi-round automated code iteration: 9-dimension parallel review → atomic fixes directly →
  architectural fixes via user approval → validate → merge → push, looping until zero findings.
description_zh: |
  全自动多轮代码迭代：9 维度并行审查 → 原子问题直接修复 → 架构问题用户批准后执行 →
  验证 → 合并 → 推送，循环至零 findings。
---

# /iterate `<goal>` `[--rounds N]` `[--no-limit]`

> 中文：全自动多轮代码迭代。每轮从 9 个维度并行审查整个项目，原子问题直接修复，架构问题经用户批准后由子代理串行执行，验证通过后合并回主分支并推送，循环直到零 findings 或达到轮数上限。
>
> English: Fully automated multi-round code iteration. Each round launches 9 parallel dimension reviewers across the project, fixes atomic issues directly, executes architectural issues after user approval via serial sub-agents, validates, merges into the target branch, pushes, and loops until zero findings or max rounds.

---

## 参数 / Parameters

| 参数 / Parameter | 默认值 / Default | 说明 / Description |
|------------------|------------------|--------------------|
| `<goal>` | required | 迭代目标 / Iteration goal |
| `--rounds N` | `7` | 最大轮数 / Max rounds |
| `--no-limit` | — | 不设上限（硬上限 50）/ Unlimited (hard cap 50) |

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
  ├─ Phase 1: 9-dimension parallel review
  ├─ Phase 2: Atomic fixes (direct)
  ├─ Phase 3: Architectural fixes (approval → serial sub-agents)
  ├─ Phase 4: Record round results
  └─ Phase 5: Validate → merge → push

Summary
```

---

## Step 1 — 设定目标与隔离 / Setup

1. **提取目标 / Extract goal**
   - 从用户输入中提取 `<goal>`；若缺失则反问用户。
   - Extract `<goal>` from user input; ask if missing.

2. **确定轮数 / Determine max rounds**
   - `maxRounds = 7`（默认）。
   - 若指定 `--rounds N`，则 `maxRounds = N`。
   - 若指定 `--no-limit`，则 `maxRounds = 50`（硬上限）。

3. **确定项目根目录 / Locate project root**
   - 以当前工作目录为起点，向上查找包含 `.git`、`iterate.config.yaml` 或 `CLAUDE.md` 的目录。
   - 该目录即为项目根目录，后续所有文件读取和命令执行均以此为准。

4. **读取配置 / Load configuration**
   - 优先读取项目根目录的 `iterate.config.yaml`。
   - 若不存在，使用本技能安装目录下的 `config/iterate.config.yaml` 作为默认配置。
   - 将配置合并到运行参数。

5. **读取项目上下文 / Read project context**
   - 读取项目根目录的 `CLAUDE.md`（若存在），提取项目名、架构、技术栈、代码规范。
   - 若不存在，使用简要描述。
   - 构造 `projectContext` 字符串供后续使用。

6. **创建隔离环境 / Create isolated environment**
   - 检查 `git status`，工作区必须干净（无未跟踪文件、无未提交修改、无未解决冲突）；若不干净，询问用户是否 commit/stash。
   - 记录当前分支名，作为迭代结束后的返回目标。
   - 创建迭代分支：`iterate/<goal-slug>-<timestamp>`。
   - 或创建 git worktree：`git worktree add ../<name> -b iterate/<goal-slug>-<timestamp>`。
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

启动 **9 个并行审查子代理**，每个审查一个维度。

Launch **9 parallel reviewer sub-agents**, one per dimension.

#### 9 个审查维度 / 9 Review Dimensions

| 维度 / Dimension | 关注点 / Focus |
|------------------|---------------|
| correctness | 崩溃风险、逻辑错误、竞态条件、类型不匹配、静默吞错 |
| security | 注入、路径遍历、硬编码密钥、输入校验、权限提升 |
| performance | N+1 查询、主线程阻塞、循环引用、O(n²)、启动瓶颈 |
| architecture | 模块边界违规、循环依赖、God Object、缺失抽象 |
| style-tests | 函数 >80 行、圈复杂度 >15、嵌套 >3、魔法数字、缺失测试 |
| tech-debt | TODO/FIXME/HACK、废弃 API、临时方案、硬编码配置 |
| spec-compliance | 对照 specs/ 目录，发现未实现功能、规范偏离 |
| frontend-backend | API/RPC 一致性、数据字段、错误传播、事件流覆盖 |
| ui-ux | 加载/空/错误状态、导航、响应式断点、无障碍 |

每个子代理的任务提示：

```text
Review the codebase for {DIMENSION} issues ONLY.

Scope: {review.scope}
- "full"      → review the ENTIRE codebase.
- "changed-only" → review ONLY files changed in the current round (git diff against {git.target_branch}).

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

#### 按模块/目录拆分 / Split by Module or Directory

当项目较大时，可将一个维度拆分为多个子任务，每个任务只审查一个模块或目录：

```text
Split dimension {DIMENSION} review by top-level directories.
For each directory, launch a reviewer with scope "changed-only" or "full".
Merge findings, removing duplicates across directory boundaries.
```

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

> **注意 / Note**：如果 9 个 reviewer 都返回空但代码中明显存在问题，主模型应基于自身判断补充 findings。

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

   根据改动的模块跑对应检查（从 `validation.commands` 读取）：

   - `vm/`：`ruff check src/ && mypy src/ --ignore-missing-imports && pytest tests/ -x -q --timeout=60`
   - `host/`：`swift build -c debug`
   - `ide-plugin/`：`npm run compile`

   执行前检查命令前缀是否在 `validation.command_whitelist` 中；不在白名单中的命令必须二次确认。

   若验证失败：
   - 追加 `.iterate_decisions.md`：`Atomic fix validation failed: {details}`
   - 输出：`❌ Round {round}: atomic fix validation failed, stopping iteration`
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
   - 如有冲突，立即解决；解决后重新验证。

4. **Push / 推送**
   - 若 `git.push_per_round` 为 `true`：
     - `git push origin {target_branch}`
     - 若被拒绝，先 `git pull --rebase`，解决冲突，重新验证，再 push。
     - **绝不 force-push 到 main/master**。
   - 若 `git.push_per_round` 为 `false`：
     - 本轮回不 push，只保留本地 merge。
     - 在最后一轮或会话结束时，一次性 `git push origin {target_branch}`。

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

## 配置说明 / Configuration

默认配置见 [`config/iterate.config.yaml`](./config/iterate.config.yaml)。

| 配置项 / Key | 类型 / Type | 默认值 / Default | 说明 / Description |
|--------------|-------------|------------------|--------------------|
| `goal` | string | `"Improve code quality"` | 迭代目标 |
| `max_rounds` | int | `7` | 最大轮数 |
| `language` | string | `"en"` | 输出语言 `zh` / `en` |
| `dimensions` | list | 9 维度 | 启用维度 |
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

1. **Reviewer 不读取敏感文件 / No sensitive file access**
   - reviewer 子代理不得读取 `.env`、`*.key`、`secrets/`、`*.pem`、`*.p12`、`credentials.json` 等文件。
   - `projectContext` 中不得包含 API 密钥、密码、Token、数据库连接字符串。

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
