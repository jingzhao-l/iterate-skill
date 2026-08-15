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

## 6. 仓库形态（决策：主仓库统一维护 + 独立插件发布仓库）
> v1.7 迭代：独立插件发布仓库（subtree 拆分）作为 npm 发布源，插件独立版本线。

- **主仓库（jingzhao-l/iterate-skill）**：`skill/` 与 `harness/` 同仓库、顶层分开维护，是**唯一维护点**——插件代码的提交、评审、README 变更等全在主仓库完成。
- **独立插件发布仓库（jingzhao-l/iterate-plugin）**：由主仓库 `git subtree split` 拆分 `harness/iterate-plugin/` 推送而成，保留完整提交历史；作为 npm 发布源（`npm publish` 在此执行）、dsh 生态发现入口（打 `dsh-plugin` topic）、并引流至主仓库（README 顶部横幅 + npm `repository` 元数据指向主仓库）。
  - 发布工作区：`/Volumes/Eng-Dev/iterate-skill/.release/iterate-plugin/`（gitignore 目录），`git subtree push` 同步后在此执行发版。
- 同步流程：`git subtree split --prefix=harness/iterate-plugin -b subtree-plugin && git push plugin-origin subtree-plugin:main` → 在 `.release/` 工作区 `git pull` 后执行 `npm publish`。
- **插件独立版本线**：`harness/iterate-plugin/package.json` 自 2.3.7 起独立递增，不再与 skill 版本号强绑定（仅第 9 节路由图的「全项目版本统一」约束对 skill 本体生效）。
- 现有 skill 三平台发布流程（ClawHub / ModelScope / SkillHub）走特定子路径，不受新增 `harness/` 影响。
- **日后的 harness 发布仓库（决策 2026-08-14）**：harness 第一个大版本（v0/1.0）完成后，同样采用「主仓库统一维护 + 独立发布仓库」模式——另开独立仓库作为 harness 的发布源（npm/安装脚本等在此执行），主仓库 `harness/iterate-harness/` 仍是唯一开发与评审点，通过 subtree 拆分持续同步，与 iterate-plugin 仓库模式完全一致。
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

#### 11.2.1 用户体验场景深析（v1.8：站在用户面前的具体交互，非内核能力清单）

> §11.2 的表是"内核能力"视角；本节补齐"用户能看到什么、点什么、玩到什么"视角，只列 skill 与插件**原理上做不出**的体验，按「看 / 摸 / 跑 / 沉淀」四类分。

**一、看得见的 UI**（skill 只能吐 markdown，插件被 dsh 卡片样式锁死）

| 独占体验 | 长什么样 | 为什么前两层做不到 |
|---|---|---|
| 实时收敛仪表盘 | 审查进行中：TUI 显示 `Round 2/3`、新发现数 sparkline `▇▅▂▁`、五维度各自 spinner + findings 计数、token/费用累计条 | skill 等全部跑完才有文字报告；dsh 卡片是静态文本，插件无法自绘组件 |
| 细粒度 diff 审批 | 修复前弹 unified diff，↑↓ 滚动、**逐 hunk 空格标记接受/拒绝**、Enter 提交 | 插件走 dsh 通用审批（整文件粒度）；skill 是模型直接改文件 |
| findings 分诊界面 | 审查完逐条过：`y 修复 / n 跳过 / a 永久忽略`——按 `a` 的自动写回 `iterate.config.yaml` 的 known_intentional | skill/插件无交互入口；"个性化配置"从手写 yaml 变成交互产生的数据 |
| init 检测式向导 | 自动识别项目语言/测试框架 → 空格勾选推荐维度 → 预览生成的 yaml → Enter 写入 | skill 的 wizard 是纯文本问答；插件没做 init |

**二、摸得着的中途干预**（不是"等它跑完"）

- Esc 暂停菜单：迭代中途暂停，弹"跳过当前 finding / 收窄维度 / 直接停"，选完继续——skill 无进程概念，插件 workflow 发起后不可中途改道。
- 断点续跑画面：`resume` 恢复时 TUI 先显示上次快照（跑到第几轮、还剩哪些 finding），确认后续跑。

**三、离开 IDE 才能跑的场景**（无人值守，存在性缺口）

- PR 自动审查：`review --dry-run --format pr-comment`，CI 里直接评论到 PR，exit code 当质量门禁（findings 超阈值即红）。
- git hook：commit 前 30 秒 changed-only 快审。
- 批量/定时：一条命令审 10 个仓库出排行；cron 每天跑，只报新增问题。

**四、数据沉淀**（从"一次性报告"到"趋势"）

- 跨 run 趋势：finding 指纹（file+line+dimension 哈希）存本地库，`log --trend` 显示"上周 12 → 本周 5"，区分**新增 / 已修复 / 顽固未动**——skill 的决策日志是纯文本，查不了。
- HTML 单文件报告：收敛曲线、severity 分布、内嵌 diff，可直接发给别人看。
- 评审回放：`log --replay` 按时间序回放每轮决策，像看录像。

**v0 取舍建议**：① findings 分诊界面（把个性化闭环做成交互）② diff 审批 + Esc 干预（把"强制受控"做成体验）③ PR/CI 模式（打开无人值守场景）优先；实时仪表盘与趋势库 v1；HTML 报告最低。

#### 11.2.2 代码实况深析（v1.9：基于 iterate_cli 六模块 + SKILL.md + 配置层的源码证据）

> 本节结论全部来自源码阅读（iterate_cli/{cli,fingerprint,scan,generator,refresh,personalize,wizard,tui}.py、SKILL.md、config/、scripts/、templates/、examples/），是 §11.2 内核能力与 §11.2.1 UX 场景的代码级证据与细化。

**一、关键事实：iterate_cli 是 100% 确定性本地计算，零 LLM 依赖**

六个模块（fingerprint / scan / generator / refresh / personalize / cli 非向导部分）全部为纯本地确定性计算 + 终端表单采集；模型依赖全部在 SKILL.md 驱动的宿主 agent 侧。这意味着 **onboarding 全链路可直接作为 harness 的数据层复用**，无需重写。

现成数据资产清单：

| 资产 | 内容 | 当前形态 | 位置 |
|---|---|---|---|
| 指纹库 | 15 类 manifest 的 SHA-256（仅项目根，不递归） | config 字段 | `iterate.config.yaml` `onboarding.fingerprints` |
| DriftResult | unchanged/changed/added/removed 四元组 | 内存，不持久化 | fingerprint.py `compare_fingerprints` |
| ScanResult | manifests/languages/dirs + 6 个 has_* 特性位 | 内存，渲染进 ITERATE.md | scan.py `scan_project` |
| suggest_* 三函数 | 维度/验证命令/白名单启发式建议 | 内存，仅向导内一次性出现 | scan.py |
| PersonalizationData | 9 类个性化数据（结构化 7 类 + 自由文本 2 类） | config + ITERATE.md 用户区 | personalize.py |
| KNOWN_SAFE_COMMAND_PREFIXES | 命令前缀白名单 + FORBIDDEN_COMMAND_CHARS 禁字符 | 源码常量 | personalize.py |
| 分区标记契约 | AI-MAINTAINED / USER-OWNED 刷新边界 | ITERATE.md 注释 | generator.py |

**二、prompt 约定 → 机制强制：全景对照（skill 现状 vs 插件已强制 vs harness 待强制）**

