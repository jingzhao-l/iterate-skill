# 示例：Swift 项目配置 / Example: Swift Project

适用于 Swift/SwiftUI macOS/iOS 项目。

```yaml
# iterate.config.yaml
goal: "消除 Swift build 警告并修复潜在的 force-unwrap 崩溃"
max_rounds: 5
language: zh

dimensions:
  - correctness
  - security
  - performance
  - architecture
  - style-tests
  - tech-debt
  - ui-ux

atomic:
  max_lines: 20
  max_adjacent_methods: 3

git:
  target_branch: main
  use_worktree: false

validation:
  command_whitelist:
    - "swift"
  commands:
    swift:
      - "swift build -c debug"
      - "swift test -c debug"
```

触发方式：

```text
/iterate "消除 Swift build 警告并修复潜在的 force-unwrap 崩溃"
```

## 预期行为

1. correctness 维度重点检查 `try!`、`force-unwrap`、`!` 等崩溃风险。
2. ui-ux 维度检查 loading/empty/error 状态和响应式断点。
3. 原子问题直接修复；架构问题（如大 View 拆分）经你批准后执行。
4. 每轮跑 `swift build` 和 `swift test` 验证。
5. 验证通过后合并推送。
