# iterate-plugin 设计文档 v3.1

> 目标：把 iterate-plugin 从「收敛看板 / 分诊 / 审查闭环的被动观察面板」升级为「质量指挥中心 + 经验银行」。
> 状态：v3.0 设计已落地（plugin 3.3.0）；**v3.1 记录 F8/F9/F10 数据化与 task_mode 通道打通**；设计文档迭代至 v3.1。
> 版本记录：见文末。

> **v3.0 设计主线（新增，保留 v2 全部内容不变）**：见 §5-§11。核心变化——① 定位从"被动观察面板"升级为"主动指挥中心 + 知识库"；② 新增质量门禁视图（各维度收敛度 / 验证通过率 / PASS-FAIL）；③ 新增经验银行（浏览 / 搜索 / 命中高亮 / 一键采纳）；④ 新增防御事件流（前置失败 / 回滚 / 不变量违反 / 假设被证伪）；⑤ 指挥操作原生按钮化（审批 / 指派 / 回滚 / 触发新一轮，底层仍走主工作流）；⑥ 与 harness 2.0 task_mode 打通，dsh UI 同步显示 code/iterate 指示灯。

---

## 1. 背景与现状回顾（v2 承载）

> 本节记录 v2 系列已实现能力（保留，作为 v3.0 迭代的基线），后续版本迭代不得删减本节内容。

### 1.1 项目定位
- **iterate-plugin** 是 iterate 生态的「dsh 桌面客户端插件」组件：把 iterate 生态同一套 review/fix loop 直接搬进 DeepSeek Harness (dsh) 桌面客户端界面。
- 提供**自治闭环代码迭代**（normal 模式）与 **dry-run 纯多轮审查**（只读）两种能力。
- 生态关系：skill（跨助手对话式）/ harness（无头引擎）/ plugin（dsh 桌面插件），三者共用同一套 `iterate.config.yaml` 与 9 维度审查体系。
- 开发与评审在主仓库 `jingzhao-l/iterate-skill` 完成，通过 `git subtree` 同步到独立发布仓库 `jingzhao-l/iterate-plugin`，版本发版与 npm 发布在插件仓库进行。

### 1.2 v2 已实现能力清单（当前发布 2.12.3）

#### 工具层（13 个纯函数工具）
- `iterate_config` / `iterate_validate` / `iterate_decision_log` / `iterate_context` / `iterate_review` / `iterate_triage` / `iterate_fix` / `iterate_diff` / `iterate_rollback` / `iterate_checkpoint` / `iterate_status` / `iterate_history` / `iterate_prune`
- **findings 分诊闭环**：审查 → UI 分诊（y/n/a）→ `iterate_triage` 写回 `known_intentional` → 下一轮自动过滤。
- **结构化修复系统**：每次修复先备份、写注册表、记录 diff，验证失败可 `iterate_rollback` 还原。
- **断点续跑**：长迭代在每轮开头保存 checkpoint，中断后可恢复进度。
- **历史审计**：`iterate_history` 读取决策日志与修复注册表汇总。
- **运行时清理**：`iterate_prune` 清理过期决策日志、陈旧断点、孤儿修复备份与空轮次。
- **配置读写**：`iterate_config` 支持带校验、备份、回滚的局部写入。

#### UI 层（客户端免构建槽位，防御式设计）
| UI 组件 | 挂载槽位 | 功能 |
|---|---|---|
| 收敛看板 `ConvergenceDashboard` | `conversation.input.dock` | 输入框上方实时轮次进度、严重度统计、维度徽章、趋势迷你图、修复计数徽章、运行阶段芯片 |
| 运行时观测台 `ObservatoryPanel` | `conversation.input.dock` | 输入框下方七个标签页：实时活动流 / 审查线程 / 收敛趋势 / 发现定位 / 修复与回滚 / 断点恢复 / 决策时间线；支持筛选与 JSON 导出 |
| Findings 分诊面板 `TriagePanel` | `conversation.chat.turnTail` | 逐条 y/n/a 判定，支持筛选、批量、键盘快捷键、localStorage 持久化、复制 YAML/应用指令 |
| 收敛统计卡片 `StatsCard` | `conversation.chat.turnTail` | 无 findings 时显示收敛统计、历史轮次表、趋势图、完成摘要 |
| iterate 主题皮肤 | `theme.overrideTokens` | 暖琥珀配色 13 个 dsw token 覆盖，明暗双模式 |
| 进度胶囊 `ProgressCapsule` | `shell.overlay` | 每轮完成/收敛时右下角弹出通知 |
| iterate 设置区 `SettingsPanel` | `settings.section` | 主题开关、分诊持久化说明、配置管理指引、运行时状态概览、一键清空分诊数据 |