- **插件已强制（10 项，确定性计算类）**：findings schema、severity 排序、跨轮去重、known_intentional 过滤、收敛判定、meta-review 六项审计（仅 dry-run）、review plan、配置合并、验证命令精确匹配、决策日志 append-only。
- **仍是 prompt 约定、harness 内核可强制（20 项），分两类**：
  - **副作用约束类（PreToolUse/PostToolUse hooks + 权限层）**：protected_paths 写拦截、risk_areas 强制审批、forbidden_fixes diff 正则匹配拒绝、敏感文件读拦截（.env/*.key）、验证失败自动回滚（限 iterate/* 分支）、逐 hunk 修复 + 文件锁串行。
  - **状态继承类（session + 持久化）**：is_atomic 实测校验（fixer 后 `git diff --stat` 超阈值自动降级 architectural）、每组 trim≤20 确定性截断、文件碰撞 defer 用 Set 交集计算、fix_priority_order 确定性重排、deferredArchitectural 跨会话继承（decision-log + resume）、正常模式复用 meta-review 审计计数一致性。

**三、维度配置体系在 harness 的解锁项**（当前维度 yaml 仅 name/priority/focus 文本，focus 里的"阈值"是自然语言不可消费）

- per-dimension `model`/`concurrency`/`token_budget`（security 用强模型、style-tests 用快模型）
- 维度级阈值门禁：`max_critical`/`max_high` → 阻止 merge / CI 红（对接 §11.2.1 PR 门禁）
- 维度特定验证命令：style-tests 修完跑 lint、security 修完跑 bandit
- priority 驱动修复调度（与 fix_priority_order 合并）；维度趋势追踪；changed-only 的维度级细化（后续轮只重跑有改动维度的模块）

**四、用户旅程断点（源码级证据，harness 可修复）**

- 安装：无 bootstrap、无版本过期比对（A1-A3）
- onboarding：**"TUI"实为 rich 着色的 input() 问答**——无方向键/空格/回车组件，维度多选靠手敲 `"1,2,5,7"`（wizard.py `_parse_dimension_selection`）；向导不问 goal/max_rounds/atomic/language（generator.py 硬编码 DEFAULT_GOAL/7/20/en，与 examples/ 展示落差）；验证命令建议按语言硬编码不读真实 manifest scripts、且无 dry-run 预检（B1-B8）
- 日常：drift 检测只在 `iterate status` 被动触发；known_intentional 添加后无法即时验证是否命中；`.bak-<timestamp>` 平铺备份难查询（C1-C5）

**五、顺带发现的现有代码问题（待修复清单，非 harness 范畴）**

1. `tui.py question()` 签名 `-> str` 实际返回 None；`prompt_prefix` 的 rich 标记可能泄露进 input() 提示文本。
2. `examples/typescript-project.md` "验证通过后合并推送" 与默认 `auto_merge=false` 矛盾（Python/Swift 示例已修正，TS 未同步）。
3. `templates/iterate-decisions.template.md` 用 `{goal}` 单花括号占位，但仓库无对应渲染代码——模板与生成器脱节，实际由 AI 会话自行处理。
4. `__main__.py` 与 `cli.py` 双 `if __name__` 守卫冗余。

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

#### 11.3.1 真实仓库结构核验（v1.11：以 GitHub 实际目录树为依据）

> 初稿结构拉取自 GitHub `HKUDS/OpenHarness` main 分支（commit `9b2efd7`，2026-06-04）；随后已完整克隆源码至主仓库 `.external/OpenHarness/`（gitignored，`--depth 1` + tags，检出 **v0.1.9 稳定 tag** `a0f8552`，2026-05-07）并完成四路并行源码深析（内核引擎 / 扩展面 / 状态配置 / 编排与 UI），深析结论见 §11.3.2。本节结构与本地克隆一致。

```
OpenHarness/
├── pyproject.toml / README.md / README.zh-CN.md / CHANGELOG.md / LICENSE(MIT)
├── src/openharness/           # 主包（扁平子包结构，无 kernel/ 聚合层）
│   ├── cli.py / __main__.py   # `oh` CLI 入口
│   ├── engine/                # query_engine.py（agent loop 核心）/ cost_tracker.py / messages.py / stream_events.py
│   ├── api/                   # provider.py / registry.py / client / openai_client / codex_client / copilot_client / usage.py（厂商中立层）
│   ├── auth/                  # 认证管理
│   ├── permissions/           # checker.py / modes.py（多级权限）
│   ├── hooks/                 # events / executor / loader / schemas——4 类 hook：command | prompt | http | agent，均带 matcher / timeout / block_on_failure / priority
│   ├── commands/              # registry.py（slash 命令注册表）
│   ├── skills/                # loader / registry / types / _frontmatter / bundled/content（anthropics 兼容技能加载）
│   ├── prompts/               # claudemd.py（CLAUDE.md 原生注入）/ system_prompt.py / context.py / environment.py
│   ├── memory/                # manager / agent / memdir / relevance / scan / search / team / usage / schema / migrate
│   ├── services/              # session_backend / session_storage / compact/（上下文压缩）/ cron_scheduler / token_estimation / lsp / memory_extract
│   ├── state/                 # app_state / store
│   ├── swarm/                 # in_process / subprocess_backend / mailbox / registry / team_lifecycle / worktree / permission_sync / lockfile（多智能体）
│   ├── tasks/                 # manager / local_agent_task / local_shell_task / types
│   ├── coordinator/           # agent_definitions / coordinator_mode
│   ├── tools/                 # 44 个内置工具：bash / file_read / file_write / file_edit / grep / glob / agent / team_* / task_* / todo_write / skill / cron_* / web_* / mcp_* / ask_user_question / enter_worktree / exit_worktree / lsp …
│   ├── ui/                    # react_launcher（对接 frontend/terminal React+Ink）/ textual_app / permission_dialog / input / output / protocol / runtime
│   ├── plugins/               # loader / installer / schemas / bundled（OpenHarness 自身插件系统）
│   ├── personalization/       # extractor / rules / session_hook（OpenHarness 已有个性化框架）
│   ├── sandbox/               # docker_backend / path_validator / session / adapter（Docker 沙箱）
│   └── mcp/ bridge/ channels/ keybindings/ themes/ vim/ voice/ output_styles/ autopilot/ utils/ platforms.py
├── frontend/terminal/         # React + Ink TUI 源码
├── autopilot-dashboard/       # React 自动驾驶看板
├── ohmo/                      # 独立子项目（fork 后可裁剪）
└── docs/ scripts/ tests/ assets/ .claude/skills/ .agents/
```

**对设计有直接影响的核验结论**：

1. **结构形态**：真实结构是「扁平子包 + 注册机制」，不存在 v1.10 §11.4 草案假设的 `kernel/` 聚合层与 `providers.py`/`agent_loop.py` 等文件名——fork 策略必须改为「保留 `openharness/` 包原样 + 新增 `iterate/` 子包 + 注册点挂载」，详见 §11.4.1。
2. **意外收获的现成能力**（草案未预料、直接复用）：
   - `swarm/worktree.py` + `tools/enter_worktree_tool.py`：**git worktree 隔离是内核原生的**——iterate 修复轮的 git 隔离方案可直接复用，无需自建；
   - `tools/cron_*` + `services/cron_scheduler.py`：定时审查（§11.2.1「cron 每天跑」场景）开箱即得；
   - `tools/ask_user_question_tool.py`：findings 分诊界面的交互原语已存在；
   - `hooks/` 4 类 hook（command/prompt/http/agent）+ matcher 工具过滤 + block_on_failure：§11.2.2 的 20 项「prompt 约定→机制强制」有了直接载体——副作用约束类用 command hook（确定性），状态继承类用 agent/prompt hook（模型校验）；
   - `personalization/`：上游已有个性化框架，iterate 个性化数据可对接而非另起炉灶；
   - `sandbox/`：验证命令可选 Docker 隔离执行；
   - `services/compact/`：长迭代多轮的上下文压缩原生支持。
3. **hook 机制细节**（来自 `hooks/schemas.py`）：`CommandHookDefinition`（shell 命令、默认 30s、可 block）/ `PromptHookDefinition`（模型校验、默认 block）/ `HttpHookDefinition` / `AgentHookDefinition`（深度模型校验、60s、block），matcher 可按工具名过滤（file_write / file_edit / bash）——iterate 的 protected_paths 写拦截、forbidden_fixes diff 正则拒绝等均可用 command hook 零内核改动实现。
4. **命令机制**：`commands/registry.py` 为 slash 命令注册表（`/xxx` 形态），CLI 子命令在 `cli.py`——iterate 命令双形态挂载（slash `/iterate` + CLI `iterate-harness` 子命令）。

#### 11.3.2 源码级深析（v1.11：基于 v0.1.9 本地克隆的四路并行探索，全部带 file:line 证据）

> 源码位置：`.external/OpenHarness/`（v0.1.9, `a0f8552`）。以下每条结论均可回溯到源码行号，是 §11.4.1 修订版架构的直接依据。

**一、关键纠偏：v1.10 草案中与源码不符的假设（12 项）**

| # | 草案假设 | 源码事实（file:line） | 对设计的影响 |
|---|---|---|---|
| 1 | agent loop 在 `QueryEngine` 类内 | 真循环是模块级函数 `run_query`（`engine/query.py:632`），单 `while` 循环在 `query.py:699`；`QueryEngine.submit_message` 只是薄包装（`engine/query_engine.py:147-190`） | 轮次控制必须 fork `run_query`，不是改类 |
| 2 | hook 可承载评审轮次控制 | `HookEvent` 共 10 个事件（`hooks/events.py:8-19`），无 PRE_TURN/POST_TURN；`STOP` 仅在模型不再调工具、循环将结束时触发一次（`query.py:806-815`）；hook 只能 block 单个工具、不能改 messages/控制流（`hooks/executor.py:64`） | 收敛判定/轮次注入只能改 loop 本体；hook 仅用于副作用约束类强制 |
| 3 | 可走「内置插件」形态 | `plugins/bundled/__init__.py` 是空文件且 `load_plugins()` 不扫描它（`plugins/loader.py:107-123` 只扫用户/项目目录）；插件无 apply/inject 编程式 API，纯声明式 manifest（`plugins/schemas.py:8-24`）；插件不能直接注入系统提示 | 否决插件路线，采用「独立子包 + 直接注册」（§11.4.1） |
| 4 | TUI 有 React / Textual 双形态可选 | Textual 实现存在但**未接线**：全仓无任何模块 import `textual_app`；`run_repl` 只走 `launch_react_tui`（`ui/app.py:57-86`） | TUI 定制唯一路径 = React 前端 + NDJSON 协议扩展 |
| 5 | CLI 有 `--session` 参数 | 不存在；恢复用 `--continue`（最近会话）/ `--resume [ID]`（指定会话，`cli.py:2110-2123`），恢复经 `run_repl(restore_messages=..., restore_tool_metadata=...)`（`cli.py:2397-2411`） | §11.5 命令集对应修正 |
| 6 | cost tracking 含金额 | `CostTracker` 只累加 token（`engine/cost_tracker.py:8-24`），`UsageSnapshot` 仅 input/output_tokens（`api/usage.py:8-16`），无金额换算 | 「看得见的成本」金额层需 fork 自建（token×价格表） |
| 7 | worktree 隔离一套实现 | **两套独立实现不共享代码**：`swarm/worktree.py`（`~/.openharness/worktrees/<slug>`，含 node_modules/.venv 软链复用，`worktree.py:105-117,144`）与 `tools/enter_worktree_tool.py`（`repo/.openharness/worktrees/`，同步 subprocess，`enter_worktree_tool.py:42-53,79-80`） | iterate 修复轮选 `WorktreeManager`（有软链复用与 stale 清理） |
| 8 | bash 白名单可用权限规则表达 | 只有 `denied_commands`（deny 语义，`permissions/checker.py:120-126`）；无 `allowed_commands` 字段（全仓 grep 0 命中） | 白名单两条路：PreToolUse command hook（零内核改动）或 fork 加字段（推荐后者，见 §11.4.1） |
| 9 | path_rules 可做 protected_paths 禁写 | `path_rules` 仅 deny 生效、不区分读写（`checker.py:109-117` 无 is_read_only 分支）；且仅当工具输入含 `file_path/path` 字段才被抽取（`query.py:916`） | 「禁写不禁读」需 fork 在 `evaluate` 加读写分支 |
| 10 | 长迭代上下文无忧 | compact 四级渐进（microcompact→collapse→session memory→LLM full compact），microcompact 把早期 read_file/bash/grep 等结果**不可逆清空**（`services/compact/__init__.py:52,808-856`），`COMPACTABLE_TOOLS` 硬编码、无「不可压缩」标记 | iterate 多轮评审的 findings/diff 关键产物必须走 attachment 通道保留（`compact/__init__.py:714-733` 已有先例） |
| 11 | bundled skill 支持目录布局 | `get_bundled_skills()` 只 glob `*.md` 不递归（`skills/bundled/__init__.py:23`）；用户级才是 `<dir>/SKILL.md` 布局（`skills/loader.py:70-85`） | iterate SKILL.md 以单文件 `skills/bundled/content/iterate.md` 落地，自动成为 `/iterate` 命令（`commands/registry.py:2160`） |
| 12 | 复用上游 personalization 框架 | 上游是 10 类正则扁平 fact（confidence 固定 0.7，`personalization/extractor.py:11-75`），与 iterate 9 类结构化 PersonalizationData 模型不兼容；存储不按项目隔离（`rules.py:9`） | iterate 个性化独立子系统，仅复用注入入口模式（`prompts/context.py:123-125` 先例） |

**二、直接可用的挂载点清单（全部现成入口，fork 改动集中且小）**

| 挂载面 | 源码入口 | 用法 |
|---|---|---|
| 轮间控制点 | `engine/query.py:868`（tool results 回喂后、下一轮 while 前） | 插 iterate 控制块：收敛判定/轮次注入/break；经 `QueryContext`（dataclass，`query.py:137-154`）扩展 `iterate_policy` 传策略，上层 `QueryEngine` 与消费者零改动 |
| slash 命令 | `create_default_command_registry()`（`commands/registry.py:2106-2266`） | `registry.register(SlashCommand("iterate", ...))`；handler 放独立模块 `commands/iterate.py`（registry.py 已 2300+ 行） |
| 自定义工具 | `BaseTool`（`tools/base.py:35-57`：`name/description/input_model` + `async execute(arguments, context) -> ToolResult`）+ `create_default_tool_registry()`（`tools/__init__.py:47-96`） | 5 个 iterate 工具按此契约实现并追加注册 |
| 内置技能 | `skills/bundled/content/iterate.md`（frontmatter 仅 `description` 功能必填，`skills/_frontmatter.py:34-82`） | 放入即被扫描，自动注册为 `/iterate` + `skill(name="iterate")` 双入口 |
| ITERATE.md 注入 | 最小改法 1 行：`prompts/claudemd.py:15-17` candidate 元组加 `ITERATE.md`（复用向上遍历+截断+去重）；独立段落改法：`prompts/context.py:119` 后加一段 | 推荐 claudemd.py 一行改法（零新代码）；系统提示组装唯一汇聚点在 `prompts/context.py:77` |
| 配置节 | `Settings`（pydantic，`config/settings.py:496-534`）加 `IterateSettings` 字段 | model_validate/dump 自动往返，`load/save_settings` 零改动 |
| CLI 子命令 | `cli.py:765-777` 已有 `mcp/plugin/auth/provider/cron/autopilot` 子命令组先例 | 新增 `iterate` 子命令组（review/iterate/resume/log），console script 复用 `oh`/`openharness`（`pyproject.toml:48-52`） |
| 厂商接入 | `PROVIDERS` 元组加 `ProviderSpec` 即完成（`api/registry.py:55-368`，文件头注释明示三步流程）；**DeepSeek 已内置**（`registry.py:171-183`，`DEEPSEEK_API_KEY` + `api.deepseek.com/v1`） | 厂商中立零成本兑现，含重试退避（`api/client.py:32-114`：3 次指数退避+抖动+Retry-After） |

**三、并行评审 ×N 的正确姿势（源码契约）**

- `AgentTool` **强制 subprocess backend**（`tools/agent_tool.py:62-66`，注释说明 in_process 的 asyncio 内部 ID 无法被 task 工具查询）；单次 execute 只 spawn 一个 agent（`agent_tool.py:82`），**没有批量 spawn API**。
- 并行的正确方式 = 模型同一回合发起 N 次并行 `agent` 工具调用——多工具并发由内核 `asyncio.gather` 承载（`engine/query.py:830-844`，`return_exceptions=True` 防兄弟协程被取消）。
- 结果回收复用 coordinator 契约：`ui/coordinator_drain.py` 轮询 `BackgroundTaskManager`，完成批以 `<task-notification>` 包络作为后续 user turn 回灌（`coordinator_drain.py:89-197`）；coordinator 系统提示本身示范并行 spawn（`coordinator/coordinator_mode.py:496-497`）。
- **iterate 评审编排完全复用该契约**：N 个维度评审 = N 个后台 agent task（`tasks/manager.py:114` `create_agent_task`），每任务独立 worktree（`swarm/worktree.py:150` `create_worktree(repo_path, slug, branch, agent_id)`，含软链复用与 `cleanup_stale`），聚合由确定性引擎消费 task 输出。

**四、fork 裁剪清单（以 import 证据为准）**

| 子包 | 外部引用 | 处置 |
|---|---|---|
| `vim/` | 零外部 import（孤立死代码） | **删除** |
| `channels/` | 零外部引用（vendored 自 nanobot，`channels/UPSTREAM`） | **删除**（连带 ohmo 的 2 处 lazy import 消失） |
| `ohmo/`（子项目） | 仅 channels 内 2 处 lazy import | **删除**（可选依赖） |
| `autopilot/` | `cli.py` ×10 + `commands/registry.py:17` | 保留（接线中；autopilot-dashboard/ 目录一并保留或裁剪 UI） |
| `voice/` | `commands/registry.py:1618` | 保留（删需同步删命令，收益低） |
| `bridge/` | UI 三件套 + commands 活跃使用 | 保留 |
| `frontend/terminal/` | React TUI 唯一 UI | **必留**（注意：本克隆浅层无 node_modules，首启会自动 `npm install`，`react_launcher.py:133-142`） |

**五、其它源码事实（备查）**

- 会话存储是 **JSON 非 JSONL**：`~/.openharness/data/sessions/{name}-{sha1(cwd)[:12]}/` 下 `latest.json` + `session-{sid}.json` 双写（`services/session_storage.py:54-107`）；decision-log 仍按 iterate 自己的 append-only jsonl 独立存在。
- 权限三模式 `default/plan/full_auto`（`permissions/modes.py:8-13`，无 acceptEdits）；`--dangerously-skip-permissions` ≡ full_auto（`cli.py:2304-2305`）。
- 权限判定顺序：内置敏感路径硬保护（不可覆盖，`checker.py:88-98`）→ denied_tools → allowed_tools → path_rules(deny) → denied_commands → full_auto → 只读放行 → plan 拒绝 → default 弹窗确认（`checker.py:75-156`）；**PreToolUse hook 先于权限层执行**（`query.py:880-890`）。
- PreToolUse block 的语义 = 返回 `is_error=True` 的 ToolResultBlock 给模型（可调整重试），非中断会话（`query.py:886-891`）。
- cron：标准 5 字段（croniter），注册表 JSON + 历史 jsonl + fork 守护进程（`services/cron.py:12-116`、`cron_scheduler.py:261-358`，`oh cron start`）；job 经沙箱执行、300s 超时——定时审查场景零成本。
- 沙箱：`srt` CLI 包裹或 Docker backend（`sandbox/adapter.py:52-131`、`utils/shell.py:51-97`）；Windows 原生不支持。
- auto-compact 阈值默认 ≈167k token（200k 窗口，`compact/__init__.py:1056-1088`），连续失败 3 次熔断。
- MEMORY.md 体系按 cwd 哈希存于 `~/.openharness/data/memory/`（`memory/paths.py:11-22`），不在项目内。

### 11.4 架构与模块划分

> ⚠️ v1.11 注：以下目录树为 v1.10 基于能力清单的**草案假设**（虚构的 `kernel/` 聚合层与文件名），保留存档；**修订版架构见 §11.4.1**（以 §11.3.1 真实结构为依据），落地实现以 §11.4.1 为准。

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

#### 11.4.1 修订版架构（v1.11：源码级，落地实现以此为准）

> 形态：**保留 OpenHarness 包结构与内核原样 + 新增 `iterate/` 语义子包 + 8 处内核定点修改**。不虚构 kernel 层，不重排上游目录——最大化降低上游同步（rebase）成本。

```
iterate-harness/                     # fork 自 HKUDS/OpenHarness @ v0.1.9
├── src/openharness/                 # 上游包结构原样保留（裁剪清单见 §11.3.2-四）
│   ├── iterate/                     # ★ 新增子包：iterate 语义层（唯一大块新增代码）
│   │   ├── __init__.py
│   │   ├── settings.py              # IterateSettings(pydantic) + iterate.config.yaml 加载（Master/Overrides 深合并，移植插件 config-loader）
│   │   ├── review.py                # 确定性聚合引擎：去重/known_intentional 过滤/severity 排序/收敛统计（移植 TS review.ts）
│   │   ├── meta_review.py           # 6 项一致性审计（移植 TS meta-review.ts，含 ROUND_EMPTY 修复语义）
│   │   ├── decision_log.py          # append-only decision-log.jsonl + 回放
│   │   ├── validate.py              # validation.commands 精确匹配执行网关（对齐插件 validate.ts 语义）
│   │   ├── loop_policy.py           # IterateLoopPolicy：收敛判定/轮次上限/评审计划（经 QueryContext 注入 run_query）
│   │   ├── worktree_flow.py         # 修复轮 git 隔离编排（封装 swarm/worktree.WorktreeManager + 验证失败回滚）
│   │   ├── cost.py                  # 金额层：UsageSnapshot × 价格表 → 每轮/累计费用（补上游只算 token 的缺口）
│   │   ├── personalization.py       # 9 类结构化个性化数据（独立存储 ~/.openharness/iterate/，按 cwd 隔离）
│   │   └── prompts.py               # 评审/修复子代理提示词模板（含 findings schema、canonical 循环模板）
│   ├── commands/iterate.py          # ★ /iterate slash 命令 handler（在 commands/registry.py 注册一行）
│   ├── tools/iterate_tools.py       # ★ 5 工具：iterate_config/validate/review/decision_log/context（BaseTool 契约，注册于 tools/__init__.py）
│   ├── skills/bundled/content/iterate.md   # ★ SKILL.md 内置（自动成为 /iterate + skill() 双入口）
│   ├── prompts/claudemd.py          # ★ 一行改动：candidate 元组加 ITERATE.md（§11.3.2-二）
│   └── engine/query.py              # ★ 定点改动：868 行后插 iterate 控制块 + QueryContext 加 iterate_policy 字段
├── frontend/terminal/src/panels/    # ★ React 评审进度面板 + findings 分诊组件（protocol.py 加 review_progress 事件）
└── tests/iterate/                   # ★ 语义层单测（移植插件 53 测）+ loop_policy 集成测试 + compact 保留性测试
```

**内核定点修改清单（全部 8 处，每处一个 diff 面）**：

| # | 文件 | 改动 | 目的 |
|---|---|---|---|
| 1 | `engine/query.py` | `QueryContext` 加 `iterate_policy` 字段；`:868` 后插控制块（收敛判定→break / 注入评审消息 / 产出 `ReviewProgressEvent`） | 轮次控制与收敛自停 |
| 2 | `engine/stream_events.py` | 联合类型加 `ReviewProgressEvent`（round/new_findings/per_dimension/token_cost） | TUI 实时收敛仪表盘的事件源 |
| 3 | `engine/cost_tracker.py` | `add()` 时同步调 `iterate.cost.accumulate()`；或 QueryEngine 转发处挂钩 | 金额透明（每轮/累计） |
| 4 | `config/settings.py` | `Settings` 加 `iterate: IterateSettings`（定义移入 `iterate/settings.py`，此处仅 import） | iterate.config.yaml 与内核 Settings 融合 |
| 5 | `permissions/checker.py` | 加 `allowed_commands` 白名单（evaluate 顺序插在 denied_commands 前）；`path_rules` 判定加 `is_read_only` 分支实现「禁写不禁读」 | protected_paths / 验证命令白名单原生强制 |
| 6 | `services/compact/__init__.py` | iterate 关键产物（findings 列表 / 失败 diff / 决策摘要）写入 `_build_compact_attachments` 通道 | 防 microcompact 不可逆清空评审证据 |
| 7 | `commands/registry.py` + `tools/__init__.py` | 各加一行注册（handler/工具实体在 iterate 子包与 commands/iterate.py） | /iterate 命令与 5 工具 |
| 8 | `prompts/claudemd.py` | candidate 元组加 `ITERATE.md`（1 行） | 项目知识库自动注入 |

**评审编排数据流**（复用上游契约，零编排新造）：

```
/iterate 或 oh iterate review --dry-run
  → iterate/loop_policy 生成评审计划（dimensions × goal）
  → 模型同回合 N 次并行 agent 工具调用（query.py:830-844 asyncio.gather）
  → 每评审 agent = create_agent_task + WorktreeManager 隔离（只读评审可不建 worktree，dry-run 强制不建）
  → coordinator_drain 契约回收 task-notification 输出
  → iterate/review 确定性聚合（去重/过滤/排序/收敛）
  → iterate/meta_review 审计 → ReviewProgressEvent → React 面板
  → 未收敛：loop_policy 注入「只找新问题」下一轮；收敛：出报告 + decision_log 追加
```

#### 11.4.2 fork 工作流与上游同步

- **fork base**：`v0.1.9` tag（`a0f8552`，2026-05-07，最新稳定版）；同时 cherry-pick main HEAD `9b2efd7`（2026-06-04 "preserve profile auth when overriding model"——profile 覆盖模型时保留认证，对 DeepSeek 等兼容端点的 profile 切换场景直接受益）。
- **仓库形态**：遵循 §6 决策——主仓库 `harness/iterate-harness/` 唯一开发点，subtree 拆分独立发布仓（首个大版本后建）。
- **上游同步**：fork 仓加 `upstream` remote 定期 fetch；因内核改动锁定在 §11.4.1 的 8 个定点 diff 面，rebase 冲突面可控；每次同步跑 `tests/iterate/` 全量回归（53+ 单测是行为对齐锚）。
- **裁剪执行**：fork 首次提交即删 `vim/`、`channels/`、`ohmo/`（§11.3.2-四 证据），后续不再引入。
- **版本线**：与 skill/插件一致采用「主仓库统一 + 发布仓独立发版」；harness 版本独立递增（同插件 2.3.7 先例）。

### 11.5 CLI 命令集（v0）

> ⚠️ v1.11 勘误（源码级）：① 会话恢复参数不存在 `--session`，上游用 `--continue` / `--resume <id>`（`cli.py:2110-2123`），iterate 命令集对齐为 `iterate-harness resume <id>`（缺省 = 最近会话）；② 入口命令沿用上游 console script `oh`，iterate 以子命令组挂载（`oh iterate ...`，参照 `cli.py:765-777` 子命令先例），同时保留独立 `iterate-harness` 别名；③ 「harness --dry-run 静态预览」直接复用上游 `oh --dry-run`（预览 settings/auth/skills/commands/tools）。

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
- v1.7（2026-08-14）：npm 发布源切换至插件仓库（§6）——建立本地发布工作区 `.release/iterate-plugin/`（gitignore），插件仓库从"只读镜像"升级为 npm 正式发布位：版本 bump、git tag、npm publish 均在插件仓库进行，主仓库仍是唯一开发/评审维护点；版本线确认沿用当前数值（不重置 1.0.0，npm 不允许发布低于已发布最高版本），自 2.3.7 起独立递增；主仓库 `dsh-plugin` topic 移除，仅插件仓库保留。
- v1.8（2026-08-14）：新增 §11.2.1 用户体验场景深析——区别于 §11.2 内核能力视角，按「看（实时收敛仪表盘 / 逐 hunk diff 审批 / findings 分诊 / init 检测式向导）/ 摸（Esc 暂停干预 / 断点续跑画面）/ 跑（PR 评论 + 质量门禁 / git hook / 批量定时）/ 沉淀（finding 指纹趋势 / HTML 报告 / 评审回放）」四类记录 skill 与插件原理上做不出的独占体验；给出 v0 优先级（分诊界面 > diff 审批+干预 > PR/CI 模式）。
- v1.9（2026-08-14）：新增 §11.2.2 代码实况深析——三路并行源码审查（iterate_cli 六模块 / wizard+tui+模板 / SKILL.md+配置层）证实：① iterate_cli 100% 确定性本地计算零 LLM，onboarding 全链路可直接复用为 harness 数据层（7 类现成数据资产清单）；② prompt 约定→机制强制全景对照：插件已强制 10 项确定性计算类约定，剩余 20 项分「副作用约束类（hooks/权限可强制）」与「状态继承类（session/持久化可强制）」；③ 维度 yaml 现仅 focus 文本，harness 可解锁 per-dimension model/并发/token 预算、维度级阈值门禁、维度专属验证命令等 7 项；④ 用户旅程断点源码级定位（TUI 实为 input() 问答、向导不问 goal/max_rounds/atomic/language、验证命令无 dry-run 预检等）；⑤ 顺带发现 4 个现有代码问题（tui.question 接口 bug、TS 示例 auto_merge 文档矛盾、决策日志模板未接线、双 __name__ 守卫）记入待修复清单。
- v1.10（2026-08-14）：§6 增补 harness 发布仓库决策——harness 首个大版本完成后另开独立发布仓库（同 iterate-plugin subtree 模式），主仓库统一维护。同日随 v2.3.7 发布修复 §11.2.2 所列 4 个代码问题（tui.question 契约 + prompt_prefix 死代码删除、TS 示例 auto_merge 矛盾、决策日志模板角色注释、cli.py 冗余守卫移除，新增 tests/test_tui.py）。
- v1.11（2026-08-14）：OpenHarness 源码级落地依据补全——克隆 v0.1.9 稳定版至 `.external/`（gitignored）并完成四路并行深析（内核引擎/扩展面/状态配置/编排 UI）。新增 §11.3.1 真实结构核验、§11.3.2 源码级深析（12 项草案纠偏：真循环在 run_query 而非 QueryEngine、hook 无轮次事件、plugins/bundled 空载、Textual 未接线、无 --session、CostTracker 只算 token、双 worktree 实现、无 allowed_commands、path_rules 不分读写、microcompact 不可逆清空、bundled skill 仅 *.md、personalization 模型不兼容；8 个现成挂载点清单；并行评审 ×N 源码契约；fork 裁剪清单 vim/channels/ohmo 可删）、§11.4.1 修订版架构（iterate 子包 + 8 处内核定点修改 + 评审编排数据流）、§11.4.2 fork 工作流（base=v0.1.9+cherry-pick 9b2efd7、上游同步策略）、§11.5 勘误（resume 参数/oh 子命令组/dry-run 复用）。v1.10 §11.4 目录树标注为草案存档，落地以 §11.4.1 为准。
- v1.12（2026-08-15）：M1–M3 落地实现完成——**M1 语义层**：`src/openharness/iterate/` 子包 12 模块全部就位（types / config_loader / review〔含 plan/round/report 序列化与解析契约〕 / meta_review / validate / decision_log / settings〔IterateSettings 入内核 Settings〕 / loop_policy / cost〔金额层：价格表 × UsageSnapshot → 每轮/累计 USD〕 / personalization〔9 类结构化、按 cwd 哈希隔离存储〕 / prompts〔canonical dry-run/normal 模板移植自 skill-prompt.ts〕 / worktree_flow〔git 隔离编排：enter/commit/exit、验证失败自动回滚〕）；包 `__init__` 采用 PEP 562 惰性导出打断 config.settings→iterate→api→auth→config.settings 循环导入。**M2 命令打通**：8 处内核定点修改全部落地（① query.py 控制块：turn 末读 iterate_state → ReviewProgressEvent/下一轮注入/收敛自停，另补工具 metadata 回写 tool_metadata 使跨 turn 状态可见；② stream_events.py 增 ReviewProgressEvent；③ 金额层经 loop_policy 的 CostMeter 挂钩（选 QueryEngine 转发方案）；④ Settings.iterate 字段；⑤ permissions：allowed_commands 精确匹配白名单（插在 denied_commands 前）；path_rules 维持上游双向拦截契约（iterate protected_paths 搭载，为"禁写不禁读"设计下限的超集）；⑥ compact 增 iterate_review 附件防 microcompact 清空评审证据；⑦ /iterate slash 命令 + 5 工具注册；⑧ claudemd 候选加 ITERATE.md）；QueryEngine 自动装配 IterateLoopPolicy（settings.iterate.enabled 开关，传 False 显式关闭）。**M3 CLI**：`oh iterate init/review/run/resume/log` 子命令组（init 含 manifest 检测式生成 + questionary 交互；review/run 走 run_print_mode headless 全自动管线；resume 复用 session_storage 恢复进 REPL；log 支持 --tail/--json）。bundled skill `iterate.md` 内置（自动 /iterate + skill() 双入口）。**验证**：tests/test_iterate/ 137 单测全绿（语义层 74 + 引擎/权限/内核集成 63），全仓回归 1038 passed（2 个失败均为沙箱写 ~/.openharness 与 npx 网络的环境性问题）；语义层与工具层 ruff 全过（内核遗留 lint 基线未动）。**有意偏差记录**：① path_rules 读写分支未按 §11.4.1 #5 拆分（上游测试契约 deny 双向拦截，选择搭载而非破坏）；② protected_paths 尚未自动注入 path_rules（v0.2 前接入 hooks 装配）；③ M4 TUI（React 收敛仪表盘/逐 hunk diff 审批/分诊界面）与 M5 独立分发（pip/install.sh/发布仓）未启动，为下一版本范围。
- v1.13（2026-08-15）：M4–M5 落地完成，v1.12 偏差②闭合——**偏差修复（权限层自动装配）**：`permissions/checker.py` 新增 `build_permission_checker(settings)` 工厂，把 `Settings.iterate` 自动装配进权限层：protected_paths 归一化为绝对路径 deny 规则（`.env`→`*/.env`、`secrets/*`→`*/secrets/*`，绝对模式原样透传；对用户已配规则去重、深拷贝不改源设置、`iterate.enabled=False` 时整体旁路）；forbidden_fix_patterns 编译为正则并经 `evaluate()` 新增的 `content` 参数对变更型工具写载荷（content/new_string/diff/patch，query.py `_extract_permission_content` 仅对非只读工具提取）做硬边界拦截（先于 allowed_tools/allowed_commands，不可被白名单绕过；非法正则告警跳过不阻断启动）。REPL runtime、/permissions、/plan×2 共 4 处实例化点全部替换为工厂。新增 8 项装配测试（含归一化、去重、旁路、边界优先级、载荷提取）。**M4a 协议摸底**：React TUI 链路确认为 ReviewProgressEvent → backend_host `_render_event` → BackendEvent（stdout `OHJSON:` JSONL）→ useBackendSession.handleEvent → React state → 面板组件（TodoPanel/SwarmPanel 同构模式）。**M4b 收敛仪表盘**：后端三处（protocol.py 增 `review_progress` 事件型 + 9 个 review_* 字段；backend_host 事件转换含人类可读 message；app.py print 模式 text→stderr / stream-json 双通道）+ 前端四处（types.ts ReviewProgressSnapshot；useBackendSession 状态 + 逐轮 new_findings 趋势环形数组；新组件 ReviewProgressPanel〔converged 绿/iterating 品红边框、trend n→…→0、维度 Top6、USD 成本〕；App.tsx 接线于 TodoPanel 与 StatusBar 之间）；tsc 零错误，新增 backend_host 集成测试 1 项。**M4c findings 分诊**：第 6 工具 `iterate_triage`（y=fix / n=skip / a=always-ignore）：交互经 `context.metadata["ask_user_prompt"]`（TUI 走既有 question modal，零前端改动）；`a` 持久化 KnownIntentional（file+dimension+line 三元组去重，note 可选）；全部决策落决策日志（type=decision、kind=triage）；headless 无交互通道时整体套用 `default` 参数兜底；>50 条 findings 拒绝（防问答锁死会话）；8 项新测试（含持久化→review.filter_known_intentional 闭环验证）；prompts.py 与 bundled skill iterate.md 同步第 6 工具说明，canonical dry-run 循环增第 7 步分诊入口。**M5a 分发适配**：README.md / README.zh-CN.md 重写为 iterate-harness 身份（fork 致谢 + 六工具/两模式/特性表/架构树/安装/测试；上游功劳明确归属）；install.sh / install.ps1 / install_dev.sh 三脚本适配：源固定 `jingzhao-l/iterate-harness.git`、默认 git clone + venv + 可编辑安装（--from-source 保留为兼容别名、移除 pip openharness-ai 模式）、venv/源目录改 `~/.iterate-harness-{-src,venv}`、注册 `oh`+`iterate-harness`（Windows 优先 iterate-harness.exe 避开 PowerShell Out-Host 别名）、彻底移除 ohmo/channels 引用；.gitignore 补 `.iterate-harness-venv/`；CHANGELOG 增 0.2.0 条目；test_install 契约更新为 fork 启动器断言；版本 0.2.0 对齐（pyproject / cli.py __version__ / CHANGELOG / README badge）。**M5b 发布仓**：`git subtree split --prefix=harness/iterate-harness` 推送至独立发布仓库 `jingzhao-l/iterate-harness`（同 iterate-plugin 模式，主仓库唯一维护点），仓库描述与 dsh-plugin 无关 topic 不适用、改为 iterate-harness 语义描述。**验证**：tests/test_iterate/ 153 单测全绿（含本轮新增 17 项），全仓回归 1070 passed + 6 skipped（3 个失败均为沙箱环境性：MCP stdio 真连接、插件安装流、bash 超时部分输出行为；另 test_http_flow collection error 为 venv mcp 2.0.0 无 fastmcp 的既有环境问题，stash 验证与本次改动无关）；前端 tsc --noEmit 零错误；install 脚本 bash -n 语法校验通过；语义层/工具层/本轮触碰内核文件 ruff 无新增告警。**残留偏差更新**：v1.12 偏差②已闭合；偏差①（path_rules 读写分支）维持搭载决策不变；逐 hunk diff 审批 + Esc 干预（§11.2.1 v0 优先级②）未纳入本轮，与 PR/CI 模式（优先级③）一并留待下一版本。
- v1.14（2026-08-15）：M6 落地完成（逐修复 diff 审批 + CI/PR 模式），v1.13 残留②③闭合——**M6a 逐修复 diff 审批**：`Settings.iterate` 新增 `require_fix_approval`（默认 False）；query.py `_execute_tool_call` 在权限判定后插入审批门 `_needs_iterate_fix_approval`：三条件全满足才触发（IterateLoopPolicy.require_fix_approval 开启 ∧ 工具 ∈ FILE_MUTATING_TOOLS〔write_file/edit_file/notebook_edit + file_write/file_edit MCP 风格别名〕∧ iterate_state.mode == "normal"——dry-run 评审永不触发）；触发时即便 full-auto 也降级为 requires_confirmation 走交互通道，提示语内嵌 diff 预览（`_fix_approval_reason`：edit 用 old/new 对比、write 用截断原文模拟 -/+ 两段，统一 40 行/每行 200 字符裁剪界）；硬拒绝（保护路径 deny / forbidden_fix_patterns 命中）不参与审批门、绝不被降级为可确认项；审批拒绝即工具返回错误且文件零改动。新增 TestFixApproval 6 项测试（normal 模式提示含 diff 且拒绝后文件不变、批准后正常落盘、gate 关闭/dry-run 不触发、硬拒绝不被覆盖、forbidden pattern 边界覆盖 edit new_str、diff 预览 write/edit 变体裁剪）。**M6b CI/PR 模式**：新模块 `iterate/ci_report.py`（纯函数、防御式）：`latest_report_entry` 取决策日志最后一个含 findings 的 report 条目；`ReportSummary.from_entry` 防御解析（畸形 findings 过滤、totalFindings 回退 len）；`render_github` 按 GitHub Actions workflow commands 规范输出（critical/high→error、medium→warning、low/未知→notice，file=/line= 属性，%/\r/\n/:/, 全量转义）；`render_text` 人类可读摘要；`severity_gate` 退出码策略（none|low|medium|high|critical，默认 high，非法值回退默认）；报告缺失/畸形降级为空报告不崩管道。CLI 新增 `oh iterate report`（--github / --fail-on，--fail-on 非法值报 usage error 退出码 2，缺报告时 stderr 提示 + 空报告退出码 0）；/iterate slash 命令同步 report 子命令（REPL 对等）。新增 test_ci_report.py 28 项测试（Summary 解析×6 / latest_entry×3 / render_github×3 / render_text×2 / severity_gate×6 / CLI 端到端×6 / slash×2）。**版本与分发**：版本 0.3.0 对齐（pyproject / cli.py __version__ / CHANGELOG 0.3.0 条目 / README badge）；README.md / README.zh-CN.md 特性表各增「逐修复 diff 审批」「CI / PR 模式」两行 + CLI 速览补 `oh iterate report`；顺手修复 test_decision_log.py 既有 E741 lint。**验证**：tests/test_iterate/ 187 单测全绿（v1.13 的 153 后 +6 M6a +28 M6b）；全仓回归 1104 passed + 6 skipped（3 个失败与 test_http_flow collection error 均为 v1.13 已记录沙箱/环境既有问题，无回归）；iterate 语义层/工具层/命令层 ruff 全过（cli.py 既有 lint 基线未动）。**残留偏差更新**：v1.13 残留的逐 hunk 审批以「逐工具调用 diff 审批」形态闭合（单次 edit 即单 hunk 场景等价，多 hunk 单调用场景由 40 行裁剪预览覆盖）；Esc 中途干预（暂停/改向运行中闭环）仍未实现，为下一版本候选；GitHub 主仓 10 项 dependabot 告警（5 high，上游 fork 继承依赖）仍待单独排查。
- v1.15（2026-08-15）：v1.14 两项残留全部闭合——**Esc 中途干预（§11.2.1 v0 优先级②剩余半项）**：① `loop_policy.py` 增 pause 通道：`LoopDecision.paused` 字段 + `IterateLoopPolicy.pause_requested` / `request_pause()` / `clear_pause()`；`_decide` 仅在「本将继续注入下一轮」分支消费 pause（stop 决策路径顺带清 flag，pause 在无新聚合的 turn 上存续等待下一个轮边界）。② `query.py` turn 末控制块：`decision.paused` 时经 `context.ask_user_prompt`（复用既有 question modal，前端零改动）弹干预菜单（`_handle_iterate_pause`）：`s`=跳过当前 top finding / `n <dims>`=收窄维度 / `x`=直接停 / 空=恢复原下一轮指令（原 inject 保留在 decision 上）；答案映射为对应注入指令（prompts.py 新增 `pause_menu_question` / `skip_current_finding_instruction` / `narrow_dimensions_instruction`）；headless 无交互通道默认安全停止；prompt 通道异常兜底停止；每次干预落决策日志（type=decision、kind=intervention，best-effort 不阻断控制流）。③ `backend_host.py` `_interrupt_active_request` 优雅优先：policy 存在 ∧ pause 未挂起 ∧ tool_metadata 含 iterate_state（闭环已启动）→ 置 pause + 系统 transcript 提示「下一轮边界暂停，再按 Esc 强制打断」，不取消 task；第二次 Esc（pause 已挂起）回落既有硬取消；非 iterate 会话保持上游硬取消行为不变。④ `QueryEngine.submit_message` 起新意图清除残留 pause（`iterate_policy=False` 显式关闭场景经 getattr 防御兼容，修复回归）。⑤ QueryEngine 新增 `iterate_policy` 只读属性（backend 访问通道）。**Dependabot 排查修复（10 项全清，5 high）**：全部为上游继承的 npm 工具链告警——autopilot-dashboard：vite ^6.3.2→^6.4.3（连带修复 postcss×3/esbuild/@babel/core）；frontend/terminal：marked ^18.0.0→^18.0.9、tsx ^4.19.2→^4.23.12（esbuild 0.27.4→0.28.2）、ws 8.20.0→8.21.3（lockfile 经 npm audit fix）；两包 npm audit 均 0 告警，vite build 与 tsc --noEmit 验证通过。**测试**：新增 11 项（TestPauseMechanics 5：paused 决策保留原注入/无请求不暂停/跨 noop turn 存续/stop 清 flag/clear_pause；TestEscIntervention 6：x 停止且第二响应不消费/s 注入跳过指令/n 注入收窄指令/空恢复原始下一轮/headless 默认停/干预落日志）+ backend_host 优雅中断 1 项（首 Esc 暂停不取消、次 Esc 强制取消）；FakeApiClient 增 on_stream 回调模拟运行中按 Esc。**版本与验证**：版本 0.4.0 对齐（pyproject / cli __version__ / CHANGELOG / README badge）；README 双语特性表增「Esc 中途干预」行；tests/test_iterate 198 全绿（187+11），engine+react_backend 54 绿，全仓 1115 passed + 6 skipped（3 失败均为 v1.13 已记录环境性）；触碰文件 ruff 全过。**残留说明**：Esc 干预菜单当前为 question modal 自由文本协议（s/n/x），未做专属方向键菜单组件（v1 候选）；dependabot 告警需推送后由 GitHub 自动重扫关闭。
- v1.16（2026-08-15）：0.5.0「数据沉淀起步 + 体验补齐」落地，v1.15 残留的方向键菜单候选闭合——**① finding 指纹趋势库（§11.2.1 沉淀类）**：新模块 `iterate/trend_store.py`（纯函数 + 防御式）：`finding_fingerprint` 以 `file|line|dimension` SHA-1 为稳定指纹（line 仅在正整数时参与，无行号 finding 视为文件级 `"0"`；缺 file/dimension 返回 None 不追踪）；`record_run` 在 report 条目落决策日志时由 `iterate_tools.py` `_record_trend` 挂接（best-effort，异常仅记 error 不破坏闭环）；分类学：**new**（库中首见）/ **fixed**（上轮 open 本轮缺席，记 fixed_at）/ **regressed**（曾 fixed 本轮复现，runs 续接）/ **stubborn**（open 且 runs≥3）；存储 `.iterate/trend-library.json`（临时文件+rename 原子写，损坏重置为空，2000 条 last_seen LRU 剪枝）；暴露面：`oh iterate log --trend`（cli.py）/ `/iterate trend` 与 `/iterate log trend`（slash）；`summarize`+`render_trend_summary` 输出顽固 finding Top20（file:line dimension severity runs summary）。**② Esc 干预菜单组件化（v1.15 残留闭合）**：新交互通道 `AskUserSelect = (title, options) -> value` 全链路接线（query.py QueryContext.ask_user_select → query_engine 构造器 → ui.runtime → backend_host `_ask_select`）；backend 以 `modal_request` 携 `kind=select_prompt`（request_id/question/options/cancel_value，复用 `_question_requests` 应答通道即 question_response）；前端 App.tsx 拦截 select_prompt：↑↓ 导航 / Enter 选定 / 数字键快选 / Esc 提交 cancel_value（安全首项），渲染复用 SelectModal 组件；query.py `_handle_iterate_pause` 拆分 select/text 双路径：select 路径弹 4 选项菜单（prompts.py `pause_menu_title`/`pause_menu_options`：resume 置首保证 Esc 取消安全、skip、narrow→追问维度经 `narrow_dimensions_question`（空答案降级 resume）、stop），text 路径保留 v1.15 自由文本 s/n/x 兜底（非 TUI 前端）；select 通道异常兜底安全停止。**③ 断点续跑画面（§11.2.1 摸类）**：新模块 `iterate/last_state.py`：`summarize_last_run` 从决策日志提取最后一次收尾摘要（mode/verdict/rounds〔全日志最大轮〕/totalFindings/四档 severity 桶/Top3 finding 预览〔summary 截 120 字符〕/lastIntervention〔最后一个 kind=intervention 条目〕/entryCount，畸形数据全防御返回 None）；backend_host 启动 ready 后 `_emit_last_loop_state` 发 `last_loop_state` 事件（protocol.py 新事件型，复用 state 字段；摘要失败仅 warning 绝不阻断启动）；前端 useBackendSession 增 `parseLastLoopState` 防御解析 + lastLoopState 状态；新组件 `IterateResumePanel.tsx`（◉ last iterate run 一行摘要 + finding 预览 + last intervention + `/iterate resume`·`/iterate trend` 入口提示；live review_progress 出现即自动让位）；配套 `/iterate resume` slash 子命令（无历史友好提示；有历史经 prompts.py 新增 `resume_kickoff` 提交续跑提示词——嵌入上轮 verdict/rounds/findings 预览，指示先 iterate_log 重读日志、复核仍复现的 finding、不复报已消失项、续跑前落 resume 决策条目）；session_storage `_PERSISTED_TOOL_METADATA_KEYS` 增 `iterate_state`（跨重启保留轮次历史/收敛计数，`oh iterate resume` 恢复的是真实 mid-loop 状态）。**测试**：新增 test_trend_resume_ui.py 22 项（指纹稳定性与行敏感/不可追踪 None/new-fixed-regressed 生命周期/3 轮顽固/畸形 finding 跳过/损坏库重置/summarize+render 含顽固与友好空态/last_state 无历史 None+字段提取+未知 severity 忽略//iterate trend 与 log trend 渲染/resume 无历史与 kickoff 提交/select 菜单 resume-stop-skip-narrow 追问-narrow 空降级-通道异常安全停）。**版本与验证**：版本 0.5.0 对齐（pyproject / cli __version__ / CHANGELOG 0.5.0 条目 / README badge）；README 双语特性表增「finding 指纹趋势库」「断点续跑」两行、Esc 行更新为方向键菜单描述、CLI 速览补 `oh iterate log --trend`；tests/test_iterate 220 全绿（198+22），全仓 1138 passed + 6 skipped（3 失败 + test_http_flow collection error 均为 v1.13 已记录环境性，无回归）；前端 tsc --noEmit 零错误；触碰文件 ruff 全过。**残留说明**：changed-only 快审、批量/定时评审（0.6.0 范围）与 HTML 单文件报告、评审回放、per-dimension 资源解锁（v1.0 范围）未启动。
- v1.17（2026-08-15）：0.6.0「无人值守场景扩展」落地，v1.16 残留的 changed-only 快审 + 批量/定时评审两项闭合（§11.2.1 跑类「批量/定时：一条命令审 10 个仓库出排行；cron 每天跑，只报新增问题」）——**① changed-only 快审**：新模块 `iterate/git_scope.py`（纯 subprocess 管道，15s 超时，全失败软返回）：`validate_ref` 以白名单正则（`^[A-Za-z0-9_][A-Za-z0-9_./~^-]*$`，支持 HEAD~3/HEAD^2/origin/release-1.2）防 git 选项注入（subprocess 本就走 list argv，双保险）；`detect_repo_root` 经 `git rev-parse --show-toplevel`；`collect_changed_files` 合并 `git diff --name-only <ref>` + `git status --porcelain`（重命名只取新路径、剥引号、仅磁盘上真实存在的文件入选、去重排序、200 文件硬上限）；ref 不存在时 diff 失败软降级到 status 兜底。注入链路四层：prompts.py `changed_scope_clause`（kickoff 内嵌 JSON 文件清单并指示传给 plan 工具）挂入 `dry_run_kickoff`/`normal_kickoff`（新增可选 `changed_files` 参数）；review.py `build_review_plan` 非空清单时 scope 强制翻转为 `changed-only` 并透传 `reviewer_task_prompt`（新增 changed_files 参数，逐文件列出「review ONLY these files」）；`IterateReviewInput` 新增 `changed_files` 字段、`_plan` 透传。双入口：CLI `oh iterate review|run --changed [--ref <ref>] [--clean-ok]`（`--clean-ok` 空变更优雅退出 0，为定时场景防噪声）与 slash `/iterate review|run --changed [--ref]`（干净树/非 git 仓友好提示不提交、非法 ref Rejected）；usage 帮助同步。**② 批量多仓评审 + 排行**：新模块 `iterate/batch.py`：`run_batch` 顺序逐仓走 headless print 管线（`run_print_mode(cwd=repo)`，per-repo stdout 经 redirect_stdout 捕获、单仓异常仅降级为 error 记录绝不中断整批；changed-only 默认，干净树直接 short-circuit 为 clean 状态零成本跳过，`--full` 全量；`_reviewed_record` 复用 ci_report.ReportSummary 从各仓决策日志读 verdict/totalFindings/severity）；`rank_records` 排序策略 reviewed（score 降序）> clean > error；`repo_score` 严重度加权 critical 10/high 5/medium 2/low 1；`render_ranking` ASCII 表格（repo/status/findings/c·h·m·l/score/verdict/note）。CLI `oh iterate batch <repo...> [--ref] [--rounds] [--full] [--mode] [--json]`。**③ 定时评审（cron）**：复用既有 cron 注册表/守护进程（注册表 `~/.openharness/data/cron_jobs.json` 文件锁读改写、守护进程 `oh cron start` 30s tick、历史 `cron_history.jsonl`）；`build_scheduled_command` 生成 `oh iterate review --changed --clean-ok --ref <ref> --rounds N`（normal 模式换 run 子命令）；`install_schedule` 校验 cron 表达式（croniter）与 ref 后 upsert `iterate.review-changed` 任务（携 cwd 与 timeout）；cron schema 增可选 per-job `timeout` 字段（`execute_job` 原硬编码 300s 改为 `_job_timeout`：默认 300、钳位 [1,7200]、非法值回退默认；超时 stderr 消息同步动态化）——多轮 agent 评审默认给 3600s；CLI `oh iterate schedule add <cron> [--ref/--rounds/--mode/--timeout]` / `schedule remove` / `schedule status`（含 cron_history 最后一次执行态）；「只报新增问题」由趋势库承接（`oh iterate log --trend` 的 new/stubborn 分类），定时任务本身零 LLM 判定。autopilot 子进程任务模式为既有先例，本设计沿用子进程而非 in-process 回调（改 job schema+handler 注册表超出最小集成）。**测试**：新增 test_changed_review.py 23 项（validate_ref 合法/非法集、仓外空/干净树空/diff+untracked+rename 收集/200 上限钳位/坏 ref status 兜底、plan 钉 scope 与清单嵌入/无清单保持配置 scope/空白项过滤、dry_run+normal kickoff 内嵌与无 delta 不变、工具 plan 操作端到端、slash review --changed 提交与 clean 友好与非法 ref 拒绝与 run --changed、无 flag 保持 full、_parse_changed_flags 默认/ref 取值/缺值回退）+ test_batch_schedule.py 18 项（scheduled command 两模式格式与非法 ref、install 非法 cron/mode 拒绝、upsert 去重替换与 remove 幂等、status 报 job+历史、_job_timeout 默认/覆盖/钳位/非法、execute_job 真实 1s 超时记 history、repo_score 权重、rank worst-first、render 表格、_reviewed_record 读决策日志、run_batch clean 短路/缺仓 error/坏 ref error/混合仓库各一记录；cron 注册表经 OPENHARNESS_DATA_DIR 隔离）。**版本与验证**：版本 0.6.0 对齐（pyproject / cli __version__ / CHANGELOG 0.6.0 条目 / README badge）；README 双语特性表增「changed-only 快审」「批量排行」「定时评审」三行、CLI 速览补 `--changed`/`batch`/`schedule add`；tests/test_iterate 261 全绿（220+23+18），触碰文件 ruff --fix 清零（import 排序/UTC 别名）；CLI `oh iterate --help` 冒烟确认 batch/schedule 挂载。**残留说明**：HTML 单文件报告、评审回放、per-dimension 资源解锁（v1.0 范围）未启动；cron 全 UTC 无本地时区（注册输出已提示 UTC）。
- v1.18（2026-08-15）：1.0.0「首个稳定版」落地，v1.17 残留的 v1.0 三项全部闭合——**① HTML 单文件报告（§11.2.1「看类：HTML 单文件报告——收敛曲线、severity 分布、内嵌 diff，可直接发给别人看」）**：新模块 `iterate/html_report.py`（纯函数、防御式、零外部依赖）：`build_html_report` 复用 ci_report.latest_report_entry 取最新 report 条目，渲染为 ONE 自包含 `.html`（内联 CSS、零 script、零外链 http/https——CI 产物可离线打开）；内容分层：头部（verdict/mode/converged 三徽标 + goal + 收尾时间戳/轮次）、summary 卡片（total/critical/high/rounds）、**SVG 收敛曲线**（convergence.findingsByRound 折线 + 逐点数值标注，空序列降级占位文案）、severity 与维度分布横条（固定色表）、findings 全表（severity 徽标/file:line/dimension/summary/failure_scenario/suggested_fix）、**修复时间线**（report 之前的 atomic_fix/revert/validation 条目，≤50 条，atomic_fix 携 diff 字符串时渲染 +/- 着色的 `<pre class="diff">`）；安全：全部日志衍生文本经 html.escape(quote=True)，severity 颜色仅来自固定映射表（critical #b91c1c/high #ea580c/medium #ca8a04/low #2563eb），日志内容无法注入标记或 CSS。入口：CLI `oh iterate report --html [path]`（'-' 或缺路径默认 `.iterate/report.html`，父目录自动创建；--fail-on 门禁语义不变——CI 可同时上传产物并按严重度卡退出码）与 slash `/iterate report --html`（写文件后附 text 摘要）；报告缺失时 CLI stderr 提示且不落文件。**② 评审回放（§11.2.1「log --replay 按时间序回放每轮决策，像看录像」）**：新模块 `iterate/replay.py`：`build_replay_lines` 按日志原序逐条输出 `[+相对秒] r轮次 类型(16列对齐) 摘要   (绝对时间戳)`——相对偏移以首条可解析时间戳为原点（不可解析降级 `[+?s]`）；每类型摘要按优先键探测（round_start→goal/dimensions/mode、review_result→newFindings/totalFindings、atomic_fix→summary/file、validation→command/status、report→verdict/totalFindings 等），未知类型回退截断 JSON 预览、空载荷 `(no payload)`、长文本 140 字符截断（空白折叠）；尾部 `(N entries replayed)` 计数。入口：CLI `oh iterate log --replay` 与 slash `/iterate log --replay`；空日志友好占位。**③ per-dimension 资源解锁（§11.2.1 三「维度配置体系解锁项」首个子项：per-dimension model/concurrency/token_budget）**：types.py 新增 `DimensionResources`（model/concurrency/token_budget 三可选字段 + is_empty()，未设即继承会话默认）；IterateConfig 增 `dimension_resources: dict[str, DimensionResources]`；config_loader 新增 `parse_dimension_resources`（防御解析：非映射条目/非字符串 model/非整数 concurrency/负数 token_budget 记入 errors 并跳过绝不 raise，concurrency 钳位 [1,8]）与 `resources_to_dict`（仅序列化已设字段）；`validate_config` 同步校验并透出 resource 错误；merge_config 递归合并保持 Master+Overrides 语义。流转链路：review.py `DimensionPlan` 增 `resources` 字段，`build_review_plan` 按维度名从 config 取资源注入并在 reviewer_prompt 末尾追加显式派发指令（"Resource plan: model=…; max concurrent reviewer agents=…; token budget=…"——当前架构下 reviewer 由模型经 agent 工具派发，prompt 是计划的执行通道）；`plan_to_dict` 序列化 `resources`（空资源维度不输出该键）；`/iterate config` 列出生效的 per-dimension 资源。**测试**：新增 test_html_report.py 11 项（无 report 返回 None、单文件结构 DOCTYPE→</html> 且零 script/零外链、图表+表格+时间线渲染、XSS 转义 img/onerror、无 findings 与空收敛与空时间线占位、时间线 50 条上限、CLI --html 默认路径写入与缺报告不落文件、slash report --html 写文件）+ test_replay.py 10 项（空日志友好、相对偏移 0/90/300s 与摘要键探测、坏时间戳降级、未知类型 JSON 预览、空载荷占位、500 字符截断、render 拼接、slash 与 CLI --replay 双入口、CLI 空日志）+ test_dimension_resources.py 12 项（parse 全字段/钳位/非法类型计数/非映射根、load_effective_config 读 yaml、validate_config 报错与放行、plan 携带 resources+prompt 指令+无资源维度无指令、plan_to_dict 序列化与省略、默认配置全 None、/iterate config 展示）。**版本与验证**：版本 1.0.0 对齐（pyproject / cli __version__ / CHANGELOG 1.0.0 条目 / README badge 双语）；README 双语特性表增「HTML 单文件报告」「评审回放」「per-dimension 资源」三行、CLI 速览补 `log --replay`/`report --html`；tests/test_iterate 294 全绿（261+11+10+12），全仓回归 1212 passed + 6 skipped（3 失败均为 v1.13 已记录沙箱环境性：MCP stdio 真连接、插件安装流、bash 超时部分输出，无回归）；本轮触碰文件（html_report/replay/config_loader/review/types/commands/iterate/cli 局部 + 三个新测试文件）ruff 全过（cli.py 既有 lint 基线未动）；CLI 直接函数调用测试显式传全部 typer 参数（OptionInfo truthy 陷阱修复）。**残留说明**：per-dimension 资源的 token_budget 目前为计划层声明（随 prompt 派发），引擎级按维度 token 硬预算（cost tracker 按维度切分）与维度级阈值门禁（max_critical/max_high 对接 PR 门禁）留待 1.1；cron 仍全 UTC。
- v1.19（2026-08-15）：1.1.0「策略层」落地，v1.18 残留的三项全部闭合——**① 整轮 token 预算引擎级强制**：`iterate.config.yaml` 新增顶层 `token_budget`（正整数，`parse_token_budget` 防御解析：bool/非正/非整数记入 validate_config 错误并跳过，绝不致命）；`query_engine._default_iterate_policy` 将其注入 `IterateLoopPolicy.total_token_budget`；`loop_policy.on_turn_end` 在 cost_meter 累加后**先于**聚合快照判定 `_budget_stop_reason`（`used > budget` 即返回 `token budget exhausted (used/budget tokens)` 停止决策——预算强制不依赖本轮是否有新 aggregate，无快照时构造默认快照走停止路径并携带 progress）。**② per-dimension 预算审计**：review.py 新增 `BudgetAudit`/`audit_dimension_budgets`（纯函数：只审计配置了预算的维度，used 防御钳位 ≥0，未报告维度计 0；`all_budgeted_exhausted` 仅当全部预算维度超限）；入口 `IterateReviewInput.dimension_usage`（aggregate 操作可选字段），`iterate_tools._audit_budgets` 读取生效配置中带 `token_budget` 的 `dimension_resources` 比对（bool 值剔除、max(0,int) 归一），审计结果双通道输出：payload 增 `budgetAudit` 块（dimension/budget/used/remaining/exceeded 行）+ loop-policy state 增 `exhausted_dimensions`/`all_dimensions_exhausted`；`loop_policy` 消费：全部超限→停止（reason 列出维度），部分超限→`next_round_instruction` 追加「Token budgets are EXHAUSTED for: …— do NOT spawn reviewer agents for these dimensions this round」显式派发指令（prompts.py 新增 exhausted_dimensions 参数）；审计异常绝不破坏聚合（无预算/无上报时省略整块）。**③ 维度阈值门禁**：types.py 新增 `DimensionThresholds`（max_critical/max_high 可选）与 `ThresholdsConfig`（全局 + dimensions 字典，`is_empty()`）；config_loader 新增 `parse_thresholds`（防御解析：负数/bool/非整数/非映射逐条记错跳过）/`thresholds_to_dict`（仅序列化已设字段）/validate_config 集成；review.py 新增 `ThresholdGateResult`/`evaluate_threshold_gates`（纯函数：global 与 `dimension:<dim>` 两级 scope，`actual > limit` 才违规，violation 形如 {scope,metric,limit,actual}）；`iterate_tools._meta_review` 读取项目 thresholds 评估后传入 `meta_review.build_final_review_report(threshold_result=…)`——失败门禁逐违规折叠 `THRESHOLD_EXCEEDED`（severity=high）meta-review issue 并把 verdict 翻转为 needs_revision，finalReport 携 `thresholdGate` 块（未配置 thresholds 时省略）；canonical-loop prompt（prompts.py 步骤 6）指示模型把 thresholdGate 原样复制进唯一 report 条目；CI 闭环：ci_report 新增 `threshold_gate(entry)`（防御提取 report 条目 thresholdGate 块）/`threshold_exit_code`（present∧failed→1）/`render_text` 增门禁状态行（`threshold gate: PASS/FAIL`，违规内联 `scope:metric actual>limit` 最多 5 条 + `(+N more)`）；CLI `oh iterate report` 退出码 = max(severity_gate, threshold_exit_code)。**④ cron 本地时区**：cron.py 新增 `validate_timezone`（ZoneInfo 探测，容忍首尾空白，Unknown/ValueError/KeyError 均 False）；`next_run_time` 增 tz_name 参数——表达式在 IANA 区本地时间求值后 `astimezone(utc)` 归一化存储（09:00 Asia/Shanghai → 01:00 UTC），未知区 raise ValueError；`_recompute_next_run` 统一 upsert/mark_job_run 两处重算路径（存储的未知区回退 UTC 容错旧条目）；`install_schedule` 增 timezone 参数（安装时校验，无效 raise ValueError），job 携 `timezone` 键；CLI `schedule add --timezone`（空串→None 兼容 typer）；scheduler due 判定不变（比对 UTC 归一化 next_run）。**测试**：新增 test_budget_thresholds.py 28 项（audit：预算内/超限/部分 vs 全部超限/无预算/未上报计 0/负数钳位/to_dict；gates：空配置通过/critical 超限/恰等 limit 通过/high 超限/per-dimension 只计本维度/未配置维度无门禁/多违规全报；config：token_budget 合法非法集/thresholds 往返/非法逐条记错/非映射拒绝/None 默认；meta 折叠：失败门禁翻转 verdict+issue/通过保持；loop policy：整轮预算停止/预算内继续/无快照仍停止/全维度超限停止/部分超限注入指令/prompt 列出维度）+ test_ci_report.py 增 9 项（threshold_gate 提取/缺失畸形 None/exit_code 三态/render 门禁行 FAIL 含双违规/PASS/5 条封顶(+2 more)/CLI 低严重度+失败门禁退出 1/通过门禁退出 0）+ test_batch_schedule.py 增 TestScheduleTimezone 9 项（validate_timezone 合法非法集/本地求值 09:00 上海→01:00 UTC/无区保持 UTC/未知区 raise/install 拒绝未知区/存储携 timezone 且 next_run +00:00/无区省略键/mark_job_run 重算仍 UTC 归一/_jobs_due 在 01:00 UTC 判到期）+ test_iterate_tools.py 增 5 项（aggregate dimension_usage 出 budgetAudit+state 超限维度/无预算省略/meta-review 配置 thresholds 出 thresholdGate 翻转 verdict+THRESHOLD_EXCEEDED/未配置省略）。**版本与验证**：版本 1.1.0 对齐（pyproject / cli __version__ / CHANGELOG 1.1.0 条目 / README badge 双语）；README 双语特性表增「token 预算强制」「阈值门禁」「定时评审时区」三行；tests/test_iterate 343 全绿（294+49），全仓回归 1261 passed + 6 skipped（3 失败 + test_http_flow collection error 均为 v1.13 已记录沙箱环境性，无回归）；触碰文件 ruff 全过。**残留说明**：dimension_usage 依赖 reviewer 上报（prompt 指令通道），引擎未按维度切分 cost meter（后续可在 agent 工具层回传真实 usage）；阈值门禁指标暂只有 max_critical/max_high，可按需扩展 medium/low 或自定义 metric。
- v1.20（2026-08-15）：1.2.0「日常驾驶人机工程」落地，v1.19 残留的引擎级 per-dimension usage 回传闭合 + §11.2.1 看类「init 检测式向导」与跑类「git hook：commit 前 30 秒 changed-only 快审」两项补全——**① 检测式 init 向导（§11.2.1 看类最后一项）**：新模块 `iterate/init_wizard.py`（纯函数 + 防御解析）：`detect_project` 探测 11 种标记文件（package.json/pyproject.toml/setup.py/requirements.txt/go.mod/Cargo.toml/Gemfile/pom.xml/build.gradle(.kts)/composer.json）按语言去重推断栈（node/python/go/rust/ruby/java/php）；测试命令**只来自显式证据**（真实 `scripts.test` 条目→`npm test`、pyproject 含 pytest→`pytest -q`、tests/ 布局兜底、go.mod→`go test ./...` 等），未知栈绝不发明可信命令；前端框架依赖（react/vue/svelte/next/nuxt/@angular/core）解锁 `frontend-backend`/`ui-ux` 维度；畸形 package.json 降级为 evidence 注记不 raise。`build_config_dict`/`render_config_text` 经 `yaml.safe_dump` 序列化（goal 文本不可注入 yaml 结构），头部注释标注 commands 精确匹配语义；`parse_dimension_selection` 支持序号/名称混选（`2,4`/`security ui_ux`，下划线归一，越界/未知返回 None 重询）；`write_config` 确认后才落盘。入口：CLI `oh iterate init [--yes/-y] [--force] [--goal]`（evidence 逐行打印 + yaml 预览 + 确认写入；存在配置无 --force 拒绝）与 slash `/iterate init [--force]`（TUI 内同效，预览后直接写入并提示下一步）。**同日修复**：替换 v1.12 遗留的旧 marker-lite `init` 命令（删除 `_ITERATE_DIMENSIONS`/`_detect_project`/`_has_script`/`_render_config_yaml` 及旧命令体，消除 F811 重复定义与 cli.py 一处 f-string 语法错误——该错误此前已阻断 test_ci_report 收集）。**② 托管 pre-commit 钩子（§11.2.1 跑类最后一项）**：新模块 `iterate/git_hook.py`：`install_hook` 经 `git rev-parse --show-toplevel` 解析仓根（子目录调用正确归位；非 git 仓 raise HookError），写 MARKED（`# iterate-harness pre-commit hook`）`.git/hooks/pre-commit`（0755）——对已存在且无标记的第三方钩子（husky 等）**拒绝覆盖**，仅可替换自家托管钩子；`--fail-on` 白名单校验（none|low|medium|high|critical，默认 high）；生成脚本为纯 POSIX sh（`sh -n` 语法校验入测试）：ITERATE_SKIP_HOOK=1 短路 → 绝对路径 `oh`（安装期 `shutil.which` 解析，钩子环境常缺用户 PATH）跑 `iterate review --changed --clean-ok --ref HEAD --rounds 1`（单轮快审）→ `exec oh iterate report --fail-on <sev>`（复用 CI 退出码门禁，commit 按严重度放行/阻断；`git commit --no-verify` 原生跳过）；`uninstall_hook` 同样拒绝摘除外来钩子、缺席幂等返回 False；`hook_status` 输出 installed/managed/path/skippable（非 git 仓降级 error 字段不 raise）。CLI `oh iterate hook install|uninstall|status`（typer 子应用挂 iterate_app）。**③ 引擎级 per-dimension usage 回传（v1.19 残留①闭合）**：`iterate_tools._aggregate` 把消毒后的 `dimension_usage`（bool 剔除、max(0,int) 钳位）发布进 loop-policy state（与 budgetAudit 独立——无预算配置也回传）；`AggregateSnapshot` 增 `dimension_usage` 字段、`read_state` 防御解析（非映射/非整数值条目丢弃）；`IterateLoopPolicy.on_turn_end` 在正常轮与预算停止两条路径均经 `_record_dimension_usage` 将各维度累计值中继进 `CostMeter.record_dimension_total`（**单调 max** 语义——aggregate 上报的是 running total，取 max 绝不累加重复计数），`format_summary()` 按维度输出「dimension X: N tokens (reviewer-reported)」；维度上报**不进** total_tokens/total_cost_usd（主循环口径不被子代理污染）。**测试**：新增 test_init_wizard.py 18 项（node 检测 test 脚本+react 解锁/畸形 package.json 降级、python pyproject/布局兜底、go/rust/java/php 四标记、多 python 标记去重、未知栈 base 维度、build_config 含/不含 validation、yaml 注入安全（goal 恶意文本保持标量）、写盘经 load_effective_config 往返、选择解析空保全部/序号名称/下划线归一/去重保序/越界未知 None 参数化）+ test_git_hook.py 16 项（渲染含守卫/二进制/门禁、`sh -n` 语法、单轮常量、安装写 0755 托管钩子、替换自家、拒绝外来、拒绝非法严重度、非 git 仓拒、卸载移除/缺席 False/拒外来、status 三态、子目录解析；PATH 注入 autouse fixture 兼容沙箱）+ test_loop_policy.py 增 TestDimensionUsageRelay 5 项（新聚合记录/running total 单调 max/重复聚合不双计/预算停止路径仍记录/不污染主循环 total_tokens）+ test_iterate_tools.py 增 2 项（无预算也发布 dimension_usage/负值钳位）。**版本与验证**：版本 1.2.0 对齐（pyproject / cli __version__ / CHANGELOG 1.2.0 条目 / README badge 双语）；README 双语特性表增「检测式 init」「pre-commit 钩子」两行、token 预算行补 usage 回传描述、CLI 速览补 `hook install`；tests/test_iterate 383 全绿（343+40），全仓回归 1286 passed + 6 skipped（2 失败为 v1.13 已记录沙箱环境性：插件安装流、bash 超时部分输出，无回归；test_http_flow collection error 同为既有 venv mcp 包问题，--ignore 验证）；触碰文件 ruff 全过（cli.py 既有 lint 基线 18 条未动，全部为上游风格存量）。**残留说明**：per-dimension usage 仍是 reviewer 上报口径（agent 工具层数据，非 API 计费口径），金额未按维度折算 USD（后续可将 dimension_tokens × 对应模型价格入 meter）；init 向导 java/ruby/php 的测试命令为约定建议（evidence 注记提示按 gradle/rspec/phpunit 调整）；钩子单轮评审仍受 review 全链路时长影响（30 秒目标依赖模型响应速度，--fail-on=none 可退化为纯记录）。
