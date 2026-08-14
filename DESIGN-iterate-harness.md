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
4. 版本号全项目统一（遵循既有硬约束）。

## 10. 风险与开放问题
- 桥接性能与稳定性：子进程 / JSON-RPC 的调用开销。
- dsh 演进依赖：新版本是否破坏插件 API。
- 语义层最终落 Python 还是 TS：影响路线 B 是否与插件共享代码。
- SKILL.md 内容是否需为 harness 形态改写（上下文压缩、记忆注入方式）。

## 11. 版本记录
- v1.0（2026-08-14）：首版设计草案。决策点：仓库形态=方案 B 同仓库双模块；落地优先级=先 dsh 最小验证插件。
- v1.1（2026-08-14）：新增 dry-run 纯审查模式（只评审不改文件、多轮收敛出报告）；v0 范围调整为「自治闭环 + 并行评审 + dry-run」；能力边界表补充 dry-run 与自主多轮收敛差异。
- v1.2（2026-08-14）：实现阶段落地 dry-run——新增确定性纯函数引擎 `src/review.ts` 与 `iterate_review` 工具（plan / aggregate 两操作），v0 工具数由 4 更新为 5（config / validate / decision-log / context / review），补充 canonical dry-run 收敛循环模板说明。
- v1.3（2026-08-14）：实现阶段落地自治闭环——`skill-prompt.ts` 补充 normal 模式 canonical 模板（配置→评审计划→并行评审→确定性聚合→原子修复→验证→回环→达标自停）；评审报告类型由 `DryRunReport` 泛化为 `ReviewReport`（mode 支持 dry-run / normal，两模式共用同一确定性聚合引擎），报告新增全局去重/过滤/排序后的 `findings` 字段，供 fixer 直接消费；20 个单元测试全绿。
- v1.4（2026-08-14）：实现阶段补齐 meta-review 报告审计——新增 `src/meta-review.ts`（6 项一致性检查：COUNT_MATCH / SEVERITY_SUM / DIMENSION_SUM / SORT_ORDER / CONVERGENCE / ROUND_SHAPE），`iterate_review` 新增 `meta-review` 操作，dry-run 收敛报告产出前先审计自身一致性并给出 approved / needs_revision 判定；修复 ROUND_EMPTY 误报 bug（收敛轮=最后一轮空属正常成功信号，不再标记为缺陷）；插件经真实 dsh headless 运行时验证：5 个 iterate 工具全部注册、系统提示成功注入、aggregate + meta-review 端到端输出符合预期；新增 README 使用说明；33 个单元测试全绿。
