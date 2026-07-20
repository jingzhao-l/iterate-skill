# 示例：Python 项目配置 / Example: Python Project

适用于纯 Python 项目或 Python 为主的项目。

```yaml
# iterate.config.yaml
goal: "修复所有 ruff/mypy 报错并补齐关键路径的单元测试"
max_rounds: 5
language: zh

dimensions:
  - correctness
  - security
  - performance
  - architecture
  - style-tests
  - tech-debt
  - spec-compliance

atomic:
  max_lines: 20
  max_adjacent_methods: 3

git:
  target_branch: main
  use_worktree: false

validation:
  command_whitelist:
    - "ruff"
    - "mypy"
    - "pytest"
  commands:
    python:
      - "ruff check src/ tests/"
      - "mypy src/ --ignore-missing-imports"
      - "pytest tests/ -x -q --timeout=60"
```

触发方式：

```text
/iterate "修复所有 ruff/mypy 报错并补齐关键路径的单元测试"
```

## 预期行为

1. 第 1 轮可能发现大量 style-tests 和 correctness 问题。
2. 原子问题（如单个函数过长、缺失类型注解）直接修复。
3. 架构问题（如大文件拆分、跨模块重构）经你批准后执行。
4. 每轮跑 `ruff check`、`mypy`、`pytest` 验证。
5. 验证通过后自动 `git merge` 回 `main` 并 `git push`。
