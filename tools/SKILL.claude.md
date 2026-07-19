# iterate-skill for Claude Code

Claude Code 实现 iterate skill 的核心要点：用 `/workflow` 或 `/agent` 启动并行 reviewer，用 Plan/Approve 模式做用户审批，用 `Bash` 工具跑验证命令。

---

## 目录放置 / Placement

```text
~/.claude/skills/iterate/SKILL.md
# 或项目内
<project>/.claude/skills/iterate/SKILL.md
```

将本仓库的 `SKILL.md` 复制到上述位置即可。

---

## 触发方式 / Invocation

在 Claude Code 中输入：

```text
/iterate "<goal>" [--rounds N] [--no-limit]
```

或直接在对话中说出目标。

---

## 工具映射 / Tool Mapping

| iterate 概念 | Claude Code 工具 | 说明 |
|--------------|------------------|------|
| 并行 reviewer | `Workflow` / `Agent` × N | 每个 reviewer 一个 agent，并行执行 |
| 按目录拆分 reviewer | `Agent` per directory | 大项目时按目录分组 |
| 用户审批 | `EnterPlanMode` / `ExitPlanMode` | 架构修复进入 Plan 模式，用户 approve 后执行 |
| 文件编辑 | `Read` / `Edit` / `Write` | 原子修复由主模型直接操作 |
| 架构修复子代理 | `Agent` (serial) | 串行委派，每个完成后再启动下一个 |
| 验证命令 | `Bash` | 执行 `validation.commands` 中的命令 |
| 配置校验 | `Bash` | `python scripts/validate.py config iterate.config.yaml` |

---

## Workflow JSON 示例 / Workflow JSON Example

```json
{
  "name": "iterate-security-review",
  "description": "Run security dimension reviewer",
  "steps": [
    {
      "tool": "Read",
      "path": "iterate.config.yaml"
    },
    {
      "tool": "Read",
      "path": "CLAUDE.md",
      "if_exists": true
    },
    {
      "tool": "Agent",
      "prompt": "Review the codebase for security issues ONLY. Scope: {review.scope}. Focus: injection, path traversal, hardcoded secrets, input validation. Project context: {projectContext}. Do NOT read .env, *.key, secrets/, *.pem, *.p12, credentials.json. Return strictly as JSON with 'findings' array."
    }
  ]
}
```

---

## 子代理失败处理 / Sub-agent Failure

子代理返回失败时：

1. 记录到 `.iterate_decisions.md`。
2. 提示用户并等待明确指令（continue / skip / abort）。

---

## 验证命令安全 / Validation Safety

执行 `Bash` 前：

1. 读取 `validation.command_whitelist`。
2. 命令不在白名单时，先请求用户确认。
