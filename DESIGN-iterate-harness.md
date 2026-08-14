# iterate-harness 设计文档 v1.0

> 目标：把 iterate 从 Skill 形态升级为「专门用于 iterate 的极简 agent harness」，深度适配原 skill 的体系与功能。
> 状态：设计草案，待实现验证。
> 版本记录：见文末。

## 1. 背景与目标

### 1.1 背景
- iterate 目前以 Skill 形态存在（SKILL.md 提示词 + Python iterate_cli 工具链），其运行依赖宿主 IDE 的 agent 读取提示词并执行。
- 用户希望升级为 agent harness：一个独立于宿主 IDE 的运行时，把 iterate 的迭代循环、并行评审、原子修复、验证机制变成可执行的一等公民。

### 1.2 目标
1. 提供可复用的 agent 运行时（会话、工具、编排、配置、安全）。
2. 深度适配 iterate 原 skill 的体系与功能，语义层不重复实现。
3. 极简设计：克制、模块化、插件化。

## 2. 设计原则
- **极简核心**：内核只做 5 件事——会话管理、工具注册、编排循环、配置、安全边界。
- **一切可插拔**：模型、工具、技能、会话、沙箱、存储、循环、调度、UI 均可替换或重组合。
- **可追溯**：append-only 会话日志，模型可见内容必须能从日志重建（硬约束）。
- **厂商中立**：不锁定单一模型供应商。
- **深度适配**：iterate 的业务机制沉淀为「语义层」，与内核解耦，可被不同运行时承载。

## 3. 总体架构（三层）
1. **iterate 业务语义层**：维度规划、并行评审、原子修复、架构修复、决策日志、验证闭环（原 skill 体系，不重写）。
2. **Harness 极简内核**：会话管理 / 工具注册 / 编排循环（焦点）/ 配置 / 安全边界。
3. **运行时承载（可插拔）**：路线 A = dsh 运行时（插件承载）；路线 B = 独立运行时（fork 定制）。

## 4. iterate 机制 → harness 能力映射
| iterate skill 机制 | harness 适配能力 |
|---|---|
| 维度规划（dimensions 配置） | 配置驱动规划器，生成评审任务清单 |
| 并行评审（多维度并行） | 多 subagent 并行编排，聚合评审结论 |
| 原子修复（逐条修复） | 工具边界 + 变更审批（防越界改文件） |
| 架构修复（跨文件重构） | 全局上下文重载 + 跨文件工具 |
| 结果记录（决策日志） | append-only 会话日志，天然可追溯 |
| 验证命令（validate 校验） | 命令执行网关 + 校验器插件 |
| onboarding / 个性化 | 配置初始化向导，写入 harness 配置 |
| ITERATE.md 项目知识库 | 项目记忆投影（随会话自动加载/刷新） |

## 5. 双路线（并行，语义层共享）
### 路线 A：dsh 插件（iterate-dsh-plugin）
- 形态：Cordis 生态内插件（TypeScript），复用 dsh 运行时。
- 复用：subagent / approval / plan / skill 加载 / append-only 日志。
- 职责：iterate 循环映射为 dsh workflow；config 映射为 dsh 配置；validate 映射为工具。
- 优点：零运行时维护、生态复用、快速落地。
- 风险：受 dsh 演进约束；插件是 TS，与 Python 工具链需桥接。

### 路线 B：独立极简 harness（iterate-harness）
- 形态：fork OpenHarness（MIT）定制，Python 同栈。
- 保留：工具调用、记忆、权限、多智能体协调。
- 定制：内置 iterate 迭代循环、维度评审、决策日志、验证网关。
- 优点：完全自主、深度定制、语义层可直连 Python iterate_cli。
- 风险：运行时自维护，启动成本高。

### 对比摘要
| 维度 | 路线 A dsh 插件 | 路线 B 独立 Harness |
|---|---|---|
| 运行时维护 | 零维护 | 自维护 |
| 控制力 | 受 dsh 约束 | 完全自主 |
| 启动成本 | 低 | 高 |
| 生态复用 | 强（dsh-plugin topic） | 独立 |
| 语言栈 | TS + Python 桥 | Python 同栈 |

