# iterate-skill-installer

One-command installer for [iterate-skill](https://github.com/jingzhao-l/iterate-skill) across AI coding assistants.

## Usage

```bash
# Interactive install — detects your AI assistants and lets you choose
npx iterate-skill-installer

# Install to a specific assistant only
npx iterate-skill-installer --ai trae
npx iterate-skill-installer --ai claude

# Install into a project directory instead of globally
npx iterate-skill-installer --target ./my-project

# Force overwrite existing skill files
npx iterate-skill-installer --force
```

## What it does

1. Checks for Python 3 on your system.
2. Fetches the latest iterate-skill release from GitHub.
3. Downloads the release tarball and `SHA256SUMS.txt`.
4. Verifies the tarball checksum.
5. Extracts the release into a temporary directory.
6. Runs the bundled Python install script (`scripts/install.py`) which:
   - Detects installed AI coding assistants on your machine.
   - Prompts you to select targets (default: all detected assistants).
   - Copies the skill files into the correct skills directories.
7. Installs the `iterate` CLI onto your PATH (prefers `pipx`, otherwise
   `pip install --user`) so you can run `iterate onboard` directly.

> **Note:** the installer always puts the `iterate` CLI on your PATH so a single
> command gives you both the skill and the CLI. If you **don't** want the CLI
> auto-installed, use a manual install instead — copy `SKILL.md` + `config/` +
> `scripts/` + `templates/` to your assistant dir, or run
> `python scripts/install.py install` directly. If the CLI install fails, you can
> still install it later with `pipx install .` or `pip install .` from a checkout.

## Supported AI assistants

Trae, Claude / Claude Code, Cursor, Windsurf, GitHub Copilot, Codex, Gemini CLI, OpenCode, Aider, AiderDesk, Zed, Warp, Continue, Cline, Roo Code, Qoder, Augment, OpenClaw, Autohand Code CLI, IBM Bob, CodeArts Agent, Antigravity, Amp, Deep Agents, Kimi Code CLI, Astral.

## Requirements

- Node.js 18+
- Python 3.10+
- `tar` command available on PATH (available by default on macOS, Linux, Windows 10+)

## License

MIT