- UI 层为**防御式设计**：`slots` / `theme` / `React` 任一不可用时自动降级，不会崩溃客户端。

### 1.3 v2 的边界与 v3.0 升级动机
- **现状**：v2 是"监控 + 轻度操作"——能看收敛进度、能分诊，但 rollback/resume 等操作需复制 `iterate_*` 命令文本（为遵守 dsh 主工作流约束）。
- **升级动机**：方向确认——**经验银行（方向 1）最适配 harness 和 plugin**。plugin 作为 dsh 界面层，v3.0 把"看"升级为"指挥 + 知识"：既能看（门禁/事件流），又能做（原生指挥操作），还能学（经验银行浏览/采纳），让积累的质量知识成为 dsh 用户的一等公民。

---

## 2. 设计原则（v3.0 延续 v2，新增指挥与知识原则）
- **防御式 UI 不变**：`slots` / `theme` / `React` 任一不可用仍自动降级，不崩溃客户端。
- **主工作流不被绕过**：所有指挥操作底层仍走 iterate 主工作流（通过插件工具触发，不绕过审查/审批/日志），只是把"复制命令文本"封装为原生按钮。
- **只读默认 + 显式确认**：写操作沿用"只读默认 + 显式确认 + 写入前备份 + 失败回滚"（与 harness WebUI §17.3 一致）。
- **经验即资产**：经验银行是方向 1 在 UI 的落地——让用户"看得到"项目积累的质量知识，并一键复用。
- **跨形态一致**：与 harness 2.0 / skill 3.0 共享同一套防御式术语与数据（task_mode / 防御事件 / 经验库）。

---

## 3. 防御式编程概念界定（与 harness 2.0 / skill 3.0 对齐）

> 生态统一词汇表（与 harness 2.0 §20.1.3、skill 3.0 §3 一致）：
> ① 最小化假设；② 信任边界验证；③ 快速失败、响亮失败（fail fast, fail loud）；④ 前置/后置条件 + 断言。
> plugin 作为界面层，其职责是**可视化这些防御事件**（发生了什么、防御住了什么），而非实现防御机制本身。

---

## 4. v3.0 总览：质量指挥中心 + 经验银行

- **定位变化**：从"被动观察面板" → **"主动指挥中心 + 知识库"**。
- **心智模型**：`被动观察` → `指挥 + 知识`：既能看（门禁/事件流），又能做（原生指挥），还能学（经验银行）。
- **实现形态**：保留免构建 Web UI 层 + 13 纯函数工具，新增/扩展面板与操作（§5-§11）。

---

## 5. 新增：质量门禁视图（Quality Gate View）

- **功能**：显示项目门禁状态——各维度收敛度、验证通过率、整体 `PASS/FAIL` 与理由。
- **数据来源**：来自 skill 3.0 写入的**机器可读质量证书**（JSON）与 harness 决策日志聚合；`iterate_status` / `iterate_history` 扩展输出门禁快照。
- **UI 位置**：新增 `QualityGatePanel`，挂 `conversation.input.dock`（与收敛看板并列，或以新标签页并入 ObservatoryPanel）。
- **视觉**：对齐既有 severity 固定色表（严重度→红/琥珀/绿），门禁 PASS/FAIL 用绿/红徽章。

---

## 6. 新增：经验银行（Experience Bank）

- **功能**：浏览 / 搜索项目历史修复经验，命中高亮（"这次命中了第 N 条历史经验"），一键采纳。
- **数据来源**：harness 2.0 经验库（跨会话沉淀的修复经验）+ 决策日志 + 修复注册表；skill 3.0 作为经验生产者写入。
- **UI 位置**：新增 `ExperienceBankPanel`（可并入 ObservatoryPanel 新标签页）。
- **采纳机制**：采纳时把经验对应的修复模式/已验证修法注入当前上下文，底层仍走 iterate 主工作流（不绕过审查）。