## 6. 仓库形态（决策：方案 B 同仓库双模块）
- `skill/` 与 `harness/` 同仓库、顶层分开维护，共享版本号。
- 现有 skill 三平台发布流程（ClawHub / ModelScope / SkillHub）走特定子路径，不受新增 `harness/` 影响。
- 日后需要再平滑升级为 Monorepo（workspace）。
- 备选：方案 A 独立仓库（跨仓共享语义层协调成本高）、方案 C Monorepo（单人维护过度设计）。

## 7. iterate-dsh-plugin 最终实现形态（v0 最小验证版）
```
harness/
└── iterate-plugin/            # dsh 插件（TS）
    ├── package.json           # dsh.bundle 字段指向 patch 文件（分发格式）
    ├── src/
    │   ├── index.ts           # export function apply(ctx)
    │   ├── inject.ts          # export const inject = ['tools','sessions',...]
    │   ├── tools/             # validate / decision-log / config 等工具
    │   ├── skills/iterate.md  # 复用原 SKILL.md
    │   ├── memory/            # ITERATE.md 投影与注入
    │   └── bridge/            # 子进程/JSON-RPC 桥 → 调 Python iterate_cli
    ├── cordis.patch.yml       # 挂载配置（一行 insert 即装上）
    └── README.md
```
运行时循环：规划（读 dimensions）→ 并行评审（subagent ×N）→ 原子修复（工具+审批）→ 验证（validate 桥）→ 决策日志（append-only）→ 回环直至验证通过。
- 插件遵守 dsh 规范：`inject` 声明依赖、`ctx.tools.register(defineTool(...))` 注册工具、`ctx.effect()` 管理可逆副作用、Model-visible means logged。
- v0 范围：自治闭环 workflow（规划 → 并行评审 ×N → 原子修复 → 验证 → 回环 → 达标自停）+ dry-run 纯审查模式 + 5 个核心工具（config / validate / decision-log / context / review）+ 加载 SKILL.md + ITERATE.md 注入，验证语义层迁移与 Python 桥接成本。

### 7.1 dry-run 模式（纯审查模式）
- **定位**：只评审、只出报告，**绝不修改任何文件**。是 iterate 的「只读体检」模式，也是普通 skill 完全做不到的效果。
- **触发**：工具调用 `iterate review --dry-run`，或 workflow 参数 `mode: "dry-run"`（区别于 `mode: "normal"`）。
- **行为**：
  1. **规划**：读取 dimensions + goal，生成评审任务清单（同正常模式）。
  2. **并行评审**：N 个 subagent 并行，返回各维度 findings。
  3. **聚合**：去重、过滤 `known_intentional`、按 severity 排序（同正常模式 Phase 1）。
  4. **多轮收敛**：可配 `review.max_reviews`，**反复多轮审查**直至发现数收敛（较上一轮不再下降）或达到上限——"纯粹反复审查"。
  5. **产出**：评审报告（各维度 findings + 每轮收敛统计 + 建议修复优先级）+ append-only 决策日志。**不创建分支、不建 worktree、不写任何项目文件**。
- **与正常模式差异**：跳过 Phase 2/3（原子/架构修复）、跳过 git 隔离与 merge/push；只保留 Phase 0/1/4（规划/评审/记录）。
- **确定性实现**：多轮收敛的去重 / 已知意图过滤 / severity 排序 / 收敛统计全部落在纯函数引擎 `src/review.ts`（可单测）；`iterate_review` 工具提供 `plan`（评审计划）与 `aggregate`（确定性聚合）两个操作；workflow 按注入的 canonical 模板复现循环——每轮把已发现 findings 喂回评审者"只找新问题"，某轮新增 0 条即收敛自停。
- **用途**：CI 预检、发布前基线评估、改动前摸底、教学演示、成本可控的多维深度审查。
- **价值**：正常模式是"评审即修复"，dry-run 是"评审即诊断"——先彻底看清问题、形成可审计的报告，再由人或后续轮次决定是否动手。

