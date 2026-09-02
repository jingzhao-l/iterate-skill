# iterate-skill 设计文档 v3.0

> 目标：把 iterate-skill 从「审查-修复-收敛命令」升级为「深度贯彻防御式编程理念、以 iterate 闭环为主体的编程 agent skill」。
> 状态：v2 稳定期已实现（当前 2.12.0）；**v3.0 设计启动：防御式编程 AI agent skill**；设计文档迭代至 v3.0。
> 版本记录：见文末。

> **v3.0 设计主线（新增，保留 v2 全部内容不变）**：见 §6-§10。核心变化——① skill 从"审查命令"升级为"防御式编程 AI agent skill"，以 iterate 闭环为骨架；② 宿主 AI 调用后按"动手前 / 动手时 / 动手后 / 收尾"四步防御式协议执行；③ CLI 新增 `guard pre-check / post-check` 与 `invariant` 确定性校验；④ 与 harness 2.0（自执行形态）共享同一套防御式编程术语与配置，互为指令形态 / 执行形态。

---

## 1. 背景与现状回顾（v2 承载）

> 本节记录 v2 系列已实现能力（保留，作为 v3.0 迭代的基线），后续版本迭代不得删减本节内容。

### 1.1 项目定位
- **iterate-skill** 是 iterate 生态的「Core Skill + CLI」组件：一个可移植、可配置的 AI 编程助手技能（`/iterate` + `iterate` CLI）。
- 解决的核心痛点：AI 助手"说得多、做得浅"——一次对话只改几行、看过一个文件不再管全局、很少回头复核自己改坏的东西。iterate 把这些收尾工作（逐项审查、分维度排查、修复、验证、再迭代）自动化。
- 运行机制（自闭合流水线）：
  ```
  定目标 → 多维度并行审查 → 原子修复 + 架构修复（需你批准）→ 验证 → 再审查 → 循环直到收敛 / 达轮数上限 → 输出总结
  ```
- 生态关系：skill（跨助手对话式）/ harness（无头引擎）/ plugin（dsh 桌面插件），三者共用同一套 `iterate.config.yaml` 与 9 维度审查体系。

### 1.2 v2 已实现能力清单（当前发布 2.12.0）
- **9 维度并行审查**：correctness / security / performance / architecture / style-tests / tech-debt / spec-compliance / frontend-backend / ui-ux。
- **双轨修复**：原子问题（≤20 行、单文件）自动修；架构问题经用户批准后再修。
- **Git 隔离**：每轮在独立 `iterate/*` 分支或 worktree 中完成；merge/push 默认关闭，需显式开启。
- **Secure-by-default**：`push_per_round` 和 `auto_merge` 默认均为 `false`。
- **命令白名单**：配置时 + 个性化时双层校验，拒绝危险 shell 元字符。
- **校验和验证**：从 GitHub Release 更新时强制 SHA256 校验。
- **多助手支持**：Trae / Claude Code / Cursor / Windsurf / GitHub Copilot / Codex / Roo Code 等 25+ 工具。
- **项目知识库**：自动生成 `ITERATE.md` + `iterate.config.yaml`，支持漂移检测和增量刷新。
- **CLI 命令集**：`onboard`（初始化向导）/ `personalize`（9 类个性化）/ `refresh`（增量刷新调和落盘）/ `doctor`（健康检查）/ `config`（含 2.12.0 新增 `--json` 结构化输出）/ `status` / `show` / `scan` / `dimension_sets` / `tui`。
- **范围审查蓝图 `dimension_sets`**（2.11.0）：按 `frontend` / `api` / `security` / `performance` / `style-tests` 等命名集预设维度组合；`refresh` 保留用户自定义集并增量补入新检测层集。
- **范围路由 + 偏门范围重定义（2.11.0-2.11.1）**：指定目标优先匹配命名维度集；未命中时从维度全集重新推导（禁抄预设，决策日志记录 `Scope Dimension Redefinition` 小节并机器校验）。
- **防御式实现基线**：`refresh` 调和结果真正落盘、doctor 畸形白名单不再绕过元字符安全网、wizard 重跑不丢数据、validate.py 重定义区块切分修复、publish_qoder zip-slip 防护与 shell 注入面修复（2.11.2）。
- **测试基线**：全量 Python 测试 888 个全部通过，`ruff check .` 通过。

### 1.3 v2 的边界与 v3.0 升级动机
- **物理约束**：skill 只会在用户**显式调用 `/iterate`** 时被触发，平时不在 agent 上下文内。因此 v2 的每次调用是"一次独立的审查-修复-收敛"。
- **升级动机**：v2 的 iterate 闭环已经做到了"审查环节的防御"（发现并修复问题），但**编码过程本身的防御性**尚未贯彻——宿主 AI 在写代码时仍可能"乐观假设、越界信任、带病继续"。v3.0 把防御式编程从"审查时执行"前移到"编码时执行"，让 skill 成为**以 iterate 为主体、深度贯彻防御式编程理念的 AI agent skill**。

