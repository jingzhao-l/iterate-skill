# Iterate Skill

> 一个可移植、可配置的 AI 编程助手技能：全自动多轮代码审查与修复。
> A portable, configurable AI coding assistant skill: fully automated multi-round code review and fixing.

[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](./LICENSE)
[![npm](https://img.shields.io/badge/-npm-CB3837?logo=npm&logoColor=white)](https://www.npmjs.com/package/iterate-skill-installer)
[![ClawHub](https://img.shields.io/badge/-ClawHub.ai-4285F4?logo=cloudflare&logoColor=white)](https://clawhub.ai/jingzhao-l/skills/iterate-skill)
[![SkillHub CN](https://img.shields.io/badge/-SkillHub.cn-2385bb?logo=codeberg&logoColor=white)](https://www.skillhub.cn/skills/jingzhao-l/iterate-skill)
[![ModelScope](https://img.shields.io/badge/-ModelScope-624aff?logo=alibabacloud&logoColor=white)](https://www.modelscope.cn/skills/jingzhao0/iterate-skill)

---

## 简介 / Introduction

**Iterate Skill** 让 AI 助手像一位严谨的资深工程师一样，对代码库进行多轮审查与修复。

每轮它会并行审查整个项目，区分两类问题：

- **原子问题（Atomic）**：单文件、单函数、≤20 行，直接自动修复。
- **架构问题（Architectural）**：跨文件、改接口、新增模块，需要用户批准后执行。

修复后自动验证，循环直到零问题或达到轮数上限。合并与推送默认关闭，安全优先。

**Iterate Skill** enables your AI assistant to act as a rigorous senior engineer. Each round it reviews the entire codebase in parallel, classifies findings as atomic (auto-fixed) or architectural (user-approved), validates fixes, and loops until clean or the round limit is reached. Merge and push are opt-in by default.

---

## 一分钟了解 / At a Glance

| 能力 | 说明 |
|---|---|
| **9 维度并行审查** | correctness、security、performance、architecture、style-tests、tech-debt、spec-compliance、frontend-backend、ui-ux |
| **双轨修复** | 小问题自动修，大问题先问你再修 |
| **Git 隔离** | 每轮在独立分支/worktree 中完成，不直接写 main/master |
| **Secure-by-default** | `push_per_round` 和 `auto_merge` 默认 `false` |
| **命令白名单** | 配置时 + 个性化时双层校验，拒绝危险 shell 元字符 |
| **校验和验证** | 从 GitHub Release 更新时强制 SHA256 校验 |
| **多助手支持** | Trae、Claude Code、Cursor、Windsurf、GitHub Copilot、Codex、Roo Code 等 25+ 工具 |
| **项目知识库** | 自动生成 `ITERATE.md` + `iterate.config.yaml`，支持漂移检测和增量刷新 |

---

## 安装 / Installation

### 推荐方式一：npm 一键安装器（一条命令）

适合大多数用户。无需克隆仓库，自动从 GitHub Release 下载、校验、安装：

```bash
# 全局安装（自动检测已安装的 AI 助手并交互选择）
npx iterate-skill-installer

# 仅安装到指定助手
npx iterate-skill-installer --ai trae
npx iterate-skill-installer --ai cursor
npx iterate-skill-installer --ai claude

# 安装到指定项目目录
npx iterate-skill-installer --target /path/to/project

# 强制覆盖已安装的技能
npx iterate-skill-installer --ai trae --global --force
```

> 该安装器会自动创建隔离的 Python 环境、安装依赖、调用 `scripts/install.py` 完成安装。需要 Python 3.10+。

### 推荐方式二：安装 iterate CLI

如果你更喜欢在终端里完成 onboarding 和个性化配置：

```bash
# 克隆仓库后安装
pip install .
# 或使用 pipx 隔离安装
pipx install .

# 验证
iterate --version
```

安装后可在任意项目目录使用：

```bash
iterate onboard      # 交互式 onboarding 向导
iterate personalize  # 9 步个性化配置
iterate status       # 查看 onboarding 状态和漂移
iterate refresh      # 增量刷新
iterate reonboard    # 完整重新 onboarding
```

### 手动方式：源码脚本

适合开发者或需要完全控制安装过程：

```bash
git clone https://github.com/jingzhao-l/iterate-skill.git
cd iterate-skill

# 安装到指定助手
python scripts/install.py install --ai trae --target /path/to/project

# 全局安装
python scripts/install.py install --ai trae --global

# 覆盖更新
python scripts/install.py install --ai trae --global --force

# 从 GitHub Release 刷新
python scripts/install.py update --ai trae --target /path/to/project

# 卸载
python scripts/install.py uninstall --ai trae --target /path/to/project --yes
```

### 最简方式：复制 SKILL.md

如果只需要让某个 AI 助手认识这个 skill，把 `SKILL.md` 复制到对应目录即可：

```bash
# Trae
mkdir -p ~/.trae/skills/iterate
cp SKILL.md ~/.trae/skills/iterate/SKILL.md

# Claude Code
mkdir -p ~/.claude/skills/iterate
cp SKILL.md ~/.claude/skills/iterate/SKILL.md

# Cursor
mkdir -p ~/.cursor/skills/iterate
cp SKILL.md ~/.cursor/skills/iterate/SKILL.md
```

具体路径请参考 [`SKILL.md`](./SKILL.md) 中的“工具映射表”。

### 全局安装 vs 项目级安装

- **全局安装**：skill 文件放在用户主目录（如 `~/.trae/skills/iterate`），每个项目首次调用 `/iterate` 都会触发一次 onboarding。
- **项目级安装**：skill 文件放在项目内的 `.trae/skills/iterate` 等目录，onboarding 完成后直接复用项目根目录的 `ITERATE.md`。

---

## 快速开始 / Quick Start

安装完成后，在目标项目根目录执行 onboarding：

```bash
# 方式 A：使用 AI 助手（自动扫描代码库）
# 在 AI 助手对话中输入 /iterate，首次会触发 onboarding

# 方式 B：使用终端（适合对项目已有清晰了解）
cd /path/to/project
iterate onboard
```

onboarding 会生成两个文件：

- `ITERATE.md`：项目知识库（技术栈、模块地图、约定、禁区等）
- `iterate.config.yaml`：迭代配置（目标、维度、验证命令等）

然后就可以开始迭代：

```text
/iterate "提升代码质量，确保所有函数 ≤80 行且测试通过"
```

---

## 使用方式 / Usage

### 在 AI 助手中

安装 skill 后，在支持该技能的 AI 工具中输入：

```text
/iterate "你的目标"
/iterate "你的目标" 10
/iterate "你的目标" no-limit
```

### 在终端中

```bash
# 交互式 onboarding（首次/非首次会自动分支）
iterate onboard

# 中途追加个性化约束
iterate personalize

# 查看状态和漂移检测
iterate status

# 增量刷新（保留 ITERATE.md 用户手写区）
iterate refresh

# 完整重新 onboarding（备份旧文件）
iterate reonboard
```

---

## Onboarding（项目知识库初始化）

首次调用 `/iterate` 时，skill 会检查项目根目录是否存在 `ITERATE.md`。若不存在，触发 onboarding。

### 两条通道

| 通道 | 适用场景 | 产出 |
|---|---|---|
| **AI Onboarding** | 希望 AI 自动扫描代码库、识别技术栈 | `ITERATE.md` + `iterate.config.yaml` |
| **CLI Onboarding** | 对项目有清晰认知，愿手动确认技术栈 | 同上 |

### ITERATE.md 结构

文件分为两个区域：

- `<!-- ITERATE:AI-MAINTAINED:START -->`：AI 维护区，刷新时会更新。
- `<!-- ITERATE:USER-OWNED:START -->`：用户维护区，手写约定、禁区、风险区，刷新时保留。

### 漂移检测

每次调用 `/iterate` 时，会重新计算 `package.json`、`pyproject.toml` 等 manifest 文件的 SHA-256 指纹。如果发现变更：

- 无漂移 → 静默通过
- 有漂移 → 提示用户选择：继续 / 增量刷新 / 完整重新 onboarding

---

## 个性化配置 / Personalization

AI 扫描能发现技术栈和目录结构，但无法发现项目专属约束。个性化配置把这些知识沉淀下来。

主要类别：

| 类别 | 说明 | 存储位置 |
|---|---|---|
| 禁区 | iterate 不得修改的文件/目录 | `iterate.config.yaml` |
| 风险区 | 改动需架构审批 | `iterate.config.yaml` |
| 已知意图 | 抑制误报 | `iterate.config.yaml` |
| 维度定制 | 为特定维度追加 focus | `iterate.config.yaml` |
| 优先修复顺序 | 维度修复优先级 | `iterate.config.yaml` |
| 禁止的修复方式 | 不可使用的手法 | `iterate.config.yaml` |
| 项目约定与注意点 | 经验教训、已知陷阱 | `ITERATE.md` 用户区 |
| 补充验证命令 | 项目特有验证命令 | `iterate.config.yaml` |

使用方式：

```bash
# onboarding 时顺带配置
iterate onboard

# 项目中途随时追加
iterate personalize
```

完整示例请参考 [`config/iterate.config.yaml`](./config/iterate.config.yaml)。

---

## 配置 / Configuration

默认配置位于 [`config/iterate.config.yaml`](./config/iterate.config.yaml)。项目级配置会递归覆盖 Master 配置的同名字段。

常用配置项：

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `goal` | string | `"Improve code quality"` | 迭代目标 |
| `max_rounds` | int | `7` | 最大轮数（上限 50） |
| `language` | string | `"en"` | 输出语言：`zh` / `en` |
| `dimensions` | list | 9 维度 | 启用的审查维度 |
| `review.scope` | string | `"full"` | `full` 全量 / `changed-only` 增量 |
| `atomic.max_lines` | int | `20` | 原子问题最大行数 |
| `git.target_branch` | string | `main` | 合并目标分支 |
| `git.push_per_round` | bool | `false` | 每轮通过后是否 push |
| `git.auto_merge` | bool | `false` | 验证后是否自动 merge |
| `validation.command_whitelist` | list | 常用前缀 | 允许执行的命令前缀 |
| `validation.commands` | object | 示例 | 按语言分组的验证命令 |
| `onboarding.drift_check` | bool | `true` | 是否检查 manifest 漂移 |

示例：

```yaml
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

> `validation.commands` 中的命令**必须**以 `command_whitelist` 中的前缀开头，否则会被拒绝。

### 命令行配置

```bash
# 初始化项目配置
python scripts/install.py config --init --target /path/to/project

# 非交互式修改
python scripts/install.py config --set goal="Fix all bugs" --target /path/to/project
python scripts/install.py config --set max_rounds=10 --target /path/to/project
python scripts/install.py config --set dimensions='[correctness, security]' --target /path/to/project

# 交互式向导
python scripts/install.py config --interactive --target /path/to/project

# 校验配置
python scripts/install.py validate --target /path/to/project
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
├── config/
│   ├── iterate.config.yaml           # 默认配置（Master）
│   ├── config.schema.json            # 配置 JSON Schema
│   ├── dimensions.yaml               # 聚合版维度定义
│   └── dimensions/                   # 数据驱动的维度定义
├── examples/                         # 各语言项目示例
├── templates/                        # 模板文件
├── iterate_cli/                      # onboarding CLI 源码
│   └── data/
│       └── ITERATE.template.md       # wheel 打包模板
├── scripts/
│   ├── install.py                    # 安装/卸载/配置/校验脚本
│   ├── validate.py                   # 配置与维度校验
│   └── requirements.txt              # 脚本依赖
├── tools/                            # 各 AI 助手专属实现示例
├── tests/                            # 单元测试
└── .github/workflows/                # CI / Release
```

---

## 核心流程 / Core Workflow

```text
Step 0 — Onboarding Check
  └─ 定位项目根 → 检查 ITERATE.md → 漂移检测 →（缺失则触发 onboarding）

Setup
  └─ 提取 goal → 加载配置 → 读取项目上下文 → 创建隔离分支/worktree

Loop (round = 1 .. max_rounds)
  ├─ Phase 1: N 维度并行审查
  ├─ Phase 2: 原子问题自动修复
  ├─ Phase 3: 架构问题用户批准后执行
  ├─ Phase 4: 记录本轮结果
  └─ Phase 5: 验证 → merge（若 auto_merge=true）→ push（若 push_per_round=true）

Summary
```

详细流程请参考 [`SKILL.md`](./SKILL.md)。

---

## 安全说明 / Security

- **高自主性**：本 skill 会自主执行文件编辑、`git` 操作以及 `validation.commands` 中配置的命令。所有修改先在隔离分支/worktree 中进行，架构修复必须经用户批准。
- **Secure-by-default Git**：`push_per_round` 和 `auto_merge` 默认均为 `false`。回滚使用 `git restore` 等非破坏性命令。
- **双层命令白名单**：
  - 配置时校验命令前缀。
  - 个性化添加 `extra_validation_commands` 时仅接受 30+ 预批准工具前缀，拒绝 `;`、`|`、`&` 等 shell 元字符。
- **敏感文件**：不读取 `.env`、密钥、凭证等敏感文件。
- **Update 安全**：`scripts/install.py update` 从 GitHub Release 下载时强制 SHA256 校验，缺失或不匹配则拒绝。

---

## 贡献 / Contributing

欢迎提交 Issue 和 PR！

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feat/your-feature`
3. 提交改动：`git commit -m "feat: description"`
4. 推送分支：`git push origin feat/your-feature`
5. 创建 Pull Request

请保持 `SKILL.md` 的中英双语结构，新增功能需补充配置示例。

---

## 许可证 / License

[MIT](./LICENSE) © 2026 iterate-skill contributors
