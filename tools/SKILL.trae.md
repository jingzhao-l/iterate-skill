# iterate-skill for Trae

Trae 实现 iterate skill 的核心要点：用 `Task` 启动并行 reviewer，用 `AskUserQuestion` 做用户审批，用 `RunCommand` 跑验证命令。

---

## 目录放置 / Placement

```text
~/.trae/skills/iterate/SKILL.md
# 或项目内
<project>/.trae/skills/iterate/SKILL.md
```

将本仓库的 `SKILL.md` 复制到上述位置即可。

---

## 触发方式 / Invocation

在 Trae 对话中输入（参数通过 Agent Skills 占位符 `$0` / `$1` / `$2` 注入）：

```text
/iterate "<goal>" [rounds] [no-limit]

# 示例
/iterate "提升代码质量" 10
/iterate "提升代码质量" no-limit
```

---

## 工具映射 / Tool Mapping

| iterate 概念 | Trae 工具 | 说明 |
|--------------|-----------|------|
| 并行 reviewer | `Task` × N | `subagent_type: "search"` 用于代码审查；`subagent_type: "general_purpose_task"` 用于汇总 |
| 按目录拆分 reviewer | `Task` per directory | 大项目时，每个子任务审查一个目录 |
| 用户审批 | `AskUserQuestion` | 呈现架构修复列表，等待用户选择 |
| 文件编辑 | `Read` / `Edit` / `Write` | 原子修复由主模型直接操作 |
| 架构修复子代理 | `Task` (serial) | 每个 task 串行执行，完成后才启动下一个 |
| 验证命令 | `RunCommand` | 执行 `validation.commands` 中的命令 |
| 配置校验 | `RunCommand` | `python scripts/validate.py config iterate.config.yaml` |

---

## Reviewer Task 示例 / Reviewer Task Example

```text
subagent_type: "search"
description: "security reviewer"
query: |
  Review the codebase for security issues ONLY.

  Scope: {review.scope}
  Focus: injection, path traversal, hardcoded secrets, input validation.
  Project context: {projectContext}

  Do NOT read .env, .env.*, *.key, secrets/, *.pem, *.p12, *.crt, *.cer, credentials.json, .aws/, .ssh/.

  For each finding report: file, line, severity, dimension, summary,
  failure_scenario, suggested_fix, is_atomic.

  EVIDENCE RULE: only report findings anchored in code you actually read.
  Fabricated paths or invented line numbers are EVIDENCE_VIOLATIONs.

  Return strictly as JSON: { "findings": [...] }
```

---

## Meta-review 硬证据门禁 / Meta-review Evidence Gate

`reviewer.evidence_validation`（默认开启）要求审查报告本身再被审查：逐条校验每个 finding 的 `file`/`line` 是否真实存在于磁盘代码中。任何伪造路径或越界行号都会以 `EVIDENCE_VIOLATION` 判 `needs_revision`。

`reviewer.coverage_validation`（默认开启）将 reviewer 自报的 `readFiles` 与分配清单比对，明显缺口浮出 medium 的 `COVERAGE_GAP` 提示（不反转判定）。

---

## Onboarding / Personalization

首次调用 `/iterate` 前需先完成 onboarding：生成 `ITERATE.md` 知识库与项目级 `iterate.config.yaml`（含 `onboarding.fingerprints` 漂移指纹）。可在 Trae 终端运行 `iterate onboard` 交互式完成，或由 AI 通道自动扫描。项目专属约束（禁区、风险区、已知意图等）通过 `iterate personalize` 追加。详见主 `SKILL.md`。

---

## 子代理失败处理 / Sub-agent Failure

子代理返回失败时，主模型必须：

1. 记录失败原因到 `.iterate_decisions.md`。
2. 使用 `AskUserQuestion` 询问用户：
   - 继续（continue）
   - 跳过该 task（skip）
   - 中止本轮（abort round）

---

## 验证命令执行前检查 / Pre-validation Check

运行 `RunCommand` 前：

1. 读取 `validation.command_whitelist`。
2. 命令不在白名单时，**直接拒绝，不可通过用户确认绕过**（与个性化硬白名单一致）。
3. 执行命令并捕获输出。
