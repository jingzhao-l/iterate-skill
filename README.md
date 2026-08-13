# Iterate Skill

> 一个可移植、可配置的 AI 编程助手技能：全自动多轮代码审查与修复。
> A portable, configurable AI coding assistant skill: fully automated multi-round code review and fixing.

[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](./LICENSE)
[![npm](https://img.shields.io/badge/-npm-CB3837?logo=npm&logoColor=white)](https://www.npmjs.com/package/iterate-skill-installer)
[![GitHub release](https://img.shields.io/github/v/release/jingzhao-l/iterate-skill)](https://github.com/jingzhao-l/iterate-skill/releases)
[![ClawHub](https://img.shields.io/badge/-ClawHub.ai-4285F4?logo=cloudflare&logoColor=white)](https://clawhub.ai/jingzhao-l/skills/iterate-skill)
[![ModelScope](https://img.shields.io/badge/-ModelScope-624aff?logo=alibabacloud&logoColor=white)](https://www.modelscope.cn/skills/jingzhao0/iterate-skill)

---

## 30 秒了解 / At a Glance

**Iterate Skill** 让 AI 助手像一位严谨的资深工程师一样，对代码库进行多轮审查与修复。

| 能力 | 说明 |
|---|---|
| **9 维度并行审查** | correctness、security、performance、architecture、style-tests、tech-debt、spec-compliance、frontend-backend、ui-ux |
| **双轨修复** | 原子问题（≤20 行、单文件）自动修；架构问题经你批准后再修 |
| **Git 隔离** | 每轮在独立 `iterate/*` 分支或 worktree 中完成；merge/push 默认关闭，需显式开启 |
| **Secure-by-default** | `push_per_round` 和 `auto_merge` 默认均为 `false` |
| **命令白名单** | 配置时 + 个性化时双层校验，拒绝危险 shell 元字符 |
| **校验和验证** | 从 GitHub Release 更新时强制 SHA256 校验 |
| **多助手支持** | Trae、Claude Code、Cursor、Windsurf、GitHub Copilot、Codex、Roo Code 等 25+ 工具 |
| **项目知识库** | 自动生成 `ITERATE.md` + `iterate.config.yaml`，支持漂移检测和增量刷新 |

---

## 3 分钟上手 / Quick Start

### 1. 安装技能

```bash
npx iterate-skill-installer
```

运行后会自动检测你已安装的 AI 编程工具，交互选择要安装到哪些助手。支持 `--ai <name>` 直接指定单个助手。安装器还会自动安装 `iterate` CLI（用于下面第 2 步的 `iterate onboard` 等命令），一条命令即可完成 skill + CLI 的安装。

### 2. 进入项目并完成 onboarding

```bash
cd /path/to/your-project
iterate onboard
```

`iterate onboard` 会生成本项目的知识库：

- `ITERATE.md`：技术栈、模块地图、约定、禁区等
- `iterate.config.yaml`：迭代目标、审查维度、验证命令等

### 3. 开始迭代

在 AI 助手对话中输入：

```text
/iterate "提升代码质量，确保所有函数 ≤80 行且测试通过"
```

或在终端里直接启动 CLI：

```bash
iterate status      # 查看 onboarding 状态和漂移
iterate refresh     # 增量刷新 ITERATE.md
iterate personalize # 追加项目专属约束
```

---

## 安装 / Installation

### 推荐：npx 一键安装（适合绝大多数用户）

无需克隆仓库，无需手动配置 Python 环境，一条命令完成 skill 下载、校验、安装，并自动安装 `iterate` CLI：

```bash
# 自动检测已安装的 AI 助手并交互选择
npx iterate-skill-installer

# 仅安装到 Trae
npx iterate-skill-installer --ai trae

# 安装到指定项目目录
npx iterate-skill-installer --target /path/to/project

# 强制覆盖已安装的技能
npx iterate-skill-installer --ai trae --global --force
```

常用选项：

| 选项 | 说明 |
|---|---|
| `--ai <name>` | 仅安装到指定助手，如 `trae`、`claude`、`cursor` |
| `--target <path>` | 项目级安装到指定目录 |
| `--global` | 安装到用户主目录（默认） |
| `--force` | 覆盖已存在的 skill 文件 |
| `--token <token>` | GitHub token，用于提高 API 速率限制 |
| `-h, --help` | 查看帮助 |
| `-v, --version` | 查看版本 |

> **安装器会安装 `iterate` CLI 到你的 PATH**（优先 `pipx` 隔离安装，否则 `pip install --user`）。这是为了让 `npx iterate-skill-installer` 一条命令完成 "skill + CLI"，但安装器确实会在你的系统上放置一个可执行文件。若不希望自动安装 CLI，可改用下方的"手动复制 SKILL.md"或"源码脚本"方式。
>
> 安装器需要 Node.js 18+ 和 Python 3.10+。它会自动创建隔离的 Python 虚拟环境、安装依赖、调用 `scripts/install.py` 完成文件复制。下载 release 时强制校验 `SHA256SUMS.txt`，校验失败则拒绝安装。若 `iterate` 命令安装失败，仍可手动执行 `pipx install .` 或 `pip install .` 补装。

### 其他安装方式

如果你无法使用 npm，或者希望完全控制安装过程，可选用以下方式。

#### 方式 A：本地安装 iterate CLI

通过 npx 一键安装时已自动安装 `iterate` CLI。若你未使用 npx，或希望手动/升级安装 CLI，可在此手动安装：

```bash
git clone https://github.com/jingzhao-l/iterate-skill.git
cd iterate-skill

# 推荐用 pipx 隔离安装
pipx install .

# 或直接用 pip
pip install .

# 验证
iterate --version
```

安装后可在任意项目目录使用 `iterate onboard`、`iterate personalize`、`iterate status`、`iterate refresh`、`iterate reonboard`。

#### 方式 B：手动复制 SKILL.md

如果你只想让某个 AI 助手认识这个 skill，把 [`SKILL.md`](./SKILL.md) 复制到对应目录即可：

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

更多工具的路径请参考 [`SKILL.md`](./SKILL.md) 中的“工具映射表”。

#### 方式 C：源码脚本（开发者）

```bash
git clone https://github.com/jingzhao-l/iterate-skill.git
cd iterate-skill

python scripts/install.py install --ai trae --global
python scripts/install.py update --ai trae --target /path/to/project
python scripts/install.py uninstall --ai trae --target /path/to/project --yes
```

### 全局安装 vs 项目级安装

| 安装范围 | 路径示例 | 效果 |
|---|---|---|
| **全局安装** | `~/.trae/skills/iterate/` | 所有项目首次调用 `/iterate` 都会触发 onboarding |
| **项目级安装** | `/project/.trae/skills/iterate/` | onboarding 完成后直接复用项目根目录的 `ITERATE.md` |

建议：先在全局安装一次，让助手认识你；再在重要项目里做一次项目级安装，避免重复 onboarding。

### 为什么不推荐 skills.sh 安装？

本项目早期曾在 skills.sh / SkillHub 等平台分发。从 v2.1 起，**推荐统一使用 `npx iterate-skill-installer`**，原因如下：

1. **一条命令完成**：自动下载、SHA256 校验、环境准备、助手选择，无需手动克隆或复制文件。
2. **版本一致**：始终从 GitHub Release 安装，避免平台缓存导致的版本错乱。
3. **跨助手统一**：同一份安装逻辑支持 25+ AI 助手，而不是每个平台各自维护。
4. **安全可验证**：强制校验 SHA256SUMS.txt，校验失败则拒绝安装。

skills.sh 等市场页面仍会保留，用于展示和发现，但不再作为首选安装入口。

---

## 日常使用 / Daily Usage

### 在 AI 助手中

安装 skill 后，在支持该技能的 AI 工具中输入：

```text
/iterate "你的目标"
/iterate "你的目标" 10
/iterate "你的目标" no-limit
```

首次调用会自动触发 onboarding（如果项目还没有 `ITERATE.md`）。

### 在终端中

```bash
# 交互式 onboarding（首次/非首次会自动分支）
iterate onboard

# 中途追加个性化约束
iterate personalize

# 查看 onboarding 状态和漂移检测
iterate status

# 增量刷新（保留 ITERATE.md 用户手写区）
iterate refresh

# 完整重新 onboarding（备份旧文件）
iterate reonboard
```

---

## 它如何工作 / How It Works

### Onboarding（项目知识库初始化）

每次调用 `/iterate` 时，skill 会检查项目根目录是否存在 `ITERATE.md`。若不存在，触发 onboarding。

| 通道 | 适用场景 | 产出 |
|---|---|---|
| **AI Onboarding** | 希望 AI 根据项目目录结构/清单文件自动识别技术栈并生成 | `ITERATE.md` + `iterate.config.yaml` |
| **CLI Onboarding** | 希望 CLI 扫描后手动确认/调整技术栈与配置 | 同上 |

扫描仅读取文件/目录**存在性**和 README.md 等少量公开上下文文件，不会读取 `.env`、密钥、凭证或其他敏感文件内容。项目专属约束可通过 `iterate personalize` 补充。

`ITERATE.md` 分为两个区域：

- `<!-- ITERATE:AI-MAINTAINED:START -->`：AI 维护区，刷新时会更新。
- `<!-- ITERATE:USER-OWNED:START -->`：用户维护区，手写约定、禁区、风险区，刷新时保留。

### 漂移检测

每次调用 `/iterate` 时，会重新计算 `package.json`、`pyproject.toml` 等 manifest 文件的 SHA-256 指纹：

- 无漂移 → 静默通过
- 有漂移 → 提示用户选择：继续 / 增量刷新 / 完整重新 onboarding

### 个性化配置

AI 扫描能发现技术栈和目录结构，但无法发现项目专属约束。`iterate personalize` 把这些知识沉淀下来：

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

完整示例请参考 [`config/iterate.config.yaml`](./config/iterate.config.yaml)。

### 核心流程

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

## 配置参考 / Configuration

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

---

## 常见问题 / FAQ

### 安装 / Installation

**Q: 安装时提示要访问 GitHub 等国外网络，国内网络环境装不上怎么办？**
A: 安装器通过 GitHub Release 下载并校验，确实需要能访问 GitHub 的网络。若网络受限，可改用不依赖 GitHub 的方式：
- 手动复制 [`SKILL.md`](./SKILL.md) 到对应助手目录（见"方式 B"）。
- 国内镜像渠道（ModelScope / SkillHub CN）已上架，可从中获取 skill 文件。
- 社区代理镜像下载后，再执行 `python scripts/install.py install` 本地安装。

**Q: `npx iterate-skill-installer` 报 Python 或 Node 版本不符合？**
A: 安装器要求 Node.js 18+ 和 Python 3.10+。请先升级系统 Python/Node，或在终端确认 `python3` / `node` 在 PATH 中。安装器会优先使用 `python3`，再回退到 `python`。

**Q: 安装器会自动安装 `iterate` CLI 到我的电脑上，我能不装吗？**
A: 可以。`npx iterate-skill-installer` 会顺带安装 `iterate` CLI（优先 `pipx`，否则 `pip install --user`）以便直接运行 `iterate onboard`。若不希望自动安装 CLI，请改用"手动复制 SKILL.md"或"源码脚本"方式，仅复制 skill 文件即可。

**Q: 安装到一半想取消，会留下半成品吗？**
A: 不会。安装器在临时目录中完成下载、校验、解压，选中助手后才会写入助手目录；取消或失败时不会覆盖已安装的 skill。若已安装过，重装默认提示覆盖，需确认或加 `--force`。

### 使用 / Usage

**Q: 这个 Skill 适合什么场景？不适合什么场景？**
A: 适合**多轮**的代码审查与自动修复——例如压制技术债、多轮消除 lint/类型/测试问题、项目级重构。**不适合**单次简单改动（改一行、加个注释），这类需求直接用普通对话即可，无需 `/iterate`。

**Q: 第一次使用为什么什么都不做？**
A: 首次调用 `/iterate` 或运行 `iterate onboard` 前，项目还没有 `ITERATE.md` 与 `iterate.config.yaml`。首次使用时 skill 会**先进行项目初始化（Onboarding）**：AI 会明确告知"这是首次使用，将先初始化项目"，扫描代码库生成 `ITERATE.md` 与配置后再进入迭代。若你看到初始化提示而不是立刻审查，这是正常流程，不是失效；也可直接在项目根目录运行 `iterate onboard` 手动完成初始化。

**Q: 处理大项目时感觉卡住，没有进度提示？**
A: 大项目首轮要并行审查多个维度，可能耗时较长。为缓解"卡住"观感，skill 现在会在对话中**持续输出进度**：每轮开始显示 `▶ Round N/max`、并行审查期间逐维度提示 `⏳ 正在审查 …`、每轮结束显示 `✅ Round N complete`。若仍觉慢，可通过以下方式提速：
- 在 `iterate.config.yaml` 中把 `review.scope` 设为 `changed-only`，只审查本轮改动。
- 按目录/模块拆分 reviewer 任务（见 SKILL.md 的 Reviewer Prompt 检查清单）。
- 适当降低 `max_rounds`，避免无谓的额外轮次。

**Q: 运行时提示有漂移（drift）是什么意思？**
A: 漂移检测会对比 `package.json`、`pyproject.toml` 等 manifest 文件的 SHA-256 指纹。若依赖或配置发生变化，说明项目状态与上次 onboarding 不一致，会提示你选择：继续 / 增量刷新（`iterate refresh`）/ 完整重新 onboarding（`iterate reonboard`）。

**Q: 修改没有合并到主分支，也没推送到远程？**
A: 这是**安全默认**行为：`git.auto_merge` 与 `git.push_per_round` 默认均为 `false`，改动保留在隔离的 `iterate/*` 分支或 worktree 中，由你 review 后决定是否合并/推送。如需自动合并推送，请在 `iterate.config.yaml` 中显式开启这两个选项。

**Q: 我手动改了 `iterate.config.yaml`，为什么某些验证命令不生效？**
A: `validation.commands` 中的命令**必须**以 `validation.command_whitelist` 中的前缀开头，否则会被拒绝。个性化添加的 `extra_validation_commands` 也只会接受 30+ 预批准工具前缀，拒绝 `;`、`|`、`&` 等 shell 元字符——这是为了安全，防止项目配置被执行任意命令。

**Q: 想增加一个新的验证工具（比如 `sphinx`），怎么办？**
A: 严格白名单只接受预批准的工具前缀（这防止项目配置执行任意命令）。新增工具有两种**安全**方式：
- **操作者级环境变量（推荐，无需改源码）**：在运行环境中设置 `ITERATE_EXTRA_SAFE_COMMAND_PREFIXES=sphinx`（逗号/空格分隔多个工具名）。该变量**只能在系统层面设置**，项目配置文件无法设置，因此不会破坏安全模型；含 `;`、`|`、`&` 等元字符的条目会被直接丢弃（fail-closed）。
- **源码级扩展**：在 `iterate_cli/personalize.py` 的 `KNOWN_SAFE_COMMAND_PREFIXES` 中追加工具名后重新安装。
- 或改用 `validation.command_whitelist` + `validation.commands` 直接配置（需通过 `python scripts/validate.py config` 校验）。

### 安全 / Security

**Q: 这个 Skill 会读取我的密钥、`.env` 吗？**
A: 不会。skill 及 onboarding 扫描仅读取 manifest 文件的存在性和 `README.md` / `CLAUDE.md` 等公开上下文文件，明确不读取 `.env`、`*.key`、`secrets/`、`*.pem` 等敏感文件。`projectContext` 也不会包含 API 密钥、密码、Token。

**Q: 下载更新时安全吗？**
A: 安全。`scripts/install.py update` 与 `npx iterate-skill-installer` 从 GitHub Release 下载预上传的 `iterate-skill.tar.gz` + `SHA256SUMS.txt`，下载后强制 SHA256 校验，缺失或不匹配则拒绝安装。

---

## 安全说明 / Security

- **高自主性**：本 skill 会自主执行文件编辑、`git` 操作以及 `validation.commands` 中配置的命令。所有修改先在隔离分支/worktree 中进行，架构修复必须经用户批准。
- **Secure-by-default Git**：`push_per_round` 和 `auto_merge` 默认均为 `false`；merge/push 为 opt-in，未显式开启时改动保留在迭代分支。回滚使用 `git restore` 等非破坏性命令。
- **双层命令白名单**：
  - 配置时校验命令前缀。
  - 个性化添加 `extra_validation_commands` 时仅接受 30+ 预批准工具前缀，拒绝 `;`、`|`、`&` 等 shell 元字符；命令加载/合并时也会重新校验，手工编辑的配置无法绕过白名单。
- **敏感文件**：skill 及其 installer 不读取 `.env`、密钥、凭证等敏感文件；onboarding 扫描仅检查 manifest 等公开文件的存在性。
- **Update 安全**：`scripts/install.py update` 与 `npx iterate-skill-installer` 从 GitHub Release 下载预上传的 `iterate-skill.tar.gz` + `SHA256SUMS.txt`，下载后强制 SHA256 校验，缺失或不匹配则拒绝安装。
- **安装器披露**：`npx iterate-skill-installer` 会顺带把 `iterate` CLI 安装到 PATH（优先 `pipx` 隔离，否则 `--user`）。若不希望安装 CLI，请使用手动复制或源码脚本方式。

---

## 目录结构 / Directory Structure

```text
iterate-skill/
├── SKILL.md                          # 核心技能文件
├── README.md                         # 本文件
├── LICENSE                           # MIT 许可证
├── CONTRIBUTING.md                   # 开源贡献指南
├── CHANGELOG.md                      # 版本变更记录
├── pyproject.toml                    # iterate CLI 包定义
├── npm-installer/                    # npx 一键安装器源码
│   ├── bin/cli.js
│   ├── lib/installer.js
│   └── package.json
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
