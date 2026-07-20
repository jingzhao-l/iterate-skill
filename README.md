# Iterate Skill

> 一个可移植、可配置的 AI 编程助手技能：全自动多轮代码审查与修复。
> A portable, configurable AI coding assistant skill: fully automated multi-round code review and fixing.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

---

## 简介 / Introduction

**Iterate Skill** 让 AI 助手像一位严谨的资深工程师一样，对代码库进行多轮审查与修复：

1. 每轮从 **N 个已启用维度** 并行审查整个项目（默认 9 个）。
2. 发现的问题分为两类：
   - **原子问题（Atomic）**：单文件、单函数、≤20 行，直接自动修复。
   - **架构问题（Architectural）**：跨文件、改接口、新增模块，需要用户批准后执行。
3. 每轮修复后自动验证、合并、推送。
4. 循环直到零 findings 或达到轮数上限。

**Iterate Skill** enables your AI assistant to act as a rigorous senior engineer:

1. Run **N parallel dimension reviewers** across the entire codebase each round (default 9).
2. Classify findings into:
   - **Atomic issues**: single file, single function, ≤20 lines — fixed automatically.
   - **Architectural issues**: cross-file, API changes, new modules — executed only after user approval.
3. Validate, merge, and push after each round.
4. Loop until zero findings or max rounds reached.

---

## 特性 / Features

- **可配置多维审查 / Configurable Multi-Dimension Review**：默认 9 维度，可通过 `dimensions` 列表启用/禁用。
- **双轨修复 / Two-Track Fixing**：原子问题自动修，架构问题经审批后修。
- **Git 隔离 / Git Isolation**：每轮在独立分支或 worktree 中完成，通过 merge 回主分支，绝不直接提交到 main/master。
- **多框架适配 / Multi-Framework Adaptation**：支持 Trae、Claude Code、Cursor 等工具，核心流程与工具细节解耦。
- **可配置 / Configurable**：通过 `iterate.config.yaml` 自定义审查维度、验证命令、轮数、语言等。
- **完整审计 / Full Audit Trail**：每轮结果写入 `.iterate_decisions.md`，可追溯、可复盘。

---

## 安装 / Installation

### 方式一：安装脚本（推荐）

```bash
# 克隆到本地
git clone https://github.com/jingzhao-l/iterate-skill.git
cd iterate-skill

# 安装到指定 AI 助手的技能目录
python scripts/install.py --ai trae --target /path/to/project
python scripts/install.py --ai claude --target /path/to/project
python scripts/install.py --ai cursor --target /path/to/project

# 或一次性安装到所有支持的助手
python scripts/install.py --ai all --target /path/to/project
```

### 方式二：手动克隆

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

#### Cursor / 通用

参考 `SKILL.md` 中的"工具映射表"，用 Cursor 的 Agent 模式或自定义脚本实现对应步骤。

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

## 目录结构 / Directory Structure

```text
iterate-skill/
├── SKILL.md                          # 核心技能文件
├── README.md                         # 本文件
├── LICENSE                           # MIT 许可证
├── CONTRIBUTING.md                   # 开源贡献指南
├── config/
│   ├── iterate.config.yaml           # 默认配置（Master）
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
│   └── iterate-decisions.template.md # 决策日志模板
├── scripts/
│   ├── install.py                    # 一键安装脚本
│   ├── validate.py                   # 配置、决策日志、维度校验脚本
│   └── requirements.txt              # 校验脚本依赖
├── tools/
│   ├── SKILL.trae.md                 # Trae 专属实现示例
│   ├── SKILL.claude.md               # Claude Code 专属实现示例
│   └── SKILL.cursor.md               # Cursor / Generic 实现示例
├── tests/
│   └── test_validate.py              # 单元测试
└── .github/
    └── workflows/
        └── ci.yml                    # GitHub Actions CI
```

---

## 核心流程 / Core Workflow

```text
Setup
  └─ 读取项目上下文 → 创建隔离分支/ worktree

Loop (round = 1 .. max_rounds)
  ├─ Phase 1: N 维度并行审查（N = len(dimensions)）
  ├─ Phase 2: 原子问题直接修复
  ├─ Phase 3: 架构问题用户批准 → 子代理串行执行
  ├─ Phase 4: 记录本轮结果
  └─ Phase 5: 验证 → merge 回主分支 → push

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
| `git.push_per_round` | bool | `true` | 每轮通过后是否立即 push |
| `validation.command_whitelist` | list | 常见命令前缀 | 无需二次确认的允许命令前缀 |
| `validation.commands` | object | 示例命令 | 各模块验证命令（**由使用者完全自定义**） |
| `reviewer.output_schema_validation` | bool | `true` | 是否校验 reviewer JSON 输出并自动重试 |

### Master + Overrides 配置模式

借鉴 UI/UX Pro Max 的 Master + Overrides 设计：

- **Master（主配置）**：skill 安装目录下的 `config/iterate.config.yaml`，定义默认值和公共规则。
- **Overrides（项目级覆盖）**：目标项目根目录的 `iterate.config.yaml`，仅声明与 Master 不同的部分。

运行时合并规则：

1. 加载 Master 配置。
2. 若项目根目录存在 `iterate.config.yaml`，则递归覆盖 Master 中的同名字段。
3. `dimensions` 列表如需完全替换而非追加，在 Overrides 中直接写完整列表。

示例：项目只需要 correctness / security 两个维度，且关闭每轮 push：

```yaml
dimensions:
  - correctness
  - security

git:
  push_per_round: false
```

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

## 许可证 / License

[MIT](./LICENSE) © 2026 iterate-skill contributors
