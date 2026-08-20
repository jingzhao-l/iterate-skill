# iterate-skill-installer

<p align="center">
  <a href="README.md"><strong>English</strong></a> ·
  <a href="README.zh-CN.md"><strong>简体中文</strong></a>
</p>

针对各种 AI 编程助手的 [iterate-skill](https://github.com/jingzhao-l/iterate-skill) 一键安装器。

[![GitHub stars](https://img.shields.io/github/stars/jingzhao-l/iterate-skill?style=social&label=Star)](https://github.com/jingzhao-l/iterate-skill)

> ⭐ 如果这个项目对你有帮助，欢迎点亮 GitHub Star，这是对开源维护最大的支持！

## 用法

```bash
# 交互式安装 —— 检测你的 AI 助手并让你选择
npx iterate-skill-installer

# 只安装到某个特定助手
npx iterate-skill-installer --ai trae
npx iterate-skill-installer --ai claude

# 安装到项目目录而非全局
npx iterate-skill-installer --target ./my-project

# 强制覆盖已有技能文件
npx iterate-skill-installer --force

# 仅安装技能 —— 跳过安装 iterate CLI
npx iterate-skill-installer --no-cli
```

## 它做了什么

1. 检查你系统上的 Python 3。
2. 从 GitHub 获取最新的 iterate-skill 发布版本。
3. 下载发布 tarball 与 `SHA256SUMS.txt`。
4. 校验 tarball 的校验和。
5. 解压发布内容到临时目录。
6. 运行自带的 Python 安装脚本（`scripts/install.py`），它会：
   - 检测你机器上已安装的 AI 编程助手。
   - 提示你选择目标（默认：所有检测到的助手）。
   - 把技能文件复制到正确的技能目录。
7. 把 `iterate` CLI 安装到你的 PATH（优先 `pipx`，否则 `pip install --user`），
   以便你直接运行 `iterate onboard`。

> **注意：** 安装器通常会在你 PATH 上装好 `iterate` CLI，这样一条命令就能同时
> 得到技能和 CLI。如果**不**想自动安装 CLI，请加 `--no-cli` 只装技能——之后可从
> 检出目录用 `pipx install .` 或 `pip install .` 补装。如果 CLI 安装失败，你之后
> 也可用同样的方式补装。

## 支持的 AI 助手

Trae、Claude / Claude Code、Cursor、Windsurf、GitHub Copilot、Codex、Gemini CLI、OpenCode、Aider、AiderDesk、Zed、Warp、Continue、Cline、Roo Code、Qoder、Augment、OpenClaw、Autohand Code CLI、IBM Bob、CodeArts Agent、Antigravity、Amp、Deep Agents、Kimi Code CLI、Astral。

## 环境要求

- Node.js 18+
- Python 3.10+
- PATH 上存在 `tar` 命令（macOS、Linux、Windows 10+ 默认可用）

## License / 许可证

MIT