## 8. 能力边界：skill 无法实现 vs harness 可实现
| 能力维度 | 原 skill | iterate-harness |
|---|---|---|
| 自主多轮迭代 | 依赖宿主手动触发 | agent-loop 原生循环，跑到达标自动停 |
| dry-run 纯审查 | 无（skill 无纯审查模式） | 只评审不改文件，多轮收敛出报告，可 CI 预检 |
| 真·并行评审 | 仅建议并行 | subagent 原生并行 ×N + 聚合 |
| 审批 / 安全边界 | 靠提示词自觉 | 原生 approval + 工具权限边界，可强制执行 |
| 可追溯性 | 项目内文件，靠自觉写 | append-only 日志硬约束，可回放/恢复/fork |
| 可插拔 | 绑定宿主模型 | 模型/工具/存储/沙箱全可替换，可 A/B |
| 跨会话记忆 | 每次重新 onboarding | 会话持久化 + ITERATE.md 自动注入 |
| 运行环境 | 必须跑在宿主 IDE | 独立 CLI / headless / CI 可跑、可批量 |

诚实边界：harness 不改变模型智力，只改变执行环境；插件 TS 与 Python 工具链存在桥接成本；skill 的零安装、宿主天然支持优势被 harness 丢掉。

## 9. 落地路线图
1. **先做最小 dsh 验证插件**（路线 A v0）：验证语义层迁移 + Python 桥成本。
2. 验证通过后，评估路线 B 独立 harness 是否投入（复用验证过的语义层）。
3. 按需发布插件到 dsh-plugin 生态（加 topic + bundle 分发）。
4. 版本号全项目统一（遵循既有硬约束；例外：`harness/iterate-plugin` 走独立版本线，见 §6）。

## 10. 风险与开放问题
- 桥接性能与稳定性：子进程 / JSON-RPC 的调用开销。
- dsh 演进依赖：新版本是否破坏插件 API。
- 语义层最终落 Python 还是 TS：影响路线 B 是否与插件共享代码。
- SKILL.md 内容是否需为 harness 形态改写（上下文压缩、记忆注入方式）。

## 11. 独立 harness 设计（路线 B 具体化）

> 基于路线 A（dsh 插件）v0 验证通过的前提，独立 harness 的形态与方案现已明确：
> fork OpenHarness（Python 栈），深度定制为「专用于 iterate 的 agent harness」。
> 本章为 v1.5 新增，完整保留前文（v1.0–v1.4）内容。

### 11.1 技术栈决策（OpenHarness = Python 栈）

经调研确认，OpenHarness（HKUDS，MIT）为 **Python 栈**：

| 项目 | 事实 |
|---|---|
| 语言 | Python 3.10+（uv 包管理器） |
| 规模 | 11,733 行 / 163 文件（44× 轻于 Claude Code） |
| 工具 | 43 个（文件 / Shell / 搜索 / Web / MCP） |
| 技能 | 完全兼容 `anthropics/skills` 与 `claude-code/plugins` |
| 测试 | 114 单测 + 6 端到端 |
| 内置能力 | streaming tool-call loop、API 重试退避、并行工具执行、token 计数与成本追踪、CLAUDE.md 注入、上下文压缩、MEMORY.md、会话恢复、多级权限、PreToolUse/PostToolUse hooks、交互审批、subagent 生成与后台任务生命周期 |
| UI | React TUI + Ink TUI 双形态 |
| 命令 | `oh`（交互）/ `oh -p`（一次性）/ `--output-format json` / `--dry-run` 静态预览 |
| 厂商 | Anthropic 兼容 / OpenAI 兼容 / Claude 订阅 / Codex 订阅 / Moonshot / GLM / MiniMax / Ollama 等 workflow |

**结论**：独立 harness 采用 **Python 同栈**，与既有 `iterate_cli`（Python）工具链同栈，语义层移植成本最低；这也回答了 v1.0 §10 开放问题「语义层最终落 Python 还是 TS」——**独立 harness 走 Python，与插件（TS）共享的是语义约定而非代码**。

### 11.2 能力差距分析（用户视角：skill / 插件实现不了 vs 独立 harness 可实现）

以用户实际使用体验为视角，逐项对比「原 skill → dsh 插件 → 独立 harness」三层能实现什么：

