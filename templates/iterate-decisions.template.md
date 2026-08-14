<!--
  决策日志结构参考模板（仅供参考 / For Reference Only）。

  `.iterate_decisions.md` 由 AI 在 `/iterate` 会话中按 SKILL.md
  「决策日志格式 / Decision Log Format」章节创建并追加，本模板不经过
  CLI 生成器渲染。`{...}` 为 AI 填充的占位约定（与 SKILL.md 中的格式
  定义一致），不是 Python format 占位符。
-->

# Iterate Decision Log

Goal: {goal}
Max rounds: {maxRounds}
Started: {timestamp}
Branch: {iteration-branch}

---

## Round {N} — {timestamp}

### Atomic Fixes (Direct)

| # | File | Summary | Severity | Status |
|---|------|---------|----------|--------|
| 1 | | | | |

### Architectural Fixes (Approved + Executed)

| # | File(s) | Summary | Severity | Status |
|---|---------|---------|----------|--------|
| 1 | | | | |

### Architectural Fixes (Deferred to Next Round)

| # | File(s) | Summary | Defer Reason |
|---|---------|---------|-------------|
| 1 | | | |

### Reverted Fixes

| # | File(s) | Summary | Revert Reason |
|---|---------|---------|---------------|
| 1 | | | |

### AI Important Decisions

| # | Decision | Reason |
|---|---------|--------|
| 1 | | |

### Validation

- 
