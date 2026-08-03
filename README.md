# Iterate Skill

> 一个可移植、可配置的 AI 编程助手技能：全自动多轮代码审查与修复。
> A portable, configurable AI coding assistant skill: fully automated multi-round code review and fixing.

[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](./LICENSE)
[![skills.sh](https://img.shields.io/badge/-skills.sh-222222?logo=github&logoColor=white)](https://skills.sh/jingzhao-l/iterate-skill)
[![ClawHub](https://img.shields.io/badge/-ClawHub.ai-4285F4?logo=cloudflare&logoColor=white)](https://clawhub.ai/jingzhao-l/skills/iterate-skill)
[![SkillHub CN](https://img.shields.io/badge/-SkillHub.cn-2385bb?logo=codeberg&logoColor=white)](https://www.skillhub.cn/skills/iterate-skill)
[![ModelScope](https://img.shields.io/badge/-ModelScope-624aff?logo=alibabacloud&logoColor=white)](https://www.modelscope.cn/skills/jingzhao0/iterate-skill)


---

## 简介 / Introduction

**Iterate Skill** 让 AI 助手像一位严谨的资深工程师一样，对代码库进行多轮审查与修复：

1. 每轮从 **N 个已启用维度** 并行审查整个项目（默认 9 个）。
2. 发现的问题分为两类：
   - **原子问题（Atomic）**：单文件、单函数、≤20 行，直接自动修复。
   - **架构问题（Architectural）**：跨文件、改接口、新增模块，需要用户批准后执行。
3. 每轮修复后自动验证；合并与推送由配置控制（默认不自动 merge/push，secure-by-default）。
4. 循环直到零 findings 或达到轮数上限。

**Iterate Skill** enables your AI assistant to act as a rigorous senior engineer:

1. Run **N parallel dimension reviewers** across the entire codebase each round (default 9).
2. Classify findings into:
   - **Atomic issues**: single file, single function, ≤20 lines — fixed automatically.
   - **Architectural issues**: cross-file, API changes, new modules — executed only after user approval.
3. Validate after each round; merge and push are config-controlled (default: no auto merge/push, secure-by-default).
4. Loop until zero findings or max rounds reached.

---

## 特性 / Features

- **可配置多维审查 / Configurable Multi-Dimension Review**：默认 9 维度，可通过 `dimensions` 列表启用/禁用。
- **双轨修复 / Two-Track Fixing**：原子问题自动修，架构问题经审批后修。
- **Git 隔离 / Git Isolation**：每轮在独立分支或 worktree 中完成，通过 merge 回主分支，绝不直接提交到 main/master。
- **Secure-by-default**：`push_per_round` 和 `auto_merge` 默认 `false`，不自动 push/merge；回滚使用非破坏性 `git restore`，避免数据丢失。
- **命令白名单双层强制 / Dual-Layer Command Whitelist**：配置时校验 + 个性化硬白名单，拒绝 shell 链接元字符和非白名单命令前缀。
- **强制校验和验证 / Mandatory Checksum Verification**：`update` 命令下载 release tarball 时强制 SHA256 校验，缺失或不匹配则拒绝下载。
- **多框架适配 / Multi-Framework Adaptation**：支持 Trae、Claude Code、Cursor、Windsurf、GitHub Copilot、Codex、Roo Code 等 13+ 工具，核心流程与工具细节解耦。
- **可配置 / Configurable**：通过 `iterate.config.yaml` 自定义审查维度、验证命令、轮数、语言等。
- **完整审计 / Full Audit Trail**：每轮结果写入 `.iterate_decisions.md`，可追溯、可复盘。

---

## 安装 / Installation

### 方式一：skills.sh CLI（推荐）

```bash
# 安装到当前项目（自动识别并配置支持的 AI 助手）
npx skills add jingzhao-l/iterate-skill

# 全局安装（所有项目可用）
npx skills add jingzhao-l/iterate-skill --global

# 仅安装到指定助手
npx skills add jingzhao-l/iterate-skill --agent claude-code
npx skills add jingzhao-l/iterate-skill --agent trae
```

skills.sh 会自动将 `SKILL.md`、配置和脚本复制到对应 AI 助手的技能目录。

### 方式二：npm 一键安装器

如果你不想手动克隆仓库，可以直接用我们发布的 npm 包，一条命令完成下载、校验、安装：

```bash
# 全局安装（自动检测 AI 助手并交互选择）
npx iterate-skill-installer

# 仅安装到指定助手
npx iterate-skill-installer --ai trae
npx iterate-skill-installer --ai cursor

# 安装到指定项目目录
npx iterate-skill-installer --target /path/to/project

# 强制覆盖已安装的技能
npx iterate-skill-installer --ai trae --global --force
```

该安装器会自动从 GitHub latest release 下载源码，校验 SHA256 校验和，创建隔离的 Python 环境并安装依赖，最后调用 `scripts/install.py` 完成安装。

### 方式三：CLI 脚本

```bash
# 克隆到本地
git clone https://github.com/jingzhao-l/iterate-skill.git
cd iterate-skill

# 安装到指定 AI 助手的技能目录
python scripts/install.py install --ai trae --target /path/to/project
python scripts/install.py install --ai claude --target /path/to/project
python scripts/install.py install --ai cursor --target /path/to/project

# 或一次性安装到所有支持的助手
python scripts/install.py install --ai all --target /path/to/project

# 查看所有支持的工具
python scripts/install.py install --help
```

已支持：Trae、Claude Code、Cursor、Windsurf、GitHub Copilot、OpenAI Codex、Roo Code、Qoder、Gemini CLI、OpenCode、Continue、Augment、Warp。

> 旧版调用方式 `python scripts/install.py --ai trae --target ...` 仍兼容。
>
> 常用选项：
> - `--force`：覆盖已存在的 skill 文件。
> - `--global`：安装到用户主目录（如 `~/.trae/skills/iterate/`），供所有项目复用。

```bash
# 全局安装（所有项目可用）
python scripts/install.py install --ai trae --global

# 覆盖更新已安装的 skill
python scripts/install.py install --ai trae --target /path/to/project --force

# 卸载
python scripts/install.py uninstall --ai trae --target /path/to/project --yes

# 检测已安装的助手并从 GitHub 最新 release 刷新
python scripts/install.py update --target /path/to/project

# 强制刷新指定助手
python scripts/install.py update --ai trae --target /path/to/project --force

# 使用 GitHub Token 避免 API 限流（update 会下载最新 release）
python scripts/install.py update --ai trae --target /path/to/project --token ghp_xxx
```

### 方式四：安装 iterate CLI（onboarding 命令行工具）

```bash
# 从仓库安装（提供 iterate 命令）
pip install .
# 或使用 pipx 隔离安装
pipx install .

# 验证安装
iterate --version
```

安装后可在任何项目目录中使用 `iterate` 命令。模板文件（`ITERATE.template.md`）已打包进 wheel，无需额外配置：

```bash
# 交互式 onboarding 向导（多路引导：首次/非首次自动分支）
iterate onboard

# 个性化配置（项目中途追加约束，9 步向导）
iterate personalize

# 查看 onboarding 状态和漂移检测
iterate status

# 增量刷新（重新扫描，保留用户手写区）
iterate refresh

# 完整重新 onboarding（备份旧文件后重做）
iterate reonboard
```

> CLI onboarding 适用于对项目有清晰认知的用户；AI onboarding（在 AI 工具中调用 `/iterate`）适用于需要自动扫描代码库的场景。两者产出相同格式的文件。
>
> **多路引导 / Multi-Path Flow**：
> - **首次 onboarding**（无 ITERATE.md）：确认手动配置 → 基础 onboarding → 询问是否需要个性化配置。
> - **非首次 onboarding**（已有 ITERATE.md）：询问是否更新基础配置（不建议手动改，建议用 `iterate refresh`）→ 询问是否进行个性化配置或遇到问题。
>
> **个性化配置 / Personalization**：捕获 AI 扫描不到的项目专属约束（禁区、风险区、已知意图、维度定制等 9 类）。运行 `iterate personalize` 可在项目中途随时追加，无需重做 onboarding。

### 方式五：手动克隆

#### Trae

```bash
git clone https://github.com/jingzhao-l/iterate-skill.git ~/.trae/skills/iterate
```

或复制 `SKILL.md` 到项目内的 `.trae/skills/iterate/SKILL.md`。

#### Claude Code

```bash
git clone https://github.com/jingzhao-l/iterate-skill.git ~/.claude/skills/iterate
```

或复制 `SKILL.md` 到项目内的 `.claude/skills/iterate/SKILL.md`。

#### Cursor / 其他工具

参考 `SKILL.md` 中的"工具映射表"，用对应 AI 助手的 Agent 模式或自定义脚本实现对应步骤。`scripts/install.py` 会自动将文件放到 `.cursor/skills/iterate/`、`.windsurf/skills/iterate/` 等目录。

---

## 快速开始 / Quick Start

在项目根目录创建 `iterate.config.yaml`（可选，会使用默认值）：

```yaml
# 示例：Python + Swift 混合项目
# 注意：validation 下的命令只是示例，务必按你项目真实的工具链修改。
goal: "提升代码质量，确保所有函数 ≤80 行且测试通过"
max_rounds: 7
language: zh

dimensions:
  - correctness
  - security
  - performance
  - architecture
  - style-tests
  - tech-debt
  - spec-compliance
  - frontend-backend
  - ui-ux

validation:
  command_whitelist:
    - "ruff"
    - "mypy"
    - "pytest"
    - "swift"
    - "npm run"
  commands:
    python:
      - "ruff check src/"
      - "mypy src/ --ignore-missing-imports"
      - "pytest tests/ -x -q --timeout=60"
    swift:
      - "swift build -c debug"
    typescript:
      - "npm run compile"
```

然后在对话中触发：

```text
/iterate "提升代码质量，确保所有函数 ≤80 行且测试通过"
# 或指定轮数
/iterate "提升代码质量" 10
# 或不设轮数上限（硬上限 50）
/iterate "提升代码质量" no-limit
```

---

## Onboarding（项目知识库初始化）

首次在项目中调用 `/iterate` 时，skill 会检查项目根目录是否存在 `ITERATE.md`。若不存在，将触发 onboarding 流程，为当前项目生成定制化知识库与配置。

### 两条通道 / Two Channels

| 通道 / Channel | 适用场景 / Suitable When | 产出 / Output |
|----------------|-------------------------|---------------|
| **AI Onboarding**（在 AI 工具中触发） | 用户希望 AI 自动扫描代码库、识别技术栈 | `ITERATE.md` + `iterate.config.yaml`（含指纹） |
| **CLI Onboarding**（终端运行 `iterate onboard`） | 用户对项目有清晰认知，愿手动确认技术栈和命令 | 同上，格式完全一致 |

### AI Onboarding 流程

1. AI 扫描 manifest 文件、目录树、`specs/`、`tests/`、`README.md` 等（只读，不碰敏感文件）。
2. 参考 `templates/onboarding-playbook.md` 中的映射表（**仅供参考，按项目实况调整**）。
3. 草拟 `ITERATE.md`（AI 维护区 + 用户维护区）和 `iterate.config.yaml`。
4. 展示摘要（含拟写入的 `validation.commands` 逐条），用户确认后才写入。
5. 写入后继续正常迭代。

### 漂移检测 / Drift Detection

每次调用 `/iterate` 时，若 `onboarding.drift_check: true`，会重新计算 manifest 文件（`package.json`、`pyproject.toml` 等）的 SHA-256 并与配置中存储的指纹比对：

- **无漂移** → 静默通过。
- **有漂移**（新增/删除/内容变更）→ 非阻塞警告，用户可选：
  - **继续**：照旧使用现有知识库。
  - **增量刷新**：AI 重新扫描，只更新 `ITERATE.md` 的 AI 维护区，保留用户手写区。
  - **完整重新 onboarding**：备份旧文件后重做。

### ITERATE.md 结构

文件分为两个区域，刷新时只更新 AI 维护区：

- `<!-- ITERATE:AI-MAINTAINED:START -->` ~ `END`：项目概述、技术栈、模块地图、推荐维度、iterate 注意点。
- `<!-- ITERATE:USER-OWNED:START -->` ~ `END`：自定义代码约定、禁区与风险区、手动批注。

### 全局安装 vs 项目级安装

- **全局安装**的 skill：每个项目首次调用都会触发单项目 onboarding。
- **项目级安装**的 skill：onboarding 完成后，后续调用直接复用 `ITERATE.md`。

---

## 个性化配置 / Personalization

AI 扫描能发现技术栈和目录结构，但无法发现项目专属的约束和经验。个性化配置让你把这些知识沉淀下来，让 iterate 更懂你的项目。

### 9 类个性化配置

| 类别 / Category | 说明 / Description | 存储位置 / Storage |
|----------------|-------------------|-------------------|
| **禁区 / Protected Paths** | iterate 不得修改的文件/目录（glob 模式） | `iterate.config.yaml` |
| **风险区 / Risk Areas** | 改动需架构审批的文件/目录（path + reason） | `iterate.config.yaml` |
| **已知意图 / Known Intentional** | 抑制误报（file:line + dimension + reason） | `iterate.config.yaml` |
| **维度定制 / Dimension Focus** | 为特定维度追加 focus 内容 | `iterate.config.yaml` |
| **优先修复顺序 / Fix Priority** | 维度修复优先级（从高到低） | `iterate.config.yaml` |
| **禁止的修复方式 / Forbidden Fixes** | 不可使用的修复手法（如 `# noqa`） | `iterate.config.yaml` |
| **Iterate 注意点 / Notes** | 经验教训、已知陷阱 | `ITERATE.md` 用户区 |
| **自定义代码约定 / Conventions** | 项目特有的代码规范 | `ITERATE.md` 用户区 |
| **补充验证命令 / Extra Validation** | 项目特有的验证命令（合并到 `validation.commands`） | `iterate.config.yaml` |

### 使用方式

```bash
# 方式一：onboarding 时顺便配置个性化
iterate onboard
# 基础 onboarding 完成后，向导会询问是否有个性化要求

# 方式二：项目中途随时追加个性化配置
iterate personalize
# 直接进入 9 步个性化向导，跳过基础 onboarding
```

每步支持 `[a]dd / [r]emove / [s]kip` 操作。已有配置会被加载，可在其基础上增量修改。

### 配置示例

```yaml
# iterate.config.yaml 中的 personalization 段
personalization:
  protected_paths:
    - "legacy/**"
    - "vendor/**"
  risk_areas:
    - path: "src/auth/"
      reason: "认证模块，任何改动需架构审批"
  known_intentional:
    - file: "db/queries.py"
      line: 42
      dimension: "tech-debt"
      reason: "使用 any 是性能优化，非技术债"
  dimension_focus:
    - dimension: "security"
      focus: "SQL 注入（项目历史上有过事故）"
  fix_priority_order:
    - security
    - correctness
    - performance
  forbidden_fixes:
    - "try-catch 吞错"
    - "# noqa"
    - "// @ts-ignore"
```

---

## 目录结构 / Directory Structure

```text
iterate-skill/
├── SKILL.md                          # 核心技能文件
├── README.md                         # 本文件
├── LICENSE                           # MIT 许可证
├── CONTRIBUTING.md                   # 开源贡献指南
├── pyproject.toml                    # iterate CLI 包定义
├── skills.sh.json                    # skills.sh 仓库分组配置
├── config/
│   ├── iterate.config.yaml           # 默认配置（Master，含 onboarding 段）
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
├── examples/
│   ├── python-project.md             # Python 项目示例
│   ├── swift-project.md              # Swift 项目示例
│   └── typescript-project.md         # TypeScript 项目示例
├── templates/
│   ├── ITERATE.template.md           # 项目知识库模板（AI + 用户双区）
│   ├── onboarding-playbook.md        # AI onboarding 参考映射表
│   └── iterate-decisions.template.md # 决策日志模板
├── iterate_cli/                      # onboarding CLI 源码
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                        # 入口：onboard/personalize/refresh/reonboard/status
│   ├── wizard.py                     # 交互式 CLI 向导（多路引导）
│   ├── personalize.py                # 个性化配置向导（9 步）
│   ├── scan.py                       # 项目技术栈扫描
│   ├── fingerprint.py                # manifest SHA-256 指纹
│   ├── generator.py                  # ITERATE.md / config 生成
│   ├── refresh.py                    # 增量刷新与重新 onboarding
│   └── data/
│       └── ITERATE.template.md       # 打包到 wheel 的模板副本（pip install 后使用）
├── scripts/
│   ├── install.py                    # CLI：安装、卸载、配置、校验
│   ├── validate.py                   # 配置、决策日志、维度校验脚本
│   └── requirements.txt              # 校验脚本依赖
├── tools/
│   ├── SKILL.trae.md                 # Trae 专属实现示例
│   ├── SKILL.claude.md               # Claude Code 专属实现示例
│   └── SKILL.cursor.md               # Cursor / Generic 实现示例
├── tests/
│   ├── test_validate.py              # 校验脚本单元测试
│   └── test_onboarding.py            # onboarding CLI 单元测试
└── .github/
    └── workflows/
        ├── ci.yml                    # GitHub Actions CI
        └── release.yml               # 发布工作流
```

---

## 核心流程 / Core Workflow

```text
Step 0 — Onboarding Check
  └─ 定位项目根 → 检查 ITERATE.md → 漂移检测 →（缺失则触发 AI Onboarding）

Setup
  └─ 提取 goal → 加载配置 → 读取项目上下文（ITERATE.md → CLAUDE.md → …）→ 创建隔离分支/worktree

Loop (round = 1 .. max_rounds)
  ├─ Phase 0: 维度规划（仅第 1 轮，goal 指定范围时 → 调整 focus → 用户确认）
  ├─ Phase 1: N 维度并行审查（N = len(dimensions)，默认 9）
  ├─ Phase 2: 原子问题直接修复（单文件/单函数/≤20 行）
  ├─ Phase 3: 架构问题用户批准 → 子代理串行执行
  ├─ Phase 4: 记录本轮结果
  └─ Phase 5: 验证 → merge（若 auto_merge=true）→ push（若 push_per_round=true）

Summary
```

详细流程请参考 [`SKILL.md`](./SKILL.md)。

---

## 配置 / Configuration

默认配置位于 [`config/iterate.config.yaml`](./config/iterate.config.yaml)。

项目级配置：在目标项目根目录创建 `iterate.config.yaml`，AI 助手会优先读取。

配置项说明：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `goal` | string | `"Improve code quality"` | 迭代目标 |
| `max_rounds` | int | `7` | 最大轮数 |
| `language` | string | `"en"` | 输出语言：`zh` / `en` |
| `dimensions` | list | 全部 9 维度 | 启用的审查维度 |
| `review.scope` | string | `"full"` | 审查范围：`changed-only` 增量 / `full` 全量 |
| `atomic.max_lines` | int | `20` | 原子问题最大行数 |
| `git.target_branch` | string | `main` | 合并目标分支 |
| `git.push_per_round` | bool | `false` | 每轮通过后是否立即 push（默认 false，安全） |
| `git.auto_merge` | bool | `false` | 每轮验证后是否自动 merge 回 target_branch（默认 false，安全） |
| `validation.command_whitelist` | list | 常见命令前缀 | 无需二次确认的允许命令前缀 |
| `validation.commands` | object | 示例命令 | 各模块验证命令（**由使用者完全自定义**） |
| `reviewer.output_schema_validation` | bool | `true` | 是否校验 reviewer JSON 输出并自动重试 |
| `onboarding.version` | string | `"1.0"` | onboarding 指纹 schema 版本 |
| `onboarding.drift_check` | bool | `true` | 每次调用时是否检查 manifest 漂移 |
| `onboarding.fingerprints` | list | `[]` | manifest 文件 SHA-256 指纹（onboarding 后自动填充） |
| `personalization.protected_paths` | list | `[]` | 禁区 glob 模式，iterate 不得修改 |
| `personalization.risk_areas` | list | `[]` | 风险区（path + reason），改动需架构审批 |
| `personalization.known_intentional` | list | `[]` | 已知意图（file:line + dimension + reason），抑制误报 |
| `personalization.dimension_focus` | list | `[]` | 维度定制（dimension + focus），追加 focus 到维度 prompt |
| `personalization.fix_priority_order` | list | `[]` | 修复优先级顺序（从高到低） |
| `personalization.forbidden_fixes` | list | `[]` | 禁止的修复方式（如 `# noqa`、`try-catch 吞错`） |
| `personalization.version` | string | `"1.0"` | personalization schema 版本（自动管理，勿手动编辑） |

> **补充验证命令**：`personalization.extra_validation_commands` 在向导中收集，同时存放在 `personalization.extra_validation_commands`（用于 round-trip）和 `validation.commands`（用于 runner 执行），命令前缀自动加入 `validation.command_whitelist`。

### Master + Overrides 配置模式

借鉴 UI/UX Pro Max 的 Master + Overrides 设计：

- **Master（主配置）**：skill 安装目录下的 `config/iterate.config.yaml`，定义默认值和公共规则。
- **Overrides（项目级覆盖）**：目标项目根目录的 `iterate.config.yaml`，仅声明与 Master 不同的部分。

运行时合并规则：

1. 加载 Master 配置。
2. 若项目根目录存在 `iterate.config.yaml`，则递归覆盖 Master 中的同名字段。
3. `dimensions` 列表如需完全替换而非追加，在 Overrides 中直接写完整列表。

示例：项目只需要 correctness / security 两个维度，且关闭每轮 push 和自动 merge：

```yaml
dimensions:
  - correctness
  - security

git:
  push_per_round: false
  auto_merge: false
```

### 命令行配置 / CLI Configuration

除了手动编辑 `iterate.config.yaml`，还可以用 `scripts/install.py config` 在命令行快速管理配置：

```bash
# 在项目根目录生成 iterate.config.yaml（从 Master 复制）
python scripts/install.py config --init --target /path/to/project

# 查看当前项目配置
python scripts/install.py config --list --target /path/to/project

# 非交互式修改单个字段（支持嵌套键）
python scripts/install.py config --set goal="Fix all bugs" --target /path/to/project
python scripts/install.py config --set max_rounds=10 --target /path/to/project
python scripts/install.py config --set dimensions='[correctness, security, performance]' --target /path/to/project
python scripts/install.py config --set review.scope=changed-only --target /path/to/project
python scripts/install.py config --set validation.commands.python='["ruff check src/", "pytest tests/ -q"]' --target /path/to/project

# 交互式配置向导（推荐新手使用）
python scripts/install.py config --interactive --target /path/to/project

# 校验项目配置
python scripts/install.py validate --target /path/to/project
```
> `--set` 的值会按 YAML/JSON 语义解析，因此列表、数字、布尔值都可以直接写入。`--set` 保存后会自动用 schema 校验，不合法时会回滚，避免产生无效配置。注意 YAML 1.1 会把 `yes`/`no`/`on`/`off` 当作布尔值，CLI 中仅 `true`/`false` 会被识别为布尔，其余保留为字符串。

---

## 贡献 / Contributing

欢迎提交 Issue 和 PR！

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feat/your-feature`
3. 提交改动：`git commit -m "feat: description"`
4. 推送分支：`git push origin feat/your-feature`
5. 创建 Pull Request

请保持 SKILL.md 的中英双语结构，新增功能需补充配置示例。

---

## 安全说明 / Security

- **高自主性**：本 skill 会自主执行文件编辑、`git` 操作以及 `validation.commands` 中配置的命令。所有修改先在隔离分支/worktree 中进行，架构修复必须经用户批准。
- **Secure-by-default Git 操作**：`push_per_round` 和 `auto_merge` 默认均为 `false`——不会自动 push 到远程，也不会自动 merge 回主分支。需用户在配置中显式设为 `true` 才会执行。回滚操作使用非破坏性命令（`git restore`），避免 `git reset --hard` 的数据丢失风险。
- **命令白名单（双层强制）**：
  - **配置时校验**：`scripts/validate.py` 检查 `validation.commands` 中每条命令是否以 `validation.command_whitelist` 中的前缀开头，不合规则报错。
  - **个性化硬白名单**：`iterate personalize` 中添加 `extra_validation_commands` 时，只接受 30+ 预批准的工具前缀（pytest/ruff/mypy/eslint/swift/cargo 等），拒绝 shell 链接元字符（`;`、`|`、`&` 等），不在白名单中的命令**直接拒绝**，不可通过确认绕过。
- **敏感文件**：skill 运行过程中不会读取 `.env`、密钥、凭证等敏感文件；`projectContext` 中也不得包含密钥内容。
- **Update 命令**：`python scripts/install.py update` 会从 GitHub Release 下载最新源码。下载前会提示确认（`--yes` 跳过）。**强制 SHA256 校验**：下载 release tarball 时必须验证校验和，若 release 缺少 `SHA256SUMS.txt` 或校验和不匹配，拒绝下载并回退到本地源码。

## 许可证 / License

[MIT](./LICENSE) © 2026 iterate-skill contributors