---

## 7. 新增：防御事件流（Defense Event Stream）

- **功能**：在观测台新增"防御事件"标签页——前置校验失败、回滚、不变量违反、假设被证伪；每次触发都显示"防御住了什么"。
- **数据来源**：harness 2.0 防御式内核事件（工具前置/后置校验结果、事务回滚、不变量违反、假设声明）经事件流推送；skill 3.0 `guard` / `invariant` 结果同步展示。
- **UI 位置**：ObservatoryPanel 新增标签页（对齐既有活动流交互：筛选、JSON 导出）。

---

## 8. 指挥操作：原生按钮化

- **功能**：审批架构修复、指派 findings、回滚到检查点、触发新一轮——原生按钮一键执行。
- **约束**：底层仍走 iterate 主工作流（通过既有 13 工具触发，记录决策日志、走审批），不绕过审查/审批/日志；写操作沿用"只读默认 + 显式确认 + 写入前备份 + 失败回滚"。
- **UI 位置**：TriagePanel（审批/指派）、ConvergenceDashboard（回滚/触发新一轮）、StatsCard（完成摘要附操作）。
- **与 v2 差异**：v2 需复制 `iterate_*` 命令文本；v3.0 封装为按钮，保留审计纪律（每次操作写入决策日志）。

---

## 9. 跨会话趋势（从质量账本读取）

- **功能**：从质量账本读取长期趋势——顽固问题、回归检测、收敛速度变化、经验命中率。
- **数据来源**：harness 趋势库（`trend_store`）+ skill 3.0 质量账本；现有 StatsCard 趋势图升级为跨会话维度。

---

## 10. task_mode 指示灯（与 harness 2.0 打通）

- **功能**：dsh UI 同步显示当前 task_mode（code / iterate），与 harness TUI 的竖向色条一致（code=primary / iterate=amber）。
- **数据来源**：harness 2.0 status 推送 `task_mode`；plugin 读取并渲染指示灯。
- **UI 位置**：ConvergenceDashboard 或输入框区域。

---

## 11. 后端支撑与数据流

| 数据 | 来源 | 消费 |
|---|---|---|
| 质量证书（门禁快照） | skill 3.0 写入 JSON + harness 决策日志聚合 | QualityGatePanel |
| 经验库 | harness 2.0 经验库 + skill 3.0 生产者 + 决策日志/修复注册表 | ExperienceBankPanel |
| 防御事件 | harness 2.0 防御式内核事件 + skill 3.0 guard/invariant 结果 | 防御事件流标签页 |
| task_mode | harness 2.0 status 推送 | 模式指示灯 |
| 指挥操作结果 | 既有 13 工具（走主工作流） | 决策日志 + UI 刷新 |

- **实现形态**：保留免构建 Web UI（`slots` / `theme` / `React` 防御式降级），工具层扩展既有 `iterate_status` / `iterate_history` 输出，新增少量只读查询工具（经验库/门禁/防御事件），不引入新的常驻服务。

---

## 12. 里程碑与验收

| 里程碑 | 内容 | 验收 |
|---|---|---|
| M1 | QualityGatePanel + 门禁快照输出 | 门禁状态正确渲染；`iterate_status`/`history` 扩展输出单测覆盖（空/进行中/PASS/FAIL） |
| M2 | ExperienceBankPanel + 经验库查询 | 浏览/搜索/命中高亮正确；采纳后注入上下文且走主工作流；无经验时优雅空态 |
| M3 | 防御事件流标签页 | 四类防御事件（前置失败/回滚/不变量违反/假设证伪）正确展示；筛选与 JSON 导出对齐既有交互 |
| M4 | 指挥操作按钮化 | 审批/指派/回滚/触发新一轮原生触发，底层走主工作流并写决策日志；写操作走 confirm + 备份 + 回滚 |
| M5 | task_mode 指示灯 | 与 harness 2.0 status 打通，code/iterate 色条正确 |