---

## 2. 设计原则（v3.0 延续 v2，新增防御式原则）
- **以 iterate 为主体**：审查-修复-验证-收敛闭环仍是 skill 的核心骨架，v3.0 不脱离、不重写，只在骨架之上注入防御式编程纪律。
- **显式调用不变**：尊重"只在 `/iterate` 时触发"的物理约束，防御式协议以"本次调用内的完整任务执行"为载体，不做常驻行为塑造。
- **确定性兜底**：prompt 指令不可靠，防御式理念必须用 CLI 确定性校验落地（`guard` / `invariant`）。
- **契约式思维**：每次动作声明前置/后置条件，用断言守卫假设。
- **快速失败**：错误一发生立即停止、报错、回滚，绝不带病继续。
- **跨形态一致**：与 harness 2.0 code 模式（自执行形态）共享同一套防御式编程术语、机制与配置，保证"指令形态 / 执行形态"行为一致。

---

## 3. 防御式编程概念界定（与 harness 2.0 对齐）

> 本节与 harness 2.0 设计（§20.1.3）保持一致，是生态统一的防御式编程词汇表。

- **防御式编程不是"审查-修复-验证-收敛"流程**，而是**编码时的心智模型**（软件工程经典定义）：
  1. **最小化假设**：假设事情会出错，主动预测并容忍问题，而非乐观假设"应该没事"。
  2. **信任边界验证**：数据从"不可信来源"进入代码的那一刻必须验证；内部状态可信任，**外部输入必须验证**。
  3. **快速失败、响亮失败（fail fast, fail loud）**：错误一发生立即停止、报错、回滚，绝不带病继续。
  4. **前置/后置条件 + 断言**：每个函数声明要求什么（前置）、保证什么（后置），用断言守卫假设。
- 与 iterate 的关系：iterate 已是防御式编程的一种实现（审查环节的防御）；v3.0 把整套心智模型前移到**编码过程本身**。

---

## 4. v3.0 总览：防御式编程 AI agent skill

- **定位变化**：从"`/iterate` 专用审查修复命令" → **"以 iterate 闭环为骨架、深度贯彻防御式编程理念的编程 agent skill"**。
- **心智模型**：`一次性审查命令` → `教宿主 AI 以防御式纪律完成整个编码任务的 agent skill`。
- **实现形态**：纯 prompt + CLI（不引入运行时）。宿主 AI 调用 skill 后，整个任务按 §5 的防御式协议执行；CLI 提供确定性校验兜底（§6）。

---

## 5. 行为协议：宿主 AI 四步防御式执行

宿主 AI 调用 `/iterate`（v3.0）后，整个任务按以下四步协议执行：

| 阶段 | 防御式原则 | 落地动作 |
|---|---|---|
| **① 动手前** | 最小化假设 + 前置条件 | 声明"我假设什么成立"（目标范围、文件存在、git 干净、依赖就绪）；跑 `iterate guard pre-check` 做确定性前置校验 |
| **② 动手时** | 信任边界验证 + 最小步进 | 最小步进修改；每次写入前验证目标路径/命令在白名单；原子修改（复用 fix 的备份/回滚机制） |
| **③ 动手后** | fail-fast + 后置条件 | 每次改动后跑 `iterate guard post-check`（语法/关键测试）；必要时回滚；记录假设是否被证伪 |
| **④ 收尾** | 不变量守护 + 收敛门禁 | `iterate invariant` 检查项目级不变量；9 维度审查 → 修复 → 验证 → 收敛，作为**交付门禁**（不收敛不交付） |

- **保留 v2 全部闭环**：第 ④ 步即 v2 的完整 iterate 闭环（9 维度并行审查、双轨修复、Git 隔离、决策日志），只是新增"不变量守护"与"防御式收尾门禁"。
- **典型示例**：用户输入"iterate on this project, fix all atomic issues" → skill 先跑 pre-check → 并行审查 → 原子修复（每步 post-check）→ 验证 → 收敛 → invariant 校验 → 输出修复统计。

---

## 6. CLI 新增（确定性兜底）

> 防御式理念必须靠 CLI 确定性校验落地（prompt 指令不可靠）。

| 命令 | 用途 | 输出 |
|---|---|---|
| `iterate guard pre-check` | 动手前前置校验（目标存在、git 干净、依赖就绪） | `PASS/FAIL` + 逐项结果；非零码表示未通过 |
| `iterate guard post-check` | 动手后后置校验（语法、关键测试命令） | `PASS/FAIL` + 逐项结果；非零码表示未通过 |
| `iterate invariant` | 项目级不变量检查（构建必过 / 核心 API 签名不变 / 安全边界不可绕） | `PASS/FAIL` + 违反项明细 |

