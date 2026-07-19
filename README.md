# Iterate Skill

> 一个可移植、可配置的 AI 编程助手技能：全自动多轮代码审查与修复。
> A portable, configurable AI coding assistant skill: fully automated multi-round code review and fixing.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

---

## 简介 / Introduction

**Iterate Skill** 让 AI 助手像一位严谨的资深工程师一样，对代码库进行多轮审查与修复：

1. 每轮从 **9 个维度** 并行审查整个项目。
2. 发现的问题分为两类：
   - **原子问题（Atomic）**：单文件、单函数、≤20 行，直接自动修复。
   - **架构问题（Architectural）**：跨文件、改接口、新增模块，需要用户批准后执行。
3. 每轮修复后自动验证、合并、推送。
4. 循环直到零 findings 或达到轮数上限。

**Iterate Skill** enables your AI assistant to act as a rigorous senior engineer:

1. Run **9 parallel dimension reviewers** across the entire codebase each round.
2. Classify findings into:
   - **Atomic issues**: single file, single function, ≤20 lines — fixed automatically.
   - **Architectural issues**: cross-file, API changes, new modules — executed only after user approval.
3. Validate, merge, and push after each round.
4. Loop until zero findings or max rounds reached.

---

## 特性 / Features

- **9 维度审查 / 9-Dimension Review**：正确性、安全、性能、架构、风格与测试、技术债、规范一致性、前后端一致性、UI/UX。
- **双轨修复 / Two-Track Fixing**：原子问题自动修，架构问题经审批后修。
- **Git 隔离 / Git Isolation**：每轮在独立分支或 worktree 中完成，通过 merge 回主分支，绝不直接提交到 main/master。
- **多框架适配 / Multi-Framework Adaptation**：支持 Trae、Claude Code、Cursor 等工具，核心流程与工具细节解耦。
- **可配置 / Configurable**：通过 `iterate.config.yaml` 自定义审查维度、验证命令、轮数、语言等。
- **完整审计 / Full Audit Trail**：每轮结果写入 `.iterate_decisions.md`，可追溯、可复盘。

---

## 安装 / Installation

### Trae

将本仓库克隆到 Trae 的技能目录：

```bash
git clone https://github.com/jingzhao-l/iterate-skill.git ~/.trae/skills/iterate
```

或复制 `SKILL.md` 到项目内的 `.trae/skills/iterate/SKILL.md`。

### Claude Code

```bash
git clone https://github.com/jingzhao-l/iterate-skill.git ~/.claude/skills/iterate
```

或复制 `SKILL.md` 到项目内的 `.claude/skills/iterate/SKILL.md`。

### Cursor / 通用

参考 `SKILL.md` 中的"工具映射表"，用 Cursor 的 Agent 模式或自定义脚本实现对应步骤。

---

## 快速开始 / Quick Start

在项目根目录创建 `iterate.config.yaml`（可选，会使用默认值）：

```yaml
# 示例：Python + Swift 混合项目
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
  vm:
    - "ruff check src/"
    - "mypy src/ --ignore-missing-imports"
    - "pytest tests/ -x -q --timeout=60"
  host:
    - "swift build -c debug"
  ide-plugin:
    - "npm run compile"
```

然后在对话中触发：

```text
/iterate "提升代码质量，确保所有函数 ≤80 行且测试通过"
```

---

## 目录结构 / Directory Structure

```text
iterate-skill/
├── SKILL.md                          # 核心技能文件
├── README.md                         # 本文件
├── LICENSE                           # MIT 许可证
├── config/
│   ├── iterate.config.yaml           # 默认配置
│   └── dimensions.yaml               # 9 维度定义与 prompt
├── examples/
│   ├── python-project.md             # Python 项目示例
│   ├── swift-project.md              # Swift 项目示例
│   └── typescript-project.md         # TypeScript 项目示例
├── templates/
│   └── iterate-decisions.template.md # 决策日志模板
└── scripts/
    └── validate.py                   # 决策日志格式校验脚本
```

---

## 核心流程 / Core Workflow

```text
Setup
  └─ 读取项目上下文 → 创建隔离分支/ worktree

Loop (round = 1 .. max_rounds)
  ├─ Phase 1: 9 维度并行审查
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
| `dimensions` | list | 9 维度 | 启用的审查维度 |
| `validation` | object | 按语言默认 | 各模块验证命令 |
| `atomic.max_lines` | int | `20` | 原子问题最大行数 |
| `git.target_branch` | string | `main` | 合并目标分支 |

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

[MIT](./LICENSE) © 2026 Zynthara AI contributors