| 能力效果 | 原 skill（提示词+Python CLI） | dsh 插件（路线 A） | 独立 harness（路线 B） |
|---|---|---|---|
| **不依赖宿主运行** | ❌ 必须跑在宿主 IDE agent 里 | ❌ 必须跑在 dsh 运行时 + 聊天会话里 | ✅ `oh -p "..."` 一次性 / headless / CI / 批量 |
| **agent loop 是内核级** | ❌ 靠宿主模型自觉循环 | ⚠️ 靠 dsh `workflow` 脚本模拟 | ✅ 内核原生 streaming tool-call cycle + retry + 并行执行 |
| **token / 成本透明** | ❌ 完全不可见 | ❌ 插件无成本层（受 dsh 约束） | ✅ 内核 token counting & cost tracking 开箱即得（呼应此前 P0 建议） |
| **审批强制执行** | ❌ 只能提示词引导 | ⚠️ 依赖 dsh approval | ✅ 内核 PreToolUse/PostToolUse hooks + 多级权限 + 交互审批弹窗，强制生效 |
| **dry-run 静态预览** | ❌ 无 | ⚠️ 有审查型 dry-run（不写文件） | ✅ 审查型 dry-run **且** 内核 `--dry-run` 静态预览（settings/auth/skills/commands/tools） |
| **跨会话恢复** | ❌ 每次重新 onboarding | ❌ 无状态 | ✅ session resume & history，`--session` 续跑（呼应此前 P1 resume 建议） |
| **持久记忆** | ❌ ITERATE.md 仅靠自觉读 | ⚠️ context 工具读文件 | ✅ MEMORY.md 持久化 + 上下文自动压缩，跨天长会话 |
| **真·并行评审** | ⚠️ 仅建议 | ✅ 但受 dsh 编排约束 | ✅ 内核并行工具 + subagent 生命周期管理，可后台任务 |
| **多智能体协调** | ❌ | ⚠️ workflow 模拟 | ✅ team registry / 任务管理 / 后台任务生命周期（native swarm） |
| **厂商中立** | ❌ 绑定宿主模型 | ⚠️ 受 dsh 接入 | ✅ 多 provider workflow，环境变量切换，本地 Ollama 亦可 |
| **reasoning 模型** | ❌ | ⚠️ 受 dsh 支持 | ✅ Kimi 等 reasoning_content 原生 |
| **技能生态复用** | ❌ | ⚠️ 需加载 SKILL.md | ✅ iterate SKILL.md 可直接挂载为 skill（anthropics 兼容） |
| **独立分发** | ✅ skill 文件 | ⚠️ 依赖 dsh 插件体系 | ✅ pip / install.sh 独立安装，可作独立产品 |

**独立 harness 独有、skill 与插件都无法实现的核心效果（用户视角）**：

1. **「离开 IDE 也能自治迭代」**：在 CI 流水线 / 命令行 / 批量任务里跑 iterate 闭环，无人值守到收敛自停，产出可审计报告。
2. **「每一次动作都强制受控」**：写文件 / 跑命令不再是模型自觉，而是被 harness 内核的权限 hooks 强制拦截并弹窗确认——从「靠自觉」到「靠强制」。
3. **「看得见的成本」**：每轮评审 / 修复消耗多少 token、多少钱实时可查，`/cost` 一目了然，让「反复多轮审查」的成本可控、可预算。
4. **「中断可恢复」**：长迭代中断后 `--session` 从上次断点续跑，不再推倒重来。
5. **「一份 SKILL.md 通吃所有宿主」**：skill 生态复用意味着 iterate 的提示词可作为标准 skill 被任意兼容 harness 加载。

**诚实边界（继承 v1.0 §8）**：harness 不改变模型智力；skill 的零安装、宿主天然支持优势被 harness 丢掉；独立运行时需自维护。

### 11.3 fork 定制点（OpenHarness → iterate-harness）

在 OpenHarness 之上定制以下内容，其余内核能力（loop / 权限 / 记忆 / 多智能体 / TUI / 厂商 workflow）直接复用：