- **不变量来源**：`iterate.config.yaml` 新增 `invariants` 段（命令 + 断言），与既有 `validation.commands` / `command_whitelist` 共用安全基线（白名单校验、元字符防护）。
- **配置兼容**：旧配置文件无 `invariants` 段时，`iterate invariant` 退化为基于 `validation.commands` 的既有验证，零破坏。
- **保留**：onboard / personalize / refresh / doctor / config / status / show / scan / dimension_sets / tui 全部保留不变。

---

## 7. 与 iterate 主体的关系（不脱离）
- **骨架不变**：审查-修复-验证-收敛闭环、9 维度体系、决策日志、Git 隔离、Secure-by-default 全部沿用 v2。
- **新增仅为"纪律层"**：防御式协议（§5）与 CLI 校验（§6）是在既有闭环之上的行为纪律，不替换任何既有机制。
- **语义层一致**：v3.0 不重写 iterate 业务语义，与 harness / plugin 仍共用同一 `iterate.config.yaml`。

---

## 8. 与 harness 2.0 / plugin 3.0 的协同

| 项目 | v3.0 角色 | 协同点 |
|---|---|---|
| iterate-skill（本项目） | 制度与经验生产者 | **指令形态**的防御式编程协议：教宿主 AI（25+ 助手）以防御式纪律干活，是唯一能进入任意助手会话的组件 |
| iterate-harness（2.0） | 执行者 | **自执行形态**：code 模式通用 agent + 防御式内核 + 多 agent 编排；两者共享同一套防御式术语表、机制与配置 |
| iterate-plugin（3.0） | 指挥台 | 门禁视图 / 经验银行 / 防御事件流，与 skill 的 `guard` / `invariant` 结果打通展示 |

---

## 9. 里程碑与验收

| 里程碑 | 内容 | 验收 |
|---|---|---|
| M1 | SKILL.md 注入四步防御式协议 | 宿主 AI 按 ①→④ 执行；v2 全部闭环保留零回归 |
| M2 | CLI `guard pre-check` / `post-check` | 前置/后置校验 `PASS/FAIL` 正确；非零码契约成立；测试覆盖正常/异常路径 |
| M3 | CLI `invariant` + 配置 `invariants` 段 | 不变量检查正确；无 `invariants` 段时退化到 `validation.commands`；命令走白名单/元字符安全基线 |
| M4 | 防御式收尾门禁 | 收敛后强制 `invariant`；不收敛不交付的行为可被测试验证 |

**质量门**：
- 后端：全量 Python 测试通过（在既有 888 项基础上新增 guard / invariant 用例，覆盖正常路径、异常路径与边界场景）；
- 安全：新增校验命令全部沿用既有白名单/元字符安全网，不引入新的 shell 注入面；
- 回归：v2 既有用例零回归。

---

## 10. 风险与开放问题
1. **宿主 AI 遵循度**：防御式协议依赖宿主 AI 遵循 prompt——靠 CLI 确定性校验兜底（无法遵循时 fail），但宿主 AI 可能跳过调用——SKILL.md 中明确"不收敛不交付"作为硬约束。
2. **CLI 校验开销**：每步 post-check 可能增加延迟——默认轻量（语法/关键测试），全量验证仍走收尾收敛。
3. **不变量误报**：`invariants` 定义过强会导致频繁 fail——提供 `known_invariant_violations` 显式豁免机制（对齐既有 `known_intentional`）。
4. **跨助手一致性**：不同宿主 AI 对协议遵循度不同——通过 CLI 结果作为唯一事实源，prompt 仅作引导。

---

## 11. 版本记录
- v1.0-v2.12.0：v2 系列设计随主仓库 skill 迭代（CHANGELOG 逐版本记录，本文档自 v3.0 起独立承载设计演进）。
- v3.0（2026-09-02）：**大版本方向：防御式编程 AI agent skill（本文档首版）**——v2 功能趋于做尽，确立 v3.0 升级方向。核心决策：① 定位从"审查命令"升级为"以 iterate 为主体、深度贯彻防御式编程理念的编程 agent skill"；② 尊重"只显式调用"物理约束，防御式协议以本次调用内的完整任务为载体（§5 四步协议）；③ CLI 新增 `guard pre-check / post-check` 与 `invariant` 确定性校验（§6），与既有 `validation.commands` / `command_whitelist` 共用安全基线；④ 与 harness 2.0（自执行形态）共享同一套防御式编程词汇表，互为指令/执行形态（§8）。**本版为纯设计细化，不修改 skill 源文件**。头部状态行更新至 v3.0。
