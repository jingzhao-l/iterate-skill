# Contributing to iterate-skill

感谢你对 iterate-skill 感兴趣！欢迎提交 Issue、PR 和改进建议。

---

## 开发环境

本项目校验脚本使用 Python 3.10+：

```bash
cd scripts
pip install -r requirements.txt
```

---

## 提交 Issue

- 描述你使用的工具（Trae / Claude Code / Cursor / Generic）。
- 提供最小可复现的 `iterate.config.yaml`（可替换敏感信息）。
- 说明期望行为与实际行为。

---

## 提交 Pull Request

1. Fork 本仓库。
2. 创建功能分支：`git checkout -b feat/your-feature` 或 `fix/your-bug`。
3. 提交改动，遵循 [Conventional Commits](https://www.conventionalcommits.org/)：
   - `feat:` 新功能
   - `fix:` 修复
   - `docs:` 文档
   - `test:` 测试
   - `refactor:` 重构
   - `chore:` 杂项
4. 确保本地校验通过：

   ```bash
   python scripts/validate.py config config/iterate.config.yaml
   python scripts/validate.py decisions templates/iterate-decisions.template.md
   pytest tests/ -q
   ```

5. 推送分支并创建 Pull Request。

---

## 文档规范

- `SKILL.md` 保持中英双语结构。
- 新增配置项必须同步更新：
  - `config/iterate.config.yaml`
  - `config/config.schema.json`
  - `README.md` 配置表格
  - `SKILL.md` 配置表格与流程说明
  - 相关 `examples/*.md`
- 新增验证命令安全规则时，同步更新 `validation.command_whitelist` 默认值与 `scripts/validate.py`。

---

## 代码规范

- Python 函数长度尽量不超过 80 行。
- 优先使用 early return 减少嵌套。
- 禁止空 catch 块。
- 新增第三方依赖必须为 MIT / Apache-2.0 / BSD 等宽松许可证，并在 `scripts/requirements.txt` 中声明精确版本。
- 所有新增脚本/测试必须附带测试用例。

---

## 许可证

通过提交 PR，你同意你的贡献采用本项目的 [MIT 许可证](./LICENSE)。