| 定制面 | 做什么 |
|---|---|
| 语义层移植 | 将插件 TS 语义层（review / meta-review / config-loader 逻辑）移植为 Python 模块，或直接复用 `iterate_cli` 现有 Python 逻辑（validation.commands 精确匹配、known_intentional 过滤、去重 / 排序 / 收敛统计、6 项 meta-review 检查） |
| 内置 iterate 命令 | `iterate-harness review --dry-run` / `iterate-harness iterate` / `iterate-harness resume` / `iterate-harness init` / `iterate-harness log`（或作为 `oh` 的子命令） |
| iterate 配置 | 加载 `iterate.config.yaml`（Master+Overrides 合并逻辑移植），权限规则映射到内核 permission 配置 |
| 决策日志 | append-only `decision-log.jsonl` 作为内核会话日志之外的业务日志，随会话可回放 |
| 技能挂载 | 将项目 SKILL.md 以 anthropics 兼容 skill 形式内置，harness 启动自动注入 |
| 项目记忆 | `ITERATE.md` 投影为 CLAUDE.md 等价物（OpenHarness 已原生支持 CLAUDE.md 注入），语义与插件 context 工具一致 |
| TUI 体验 | 复用 OpenHarness TUI；按用户偏好打磨键盘导航（↑↓ 移动、空格选择、Enter 确认）的 approve / dimension 选择界面 |

### 11.4 架构与模块划分

```
harness/
└── iterate-harness/             # fork 自 OpenHarness 的独立运行时（Python）
    ├── pyproject.toml           # 精确版本依赖，MIT
    ├── src/
    │   ├── main.py              # oh / iterate-harness CLI 入口
    │   ├── kernel/              # OpenHarness 内核（复用，尽量不改）
    │   │   ├── agent_loop.py    # streaming tool-call cycle / retry / 并行
    │   │   ├── permission.py    # 多级权限 + PreToolUse/PostToolUse hooks
    │   │   ├── memory.py        # CLAUDE.md / MEMORY.md / 上下文压缩 / 会话恢复
    │   │   ├── providers.py     # 厂商中立 workflow（Anthropic/OpenAI/本地…）
    │   │   └── tools/           # 43 内置工具（文件/Shell/搜索/Web/MCP）
    │   ├── iterate/             # iterate 语义层（深度定制核心）
    │   │   ├── config.py        # iterate.config.yaml 加载 + Master/Overrides 合并
    │   │   ├── review.py        # 确定性聚合：去重/过滤/排序/收敛（移植 TS 语义）
    │   │   ├── meta_review.py   # 6 项一致性审计（移植 TS 语义）
    │   │   ├── decision_log.py  # append-only 决策日志
    │   │   ├── validate.py      # validation.commands 精确匹配 + 执行
    │   │   └── prompts.py       # 评审/fix 子代理提示词模板（含 findings schema）
    │   ├── commands/            # iterate-harness 内置命令
    │   │   ├── review.py        # dry-run 纯审查（多轮收敛 + meta-review）
    │   │   ├── iterate.py       # normal 自治闭环（评审→修复→验证→回环→自停）
    │   │   ├── init.py          # 配置初始化向导（复用 iterate_cli onboarding 思路）
    │   │   ├── resume.py        # 会话恢复 / 断点续跑
    │   │   └── log.py           # 决策日志查看 / 回放
    │   └── tui/                 # TUI 组件（复用 OpenHarness UI 框架）
    │       ├── approve.py       # 审批弹窗（↑↓ 导航、空格、Enter）
    │       └── dimensions.py    # 维度选择 / 评审进度面板
    ├── skills/iterate.md        # SKILL.md 以 anthropics 兼容 skill 内置
    ├── tests/                   # 语义层单测（移植自插件 test，≥53 项） + 内核 E2E
    └── README.md
```

### 11.5 CLI 命令集（v0）

| 命令 | 说明 |
|---|---|
| `iterate-harness init` | 交互式初始化 `iterate.config.yaml`（goal / dimensions / validation.commands / 个性化） |
| `iterate-harness review --dry-run` | 纯审查：多轮收敛 + meta-review，只读不写文件，产出审计报告 |
| `iterate-harness iterate` | 自治闭环：评审 → 原子修复 → 验证 → 回环 → 收敛自停 |
| `iterate-harness resume --session <id>` | 从历史会话断点续跑 |
| `iterate-harness log` | 查看 / 回放决策日志 |
| `iterate-harness --dry-run` | 内核静态预览（settings / auth / skills / commands / tools），不动模型不跑工具 |

### 11.6 v0 范围与里程碑

