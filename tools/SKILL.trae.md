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

在 Trae 对话中输入：

```text
/iterate "<goal>" [--rounds N] [--no-limit]
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

  Return strictly as JSON: { "findings": [...] }
```

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
2. 若命令不在白名单中，先用 `AskUserQuestion` 确认。
3. 执行命令并捕获输出。