**质量门**：
- 工具层：新增/扩展工具单测覆盖正常路径、异常路径与边界场景（沿用既有测试规范）；
- 前端：`npm run typecheck` 零错误、`npm run build` 产出正常；
- 防御式：`slots` / `theme` / `React` 任一不可用时正确降级不崩溃；
- 安全：指挥操作全部走既有权限/审计机制，不新增敏感信息暴露面。

---

## 13. 风险与开放问题
1. **dsh 槽位约束**：新面板挂载槽位可能受 dsh 版本限制——沿用既有 `slots` 防御式降级；若某槽位不可用则退化为 ObservatoryPanel 标签页。
2. **经验库数据规模**：跨会话经验可能膨胀——采纳/浏览分页 + 检索索引；清理沿用 `iterate_prune` 语义（dry-run 只报告）。
3. **指挥操作与主工作流并发**：按钮触发与运行中任务并发——沿用既有断点/暂停机制（harness Esc 暂停），切换只影响下一轮。
4. **跨形态数据一致性**：经验库/门禁/防御事件来自 harness + skill 两处——以统一事件流/JSON 契约对齐，避免双写漂移。

---

## 14. 版本记录
- v1.0-v2.12.3：v2 系列设计随主仓库插件迭代（README/CHANGELOG 逐版本记录，本文档自 v3.0 起独立承载设计演进）。
- v3.0（2026-09-02）：**大版本方向：质量指挥中心 + 经验银行（本文档首版）**——v2 功能趋于做尽，确立 v3.0 升级方向。核心决策：① 定位从"被动观察面板"升级为"主动指挥中心 + 知识库"（§4）；② 新增质量门禁视图（§5）与经验银行（§6，方向 1 在 UI 的落地）；③ 新增防御事件流（§7）与 task_mode 指示灯（§10），与 harness 2.0 防御式内核 / skill 3.0 guard-invariant 打通；④ 指挥操作原生按钮化（§8），底层仍走 iterate 主工作流，不绕过审查/审批/日志；⑤ 跨会话趋势从质量账本读取（§9）。**本版为纯设计细化，不修改 plugin 源文件**。头部状态行更新至 v3.0。
- v3.1（2026-09-06）：**v3.0 设计落地（plugin 3.3.0）**——F8/F9/F10 从复制指令占位升级为**会话流数据实渲染**：新增 `lib/parse.js` 的 `scanSessionForQualityGate` / `scanSessionForExperienceBank` / `scanSessionForDefenseEvents`（反向时序、代理安全、深度/环保护），`get/add` 单条折叠为列表、`record/counts` 折入计数+事件流；§8 新增「指派修复」按钮（按批量作用域复制 `iterate_fix` 指令，携带 file/line/dimension/severity/summary）。task_mode 通道修正：harness status 推送只达 harness 自有前端、不通 dsh 插件，故改由插件服务器端透传——`iterate_transcript capture` 接受显式 `taskMode`，builder 持久化（review-loop 缺省 derive `iterate`），`rehydrateBuilder` 透传，`iterate_status` 经 `readTranscriptTaskMode` 读取持久化 transcript 输出并渲染；客户端 chip 由 `normalizeTranscript` 的 taskMode 透传点亮。
- v3.2（2026-09-06，plugin 3.4.0）：**综合审查与硬化批次**——① `iterate_checkpoint` 新增 `resume` 操作（加载断点 + 累加 resumeCount 原子写回），修复观测台 F5 复制出工具不支持的 `operation:"resume"` 的死指令；② `iterate_status` 补全类型中早已声明却从未填充的 `qualityGate`/`experienceBank`/`defenseEvents` 三个快照输出（质量指挥中心一屏到位）；③ 安全硬化：`applyConfigUpdates` 增加原型污染防护（对齐 `mergeConfig`），`iterate_config` 写操作对 `observatory.approval` fail-closed（模型不可经配置写自翻审批策略绕过人审门禁）；④ 防御/质量存储读取规范化（`readDefenseEvents` 重算 counts 杜绝 NaN、`readQualityGate` 归一 dimensions/数字字段防 render 崩溃）；⑤ `buildReviewReport` 轮次排序修复无序 rounds 的收敛误判；`collectScopeFiles` 改用 `path.relative` 修复 Windows 绝对路径泄漏；⑥ UX：空态 dashboard 新增「完整迭代 / 仅评审」一键复制启动按钮。