- **M1 语义层移植**：`config.py` / `review.py` / `meta_review.py` / `validate.py` / `decision_log.py` 落地，移植 ≥53 单测全绿。
- **M2 命令打通**：`review --dry-run` 与 `iterate` 两条主链路在 OpenHarness 内核跑通，权限 hooks 拦截修复写操作。
- **M3 CLI 完善**：`init` / `resume` / `log`，厂商中立 provider 验证（DeepSeek + 至少一家兼容端点）。
- **M4 TUI 打磨**：审批弹窗 + 维度选择 + 评审进度面板，键盘导航符合偏好。
- **M5 独立分发**：`pip install` / install.sh，版本号全项目统一（遵循既有硬约束），发布到 GitHub。

### 11.7 风险与开放问题（路线 B 新增）

- OpenHarness 内核升级与 fork 漂移：锁定精确版本，必要时以 patch 形式跟进。
- 语义层 TS/Python 双实现漂移：以单测对齐 + 同一份用例（tests 移植）约束行为一致。
- `iterate_cli` 复用边界：validate / onboarding 直接调用现有 Python 代码，避免重复实现。
- TUI 与 skill/插件 UX 的一致性：独立 harness 可自成一派，不与 dsh 对齐。
- 许可证：OpenHarness MIT（宽松），可入生产；继续禁止 GPL/AGPL 依赖。

## 12. 版本记录
- v1.0（2026-08-14）：首版设计草案。决策点：仓库形态=方案 B 同仓库双模块；落地优先级=先 dsh 最小验证插件。
- v1.1（2026-08-14）：新增 dry-run 纯审查模式（只评审不改文件、多轮收敛出报告）；v0 范围调整为「自治闭环 + 并行评审 + dry-run」；能力边界表补充 dry-run 与自主多轮收敛差异。
- v1.2（2026-08-14）：实现阶段落地 dry-run——新增确定性纯函数引擎 `src/review.ts` 与 `iterate_review` 工具（plan / aggregate 两操作），v0 工具数由 4 更新为 5（config / validate / decision-log / context / review），补充 canonical dry-run 收敛循环模板说明。
- v1.3（2026-08-14）：实现阶段落地自治闭环——`skill-prompt.ts` 补充 normal 模式 canonical 模板（配置→评审计划→并行评审→确定性聚合→原子修复→验证→回环→达标自停）；评审报告类型由 `DryRunReport` 泛化为 `ReviewReport`（mode 支持 dry-run / normal，两模式共用同一确定性聚合引擎），报告新增全局去重/过滤/排序后的 `findings` 字段，供 fixer 直接消费；20 个单元测试全绿。
- v1.4（2026-08-14）：实现阶段补齐 meta-review 报告审计——新增 `src/meta-review.ts`（6 项一致性检查：COUNT_MATCH / SEVERITY_SUM / DIMENSION_SUM / SORT_ORDER / CONVERGENCE / ROUND_SHAPE），`iterate_review` 新增 `meta-review` 操作，dry-run 收敛报告产出前先审计自身一致性并给出 approved / needs_revision 判定；修复 ROUND_EMPTY 误报 bug（收敛轮=最后一轮空属正常成功信号，不再标记为缺陷）；插件经真实 dsh headless 运行时验证：5 个 iterate 工具全部注册、系统提示成功注入、aggregate + meta-review 端到端输出符合预期；新增 README 使用说明；33 个单元测试全绿。
- v1.5（2026-08-14）：新增独立 harness 设计章节（§11）——确认 OpenHarness 为 Python 栈并决策独立 harness 采用 Python 同栈；以用户视角完成「skill / dsh 插件 / 独立 harness」三层能力差距分析（内核级 agent loop、token 成本透明、审批强制执行、session 恢复、持久记忆、厂商中立、技能生态复用、独立分发等）；给出 fork 定制点、模块架构、CLI 命令集（init / review --dry-run / iterate / resume / log）、v0 里程碑（M1 语义层移植 → M5 独立分发）与路线 B 新增风险。
- v1.6（2026-08-14）：仓库形态决策迭代（§6）——新增独立插件发布仓库 jingzhao-l/iterate-plugin（git subtree 拆分 harness/iterate-plugin，保留完整历史，作为 dsh 生态镜像并引流回主仓库）；主仓库保持唯一维护点，同步走 subtree push（无 CI 同步、无 force-push）；插件 package.json 补 repository/homepage/bugs 元数据指向主仓库；插件开始独立版本线（自 2.3.7 起），第 9 节版本统一约束对插件生效范围同步更新。
