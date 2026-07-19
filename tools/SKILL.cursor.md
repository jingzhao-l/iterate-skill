# iterate-skill for Cursor / Generic

Cursor 目前不原生支持 skill 注册，但可以通过 Agent 模式或自定义脚本实现 iterate 流程。本文件提供最小可运行实现思路。

---

## 方式一：Cursor Agent 模式 / Option 1: Cursor Agent Mode

1. 将本仓库的 `SKILL.md` 内容粘贴到 Cursor 的 Agent context 或自定义 system prompt 中。
2. 在项目根目录创建 `iterate.config.yaml`。
3. 在 Composer / Chat 中输入：

```text
/iterate "<goal>" [--rounds N]
```

Cursor Agent 会按 SKILL.md 的流程执行：
- 读取配置
- 创建隔离分支
- 并行审查（通过多次 Agent 调用）
- 修复问题
- 运行验证命令
- merge/push

---

## 方式二：本地脚本驱动 / Option 2: Local Script Driver

如果你希望更可控，可写一个本地脚本协调 Cursor 的 Agent：

```bash
#!/usr/bin/env bash
# iterate.sh — 最小协调脚本示例

GOAL="$1"
ROUND="${2:-7}"

git checkout -b "iterate/$(echo $GOAL | tr ' ' '-' | tr '[:upper:]' '[:lower:]')-$(date +%s)"

for i in $(seq 1 $ROUND); do
  echo "=== Round $i ==="
  # 调用 Cursor CLI 或 Agent API 执行本轮 reviewer
  # cursor agent --prompt "..."
  # 人工 review 后决定是否继续
done
```

---

## 工具映射 / Tool Mapping

| iterate 概念 | Cursor / Generic | 说明 |
|--------------|------------------|------|
| 并行 reviewer | Agent 多次调用 / 脚本并行 | 每个维度或每个目录一个 Agent 调用 |
| 用户审批 | 对话确认 / 脚本暂停等待输入 | 架构修复必须经用户确认 |
| 文件编辑 | Agent 自动编辑 / 手动编辑 | 原子修复可由 Agent 直接改 |
| 架构修复子代理 | Agent 串行调用 | 一次只执行一个架构 task |
| 验证命令 | Terminal / Bash | 手动或脚本运行 |
| 配置校验 | 脚本调用 | `python scripts/validate.py config iterate.config.yaml` |

---

## Reviewer Prompt 模板 / Reviewer Prompt Template

```text
You are a {dimension} reviewer for the iterate skill.

Scope: {review.scope} (full = entire codebase, changed-only = files changed this round).
Focus: {focus from config/dimensions.yaml}.
Project context: {projectContext}.

DO NOT read .env, *.key, secrets/, *.pem, *.p12, credentials.json.

For each finding, report:
- file, line, severity, dimension, summary, failure_scenario, suggested_fix, is_atomic

Return strictly as JSON: { "findings": [...] }
If no findings, return { "findings": [] }.
```

---

## 安全提醒 / Safety Reminder

- 执行任何 `validation.commands` 前，先检查命令是否在 `validation.command_whitelist` 中。
- 绝不 force-push。
- 绝不直接在 main/master 上提交。
