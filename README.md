# Iterate Skill

> **English** · [简体中文](./README.zh-CN.md)

<center>
  <strong>A portable, configurable AI coding assistant skill: fully automated multi-round code review and fixing.</strong>
</center>

<br/>

<p align="center">
  <a href="https://github.com/jingzhao-l/iterate-skill/blob/main/badges/downloads.json">
    <img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fjingzhao-l%2Fiterate-skill%2Fmain%2Fbadges%2Fdownloads.json&query=total&label=Total%20Downloads&style=for-the-badge&color=2ea44f&logo=download&logoColor=white" alt="Total Downloads">
  </a>
</p>

<p align="center">
  <a href="https://clawhub.ai/jingzhao-l/skills/iterate-skill"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fjingzhao-l%2Fiterate-skill%2Fmain%2Fbadges%2Fdownloads.json&query=clawhub&label=ClawHub&color=4285F4&logo=cloudflare&logoColor=white" alt="ClawHub"></a>
  <a href="https://skillhub.cloud.tencent.com/"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fjingzhao-l%2Fiterate-skill%2Fmain%2Fbadges%2Fdownloads.json&query=skillhub&label=SkillHub&color=624aff&logo=alibabacloud&logoColor=white" alt="SkillHub"></a>
  <a href="https://www.npmjs.com/package/iterate-skill-installer"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fjingzhao-l%2Fiterate-skill%2Fmain%2Fbadges%2Fdownloads.json&query=npm&label=npm&color=CB3837&logo=npm&logoColor=white" alt="npm"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-yellow" alt="License"></a>
  <a href="https://github.com/jingzhao-l/iterate-skill/releases"><img src="https://img.shields.io/github/v/release/jingzhao-l/iterate-skill" alt="GitHub release"></a>
  <a href="https://github.com/jingzhao-l/iterate-skill"><img src="https://img.shields.io/github/stars/jingzhao-l/iterate-skill?style=social&label=Star" alt="GitHub stars"></a>
</p>

> Want to support this project? A GitHub **Star** is the best thank-you and helps more developers discover iterate.

---

## Table of Contents

- [About This Project](#about-this-project)
- [At a Glance](#at-a-glance)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Daily Usage](#daily-usage)
- [How It Works](#how-it-works)
- [Configuration](#configuration)
- [FAQ](#faq)
- [Security](#security)
- [Directory Structure](#directory-structure)
- [Contributing](#contributing)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## About This Project

**iterate** is an open-source project that gives AI coding assistants the ability to perform **multi-round, autonomous code review and fixing**. You don't need any background about an "iterate" concept — it solves a very concrete pain point:

> AI assistants often "talk a lot but do little": a single conversation touches only a few lines, looks at one file and never re-checks the whole, and rarely re-verifies what it broke. `/iterate` automates these small but critical finishing tasks — item-by-item review, per-dimension triage, fixing, verification, and iteration — so the AI truly finishes a change **completely and correctly**, like a senior engineer.

Its operating mechanism can be summarized as a self-closing pipeline:

```text
Set the goal → multi-dimension parallel review → atomic fixes + architecture fixes (with your approval) → verify → re-review → iterate until convergence / max rounds → output summary
```

**iterate is not a standalone tool; it is a skill ecosystem that attaches to your existing AI assistants.** It doesn't replace your IDE or AI tools; instead it adds a strict "code gatekeeping" layer to your existing workflow. The ecosystem is made up of three components that share the same configuration and review dimensions:

| Component | Form & Location | Use Case |
|---|---|---|
| **Core Skill + CLI** | Portable AI skill `/iterate` + `iterate` CLI (root of this repo) | Multi-round iteration inside conversational UIs of Trae / Claude Code / Cursor / Copilot / Codex and 25+ assistants |
| **[iterate-harness](https://github.com/jingzhao-l/iterate-harness)** | Standalone headless engine, command `ih` (source `harness/iterate-harness`, npm: `iterate-harness`) | Run the same closed loop outside a conversational assistant, in the terminal / CI / git hooks |
| **[iterate-plugin](https://github.com/jingzhao-l/iterate-plugin)** | dsh desktop client plugin (source `harness/iterate-plugin`, npm: `iterate-plugin`) | Use the dsh desktop client to bring iterate's convergence dashboard and review progress into the UI |

The relationship: the **skill** (this repo's core deliverable) targets conversational iteration in any AI assistant; the **harness** is the same closed-loop engine for headless / CI scenarios; the **plugin** brings harness's runtime experience into dsh. The configuration (`iterate.config.yaml`) and dimension system are fully consistent across all three — understand one and you can transfer the rest.

The harness and plugin can also be installed and used independently of this repo:

```bash
# iterate-harness: one-command install (npm wrapper, simplest)
npm install -g iterate-harness

# or script install (oh / ohmo have fully migrated to ih)
curl -fsSL https://raw.githubusercontent.com/jingzhao-l/iterate-harness/main/scripts/install.sh | bash
ih iterate init && ih iterate review

# iterate-plugin: GitHub install for the dsh desktop plugin
dsh plugin --profile web add github:jingzhao-l/iterate-plugin#main
```

> The harness bundles an OrcaRouter gateway provider (including a free model tier). Register via the [referral link](https://www.orcarouter.ai/ref/ref_5eca75a9c809c95ab152) to support the project; see the [iterate-harness README](https://github.com/jingzhao-l/iterate-harness) for setup guidance.

> The rest of this document focuses on the **skill (repo root)** and its most common conversational usage. Full docs for the harness and plugin live in their own repos: [iterate-harness](https://github.com/jingzhao-l/iterate-harness) (source `harness/iterate-harness/README.md`), [iterate-plugin](https://github.com/jingzhao-l/iterate-plugin) (source `harness/iterate-plugin/README.md`).

---

## At a Glance

**Iterate Skill** lets an AI assistant review and fix a codebase over multiple rounds, like a rigorous senior engineer.

| Capability | Description |
|---|---|
| **Dual modes** | `/iterate` — original multi-round review→fix→converge loop (v2 behavior, zero breakage); `/iterate defensive` — defensive-programming mode for normal incremental coding tasks, ending in the same iterate convergence gate |
| **9 dimensions in parallel** | correctness, security, performance, architecture, style-tests, tech-debt, spec-compliance, frontend-backend, ui-ux |
| **Scope dimension sets** | Named `dimension_sets` (e.g. `frontend`, `api`, `security`) preset at onboarding; a scoped goal routes to the matching set, off-catalog scopes trigger an on-the-fly redefinition recorded in `.iterate_decisions.md` (never copied from presets) |
| **Two-track fixing** | Atomic issues (≤20 lines, single file) are fixed automatically; architecture issues are fixed after your approval |
| **Deterministic gate CLI** | `iterate guard pre-check` / `post-check` + `iterate invariant` — exact, fail-loud checks the host AI runs before/after every edit and at delivery (defensive mode) |
| **Git isolation** | Each round runs on an isolated `iterate/*` branch or worktree; merge/push is off by default and must be explicitly enabled |
| **Secure-by-default** | `push_per_round` and `auto_merge` default to `false` |
| **Command whitelist** | Double validation at config time and personalization time; rejects dangerous shell metacharacters |
| **Checksum & verification** | Enforces SHA256 verification when updating from GitHub Release |
| **Multi-assistant support** | Trae, Claude Code, Cursor, Windsurf, GitHub Copilot, Codex, Roo Code and 25+ tools |
| **Project knowledge base** | Auto-generates `ITERATE.md` + `iterate.config.yaml`, with drift detection and incremental refresh |

---

## Quick Start

### 1. Install the skill

```bash
npx iterate-skill-installer
```

It auto-detects your installed AI coding tools and interactively lets you choose which assistants to install into. Use `--ai <name>` to target a single assistant directly. The installer also installs the `iterate` CLI (for step 2's `iterate onboard`, etc.) — one command installs skill + CLI.

### 2. Enter a project and complete onboarding

```bash
cd /path/to/your-project
iterate onboard
```

`iterate onboard` generates your project's knowledge base:

- `ITERATE.md`: tech stack, module map, conventions, forbidden areas, and more
- `iterate.config.yaml`: iteration goal, review dimensions, validation commands, and more

### 3. Start iterating

In your AI assistant's conversation, type:

```text
/iterate "improve code quality, ensure all functions are ≤80 lines and tests pass"
```

Or launch the CLI directly in the terminal:

```bash
iterate status      # view onboarding status and drift
iterate refresh     # incrementally refresh ITERATE.md
iterate personalize # add project-specific constraints
```

---

## Installation

### Recommended: one-command npx install (for most users)

No repo cloning, no manual Python environment setup — one command downloads, verifies, and installs the skill, and also installs the `iterate` CLI:

```bash
# Auto-detect installed AI assistants and choose interactively
npx iterate-skill-installer

# Install only into Trae
npx iterate-skill-installer --ai trae

# Install into a specific project directory
npx iterate-skill-installer --target /path/to/project

# Force-overwrite a previously installed skill
npx iterate-skill-installer --ai trae --global --force
```

Common options:

| Option | Description |
|---|---|
| `--ai <name>` | Install only into a specific assistant, e.g. `trae`, `claude`, `cursor` |
| `--target <path>` | Project-level install into a directory |
| `--global` | Install into the user home directory (default) |
| `--force` | Overwrite existing skill files |
| `--token <token>` | GitHub token to raise API rate limits |
| `-h, --help` | Show help |
| `-v, --version` | Show version |

> **The installer puts the `iterate` CLI on your PATH** (prefer `pipx` isolated install, else `pip install --user`) so that `npx iterate-skill-installer` completes "skill + CLI" in one command. That does place an executable on your system. If you don't want automatic CLI install, use the "manually copy SKILL.md" or "source scripts" approaches below instead.
>
> The installer requires Node.js 18+ and Python 3.10+. It creates an isolated Python virtualenv, installs dependencies, and calls `scripts/install.py` to copy files. When downloading a release it forces verification against `SHA256SUMS.txt` — install is rejected on mismatch. If the `iterate` command fails to install, you can still install it manually with `pipx install .` or `pip install .`.

### Other install methods

If you can't use npm, or you want full control over the install, use one of these.

#### Method A: install the iterate CLI locally

`npx` one-command install already installs the `iterate` CLI. If you didn't use npx, or want to install/upgrade the CLI manually:

```bash
git clone https://github.com/jingzhao-l/iterate-skill.git
cd iterate-skill

# Recommended: isolated install with pipx
pipx install .

# or plain pip
pip install .

# verify
iterate --version
```

After install you can use `iterate onboard`, `iterate personalize`, `iterate status`, `iterate refresh`, `iterate reonboard` in any project directory.

#### Method B: manually copy the skill directory

> ⚠️ **You must copy the entire `iterate/` directory, not just `SKILL.md`.** `SKILL.md` resolves `config/`, `scripts/validate.py`, and `templates/` at runtime relative to its install directory. Copying only one file causes `/iterate` to fail because it can't find the config and validation scripts.

If you don't want to use the npx installer, copy the whole skill directory to the assistant directory:

```bash
# Clone or download the source first to get an iterate/ dir with SKILL.md, config/, scripts/, templates/
git clone https://github.com/jingzhao-l/iterate-skill.git
SKILL_DIR=$(pwd)/iterate-skill

# Trae
mkdir -p ~/.trae/skills/iterate
cp -R "$SKILL_DIR"/SKILL.md "$SKILL_DIR"/config "$SKILL_DIR"/scripts "$SKILL_DIR"/templates ~/.trae/skills/iterate/

# Claude Code
mkdir -p ~/.claude/skills/iterate
cp -R "$SKILL_DIR"/SKILL.md "$SKILL_DIR"/config "$SKILL_DIR"/scripts "$SKILL_DIR"/templates ~/.claude/skills/iterate/

# Cursor
mkdir -p ~/.cursor/skills/iterate
cp -R "$SKILL_DIR"/SKILL.md "$SKILL_DIR"/config "$SKILL_DIR"/scripts "$SKILL_DIR"/templates ~/.cursor/skills/iterate/
```

For more tool paths, see the "tool mapping table" in [`SKILL.md`](./SKILL.md).

#### Method C: source scripts (for developers)

```bash
git clone https://github.com/jingzhao-l/iterate-skill.git
cd iterate-skill

python scripts/install.py install --ai trae --global
python scripts/install.py update --ai trae --target /path/to/project
python scripts/install.py uninstall --ai trae --target /path/to/project --yes
```

### Global vs. project-level install

| Scope | Example path | Effect |
|---|---|---|
| **Global install** | `~/.trae/skills/iterate/` | First `/iterate` invocation triggers onboarding in every project |
| **Project-level install** | `/project/.trae/skills/iterate/` | After onboarding it reuses the project root's `ITERATE.md` |

Suggestion: install globally once so the assistant "gets to know you"; then do a project-level install in important projects to avoid repeated onboarding.

### Why not skills.sh?

This project was previously distributed on skills.sh / SkillHub and other platforms. Since v2.1, **`npx iterate-skill-installer` is the recommended unified install method** because:

1. **One command**: auto-download, SHA256 verify, environment prep, assistant selection — no manual cloning or file copying.
2. **Consistent versions**: always installs from the GitHub Release, avoiding version drift from platform caches.
3. **Unified across assistants**: one install logic supports 25+ AI assistants instead of each platform maintaining its own.
4. **Secure & verifiable**: forces verification against `SHA256SUMS.txt`; install is rejected on mismatch.

Marketplace pages like skills.sh remain for display and discovery but are no longer the primary install entry.

---

## Daily Usage

### In an AI assistant

After installing the skill, type these into any AI tool that supports it:

```text
/iterate "your goal"
/iterate "your goal" 10
/iterate "your goal" no-limit
/iterate "review code quality" review-only    # pure review mode: review repeatedly to zero findings, read-only
/iterate "full health check" --dry-run # pure review alias: review report + meta-review final report
/iterate defensive "add user login + fix the payment bug"   # defensive-programming mode (v3.0): from design to delivery
```

The first invocation auto-triggers onboarding (if the project has no `ITERATE.md`).

> **Defensive-programming mode (`/iterate defensive`)**: when you want the AI to do **normal incremental coding work** — add features, fix bugs, refactor, wire up an API, add tests — instead of a pure review, use `/iterate defensive`. The host AI carries defensive-programming discipline from start to finish: declare assumptions + run `iterate guard pre-check` before touching code, validate at trust boundaries with minimal steps while editing, run `iterate guard post-check` after every change, and finish with `iterate invariant` plus the full 9-dimension review→fix→converge loop as a **delivery gate**. It does not deliver until everything converges. The original `/iterate` mode (v2) is unchanged.

> **Pure review mode / review-only (dry-run)**: when the invocation contains `review-only` or `dry-run`, this skill does a read-only health check and **never modifies any file**. It repeatedly reviews in parallel until a round yields 0 new findings (convergence), produces a review report, then **reviews that report itself** (meta-review, checking internal consistency) and gives a final report with an `approved` / `needs_revision` verdict. Use it for pre-release health checks, code quality audits, or when you don't want the AI to touch code.

### In the terminal

```bash
# Interactive onboarding (auto-branches on first/non-first use)
iterate onboard

# Add / view / clear personalization constraints mid-way
iterate personalize          # enter the 9-step personalization wizard
iterate personalize --clear  # clear all personalization (structured rules + ITERATE.md sections)
iterate personalize --clear --yes  # skip confirmation
iterate show                 # read-only merged config + personalization details (--json for structured output)

# View onboarding status and drift detection
iterate status

# Incremental refresh (keeps hand-written ITERATE.md section)
iterate refresh

# Full re-onboarding (backs up old files)
iterate reonboard

# Project health diagnostics (config / ITERATE.md / onboarding vs skill spec)
iterate doctor

# Non-interactive config inspection & editing (no wizard)
iterate config                      # list all settable values
iterate config get max_rounds      # read one resolved value (--json for {"key": value})
iterate config set goal "..."      # validate + write one value (auto timestamped backup)

# Defensive-programming deterministic checks (v3.0 defensive mode)
iterate guard pre-check src/        # before editing: target exists / worktree clean / manifests ready
iterate guard post-check python     # after editing: run exactly validation.commands.<module>
iterate invariant                   # at delivery: file-assertions + exact commands (degrades to validation.commands)
```

#### iterate doctor (project health diagnostics)

`iterate doctor` checks your project against the skill's own spec to catch drift early:

| Check | Description |
|---|---|
| Onboarding completeness | `ITERATE.md` and `iterate.config.yaml` exist |
| Config parses & is valid | Config parses as YAML and **fully** matches `config/config.schema.json` |
| Dimensions valid | `dimensions` only reference one of the 9 spec dimensions |
| Review scope valid | `review.scope` allows only `full` / `changed-only` |
| Merge target branch | `git.target_branch` is a non-empty string |
| Validation commands | `validation.commands` is a non-empty string list |
| Command whitelist | `command_whitelist` entries are safe and every command is within the whitelist |
| Personalization dimension refs | `personalization` dimension references point to enabled dimensions |
| Version consistency | onboarding `skill_version` matches the currently installed skill version |
| Drift detection | whether the tech-stack manifest changed since onboarding |

```bash
iterate doctor            # TUI output; healthy exit 0, problems exit 1
iterate doctor --json     # structured JSON to stdout (script-friendly)
iterate doctor --json-out report.json   # write JSON report to a file (auto-creates dirs)
iterate doctor --fix      # apply safe, non-destructive fixes (auto timestamped backup), then re-run diagnostics
```

`--fix` only does items that can be safely auto-fixed, and always creates a timestamped backup of `iterate.config.yaml` (`.doctorfix-<timestamp>` suffix) before fixing. Destructive/ambiguous fixes are never applied automatically — they're reported for you to handle manually. Currently auto-fixable: `dimensions` de-dupe/empty-restore-to-default, `language` invalid value reset to `en`, `max_rounds` non-integer removal / out-of-range clamp to `[1, 50]`, `git.target_branch` empty reset to `main`, `onboarding.skill_version` sync to installed version.

#### iterate show (read-only merged config & personalization)

`iterate show` read-only displays the current merged project state — handy for quickly checking config and constraints, **writing no files**:

```bash
iterate show        # TUI output: onboarding metadata + effective config + personalization + drift status
iterate show --json # structured JSON to stdout (for scripts / CI / quick diff)
```

When you just want to confirm what restrictions are configured (forbidden areas, risk zones, known intent, dimension customization, fix order, notes, code conventions, extra validation commands), or check the merged `validation.commands` / whitelist, `iterate show` is clearer than reading `iterate.config.yaml` + `ITERATE.md` directly.

#### iterate personalize --clear (clear personalization)

When you need to clear previously configured personalization constraints, do it in one shot after confirmation (structured rules removed from `iterate.config.yaml`, associated extra validation commands cleaned from `validation.commands`, personalization section in `ITERATE.md` user area removed, while keeping your hand-written content):

```bash
iterate personalize --clear       # with confirmation prompt
iterate personalize --clear --yes # skip confirmation
```

If there is no personalization content, it says "no personalization to clear" and exits normally (exit code 0).

#### iterate config (non-interactive config get/set)

`iterate config` lets you inspect or change config values without launching the wizard — handy for scripts / CI / quick edits:

```bash
iterate config                 # TUI: list every settable key + current value
iterate config --json          # JSON object of all settable values (stdout stays clean for scripts)
iterate config get max_rounds  # print one resolved value; --json -> {"max_rounds": ...}
iterate config set language zh # validate + write one value (auto timestamped backup before write)
iterate config set reasoning_effort high --json  # confirm object {"key": ..., "value": ...}
```

Supports flat keys (`goal`, `max_rounds`, `reasoning_effort`, `language`, `mode`, `dimensions`) and nested segments (`atomic.*`, `git.*`, `review.scope`, `reviewer.*`, `validation.commands`, `invariants.*`). A corrupted config is never overwritten — `set` aborts with a clear error.

#### iterate guard (defensive-mode pre/post-edit checks, v3.0)

Deterministic fail-loud checks the host AI runs around every coding step in defensive mode. Contracts (exit code 0 = safe to proceed / change is safe; 1 = must fix or roll back):

| Command | When | Checks |
|---|---|---|
| `iterate guard pre-check [paths...]` | before editing | targets exist, git worktree is clean, manifest files ready, validation config is safe (`PASS`/`FAIL`) |
| `iterate guard post-check [module...]` | after each change | executes exactly the configured `validation.commands.<module>` (the runtime's single authority whitelist — no composition, no prefixing) |

Both support `--json` and `--dry-run` (preview exact commands without executing).

#### iterate invariant (defensive-mode delivery gate, v3.0)

`iterate invariant` checks the project-level `invariants` declared in config (`invariants.ensure` file-existence assertions + `invariants.commands` exact per-module command lists). When no `invariants` section is configured it **degrades to `validation.commands`**, so old configs keep working unchanged. Exit 0 = invariants hold, 1 = violations found. Supports `--json` / `--dry-run`.

### Edge Cases

- **Onboarding cancelled mid-way (Ctrl+C / "skip")**: no half-finished artifacts. All files are written **atomically** (`tempfile + os.replace`), so nothing is left behind — just re-run.
- **Hand-written `ITERATE.md` missing `USER-OWNED` markers**: `iterate refresh` (and AI refresh) **refuses to overwrite and errors** instead of destroying your hand-written content. Add `<!-- ITERATE:USER-OWNED:START/END -->` markers to refresh normally.
- **Non-git project**: `onboard` / `status` / `refresh` / `doctor` / `personalize` don't depend on git and work directly; but the git-isolated branch/merge/push steps in `/iterate` need a git repo — without one those steps are skipped or prompted.
- **Empty project / no manifest files**: onboarding generates the knowledge base normally; without fingerprint files like `package.json` / `pyproject.toml`, drift detection skips fingerprint comparison.
- **Corrupted `iterate.config.yaml` (YAML error / schema violation)**: `iterate doctor` reports schema errors; `doctor --fix` only fixes safely auto-fixable items, the rest need manual fixing. If config fails schema validation, `/iterate` aborts immediately with an error rather than running with a broken config.
- **Early convergence**: when a round returns 0 new findings, iteration ends early (Early Stop) instead of running to `max_rounds`.

### Recommended New-User Path

```text
1. Install      npx iterate-skill-installer      # auto-installs skill + iterate CLI
2. Init         iterate onboard                  # generates ITERATE.md + iterate.config.yaml
3. Health check iterate doctor                    # confirm config health (optional but recommended)
4. Add rules    iterate personalize              # project-specific constraints (optional)
5. Iterate      /iterate "your goal"             # or directly in your AI assistant
```

The first `/iterate` invocation will do onboarding first if the project has no knowledge base — seeing a "initializing project" message is normal, not a failure. After that, every round's changes stay on an isolated `iterate/*` branch/worktree; merge/push is off by default and happens after you review.

---

## How It Works

### Onboarding (project knowledge base initialization)

Each `/iterate` invocation checks whether `ITERATE.md` exists in the project root. If not, onboarding is triggered.

| Channel | Use case | Output |
|---|---|---|
| **AI Onboarding** | AI auto-identifies the tech stack from directory structure / manifest files | `ITERATE.md` + `iterate.config.yaml` |
| **CLI Onboarding** | CLI scans then lets you confirm/adjust the tech stack and config | Same as above |

The scan only reads file/directory **existence** and a few public context files like README.md — it does not read `.env`, keys, credentials, or other sensitive file contents. Project-specific constraints can be added with `iterate personalize`.

`ITERATE.md` has two sections:

- `<!-- ITERATE:AI-MAINTAINED:START -->`: AI-maintained section, updated on refresh.
- `<!-- ITERATE:USER-OWNED:START -->`: user-owned section — your hand-written conventions, forbidden areas, risk zones; preserved on refresh.

### Drift detection

Each `/iterate` invocation recomputes SHA-256 fingerprints of manifest files such as `package.json`, `pyproject.toml`:

- No drift → silent pass
- Drift detected → prompt: continue / incremental refresh / full re-onboarding

### Personalization

An AI scan can discover the tech stack and directory structure, but not project-specific constraints. `iterate personalize` captures that knowledge:

| Category | Description | Location |
|---|---|---|
| Forbidden areas | files/dirs iterate must not modify | `iterate.config.yaml` |
| Risk zones | changes needing architecture approval | `iterate.config.yaml` |
| Known intent | suppresses false positives | `iterate.config.yaml` |
| Dimension customization | append focus to specific dimensions | `iterate.config.yaml` |
| Fix priority order | per-dimension fix priority | `iterate.config.yaml` |
| Forbidden fix methods | techniques that must not be used | `iterate.config.yaml` |
| Project conventions & notes | lessons learned, known pitfalls | `ITERATE.md` user area |
| Extra validation commands | project-specific validation commands | `iterate.config.yaml` |

See [`config/iterate.config.yaml`](./config/iterate.config.yaml) for a complete example.

### Scope dimension sets & review routing

The top-level `dimensions` is the default for **whole-project / global** review. For **scope-specific** goals, the skill's dimension planning (SKILL.md Phase 0) routes to the right dimension scheme:

1. **Goal is empty or generic** (e.g. "improve code quality") → use the global `dimensions`. Zero friction.
2. **Goal names a scope that hits a preset `dimension_sets` set** (e.g. "review the frontend" → `frontend`) → use that set's `dimensions` + `focus` override directly, after a quick confirmation.
3. **Goal names an off-catalog scope** (no preset matches) → the AI **redefines dimensions from scratch**: it starts from the 9 canonical dimensions (not from global `dimensions` or any existing set, which would just be a lazy copy), picks the ones truly relevant to that scope, gives each **a scope-specific independent reason**, and may add temporary non-standard dimensions. This redefinition is recorded in `.iterate_decisions.md` under a dedicated `### Scope Dimension Redefinition (on-the-fly)` section, and is **validated by `scripts/validate.py decisions`** to ensure each reason isn't just a copy of the dimension's default focus prompt.

Preset sets live only in `iterate.config.yaml` (`dimension_sets`); `ITERATE.md` renders a one-time "Recommended Review Blueprints" listing. Ad-hoc redefinitions are bounded to `.iterate_decisions.md` per-round — they never balloon `ITERATE.md` or `iterate.config.yaml`, so the knowledge base stays small no matter how many iterations accumulate.

### Decision log (`.iterate_decisions.md`)

Every round's AI decisions — atomic fixes (direct), architectural fixes (approved + executed / deferred), reverted fixes, important AI decisions, validation results, and any off-catalog scope redefinitions — are recorded in `.iterate_decisions.md` (see the template in `templates/iterate-decisions.template.md`). This keeps the process auditable while keeping `ITERATE.md`'s AI-maintained section to a **single latest snapshot**.

### Core flow

```text
Step 0 — Onboarding Check
  └─ locate project root → check ITERATE.md → drift detection → (onboarding if missing)

Setup
  └─ extract goal → load config → read project context → create isolated branch/worktree

Loop (round = 1 .. max_rounds)
  ├─ Phase 1: N-dimension parallel review
  ├─ Phase 2: atomic issues auto-fixed
  ├─ Phase 3: architecture issues executed after user approval
  ├─ Phase 4: record round result
  └─ Phase 5: verify → merge (if auto_merge=true) → push (if push_per_round=true)

Summary
```

For the detailed flow, see [`SKILL.md`](./SKILL.md).

---

## Configuration

The default config lives in [`config/iterate.config.yaml`](./config/iterate.config.yaml). Project-level config recursively overrides same-name fields in the Master config.

Common config options:

| Option | Type | Default | Description |
|---|---|---|---|
| `goal` | string | `"Improve code quality"` | iteration goal |
| `max_rounds` | int | `7` | max rounds (cap 50) |
| `language` | string | `"en"` | output language: `zh` / `en` |
| `mode` | string | `"iterate"` | default execution mode: `iterate` / `defensive` (v3.0) |
| `reasoning_effort` | string? | `null` | `low` / `medium` / `high`; `null` = follow provider default |
| `dimensions` | list | 9 dimensions | enabled review dimensions (whole-project default) |
| `dimension_sets` | object | — | named scope blueprints (`frontend`/`api`/`security`/…) with `dimensions` + optional `focus` |
| `invariants` | object | — | `ensure` file-existence assertions + `commands` exact per-module lists (defensive-mode delivery gate) |
| `review.scope` | string | `"full"` | `full` / `changed-only` |
| `atomic.max_lines` | int | `20` | max lines for an atomic issue |
| `atomic.max_adjacent_methods` | int | `3` | max adjacent methods for an atomic issue |
| `git.target_branch` | string | `main` | merge target branch |
| `git.use_worktree` | bool | `false` | prefer a worktree for isolation |
| `git.push_per_round` | bool | `false` | push after each round passes |
| `git.auto_merge` | bool | `false` | auto-merge after verification |
| `validation.command_whitelist` | list | common prefixes | allowed command prefixes (config-time safety) |
| `validation.commands` | object | example | per-language validation commands (runtime's single authority whitelist) |
| `reviewer.evidence_validation` | bool | `true` | hard gate: every finding's file/line must exist on disk |
| `reviewer.coverage_validation` | bool | `true` | emit `COVERAGE_GAP` when a reviewer skipped assigned files |
| `reviewer.scope_chunk_size` | int | `25` | files per reviewer batch in a `full` scope review |
| `onboarding.drift_check` | bool | `true` | whether to check manifest drift |

Example:

```yaml
goal: "improve code quality, ensure all functions are ≤80 lines and tests pass"
max_rounds: 7
language: en
mode: iterate          # or defensive

dimensions:
  - correctness
  - security
  - performance
  - architecture
  - style-tests
  - tech-debt
  - spec-compliance
  - frontend-backend
  - ui-ux

# Named scope blueprints: a scoped goal routes to its matching set instead
# of the global `dimensions`.
dimension_sets:
  frontend:
    dimensions:
      - ui-ux
      - frontend-backend
      - correctness
      - performance
    focus:
      ui-ux: "responsive layout, a11y, and state handling specific to views"
  security:
    dimensions:
      - security
      - correctness
    focus:
      security: "OWASP Top 10, authn/authz, injection, secret handling"

# Defensive-mode delivery gate: artifacts that must exist and commands that
# must pass at delivery (absent -> degrades to validation.commands).
invariants:
  ensure:
    - "README.md"
  commands:
    python:
      - "pytest tests/ -x -q --timeout=60"

validation:
  command_whitelist:
    - "ruff"
    - "mypy"
    - "pytest"
    - "swift"
    - "npm run"
  commands:
    python:
      - "ruff check src/"
      - "mypy src/ --ignore-missing-imports"
      - "pytest tests/ -x -q --timeout=60"
    swift:
      - "swift build -c debug"
    typescript:
      - "npm run compile"
```

> Commands in `validation.commands` **must** start with a prefix in `command_whitelist`, or they are rejected.

---

## FAQ

### Installation

**Q: The installer needs GitHub access; what if my network can't reach GitHub?**
A: The installer downloads and verifies from GitHub Release, so it needs GitHub access. If your network is restricted, use GitHub-independent alternatives:
- Manually copy [`SKILL.md`](./SKILL.md) to the assistant directory (see "Method B").
- CN mirror channels (ModelScope / SkillHub CN) are published and can provide the skill files.
- Download from a community mirror, then run `python scripts/install.py install` locally.

**Q: `npx iterate-skill-installer` reports a Python or Node version mismatch?**
A: The installer requires Node.js 18+ and Python 3.10+. Upgrade your system Python/Node, or make sure `python3` / `node` are on the PATH. The installer prefers `python3`, then falls back to `python`.

**Q: The installer puts the `iterate` CLI on my machine; can I avoid that?**
A: Yes. `npx iterate-skill-installer` also installs the `iterate` CLI (prefer `pipx`, else `pip install --user`) to run `iterate onboard`, etc. If you don't want automatic CLI install, use the "manually copy SKILL.md" or "source scripts" methods — copy skill files only.

**Q: I want to cancel mid-install; will it leave half-finished artifacts?**
A: No. The installer does download/verify/unpack in a temp dir and only writes into the assistant dir after the target is selected. Cancelling or failing won't overwrite an already-installed skill. If one exists, reinstall prompts to overwrite by default (needs `--force`).

### Usage

**Q: What is this Skill for, and what isn't it for?**
A: It's for **multi-round** code review and auto-fixing — e.g. paying down tech debt, eliminating lint/type/test issues over rounds, project-level refactoring. It's **not** for single simple changes (one line, add a comment) — use a normal conversation for those, no need for `/iterate`.

**Q: `iterate` mode vs `defensive` mode — which should I use?**
A: `/iterate` is for **reviewing/fixing existing code** until it converges. `/iterate defensive` is for when you want the AI to do **normal coding work** (add a feature, fix a bug, refactor, wire up an API, write tests): the host AI runs `guard pre-check` before editing, `guard post-check` after every change, and finishes with `invariant` plus the full review→fix→converge loop as a delivery gate. Want the AI to "build something correctly" → `defensive`; want it to "polish/review what's there to zero findings" → `iterate`.

**Q: Why does the first use appear to do nothing?**
A: Before your first `/iterate` or `iterate onboard`, the project has no `ITERATE.md` or `iterate.config.yaml`. On first use the skill does **onboarding first**: it tells you "this is the first use, initializing the project", scans the codebase to generate `ITERATE.md` and config, then iterates. If you see an init message instead of immediate review, that's normal. You can also run `iterate onboard` in the project root to init manually.

**Q: It feels stuck on a large project, no progress?**
A: The first round reviews multiple dimensions in parallel and can take a while. To reduce the "stuck" feeling, the skill now streams progress: `▶ Round N/max` at round start, per-dimension `⏳ reviewing …` during parallel review, and `✅ Round N complete` at round end. To speed it up:
- Set `review.scope` to `changed-only` in `iterate.config.yaml` to review only this round's changes.
- Split reviewer tasks by directory/module (see the Reviewer Prompt checklist in SKILL.md).
- Lower `max_rounds` to avoid unnecessary extra rounds.

**Q: What does the drift prompt mean at runtime?**
A: Drift detection compares SHA-256 fingerprints of manifest files like `package.json`, `pyproject.toml`. If deps or config changed, it means the project state differs from the last onboarding; you'll be prompted to: continue / incremental refresh (`iterate refresh`) / full re-onboarding (`iterate reonboard`).

**Q: My changes weren't merged to main or pushed remotely?**
A: That's the **secure default**: `git.auto_merge` and `git.push_per_round` both default to `false`, so changes stay on an isolated `iterate/*` branch or worktree for you to review before deciding to merge/push. To auto-merge/push, enable those two options explicitly in `iterate.config.yaml`.

**Q: I edited `iterate.config.yaml` manually but some validation commands don't work?**
A: Commands in `validation.commands` **must** start with a prefix in `validation.command_whitelist`, or they're rejected. Extra validation commands added by personalization also only accept 30+ pre-approved tool prefixes and reject shell metacharacters like `;`, `|`, `&` — for safety, so the project config can't run arbitrary commands.

**Q: I want to add a new validation tool (e.g. `sphinx`), how?**
A: The strict whitelist only accepts pre-approved tool prefixes (so project config can't run arbitrary commands). Two **safe** ways to add a tool:
- **Operator-level environment variable (recommended, no source change)**: set `ITERATE_EXTRA_SAFE_COMMAND_PREFIXES=sphinx` in the runtime environment (comma/space-separated for multiple tools). This variable **can only be set at the system level**, not in the project config, so it doesn't break the security model; entries containing `;`, `|`, `&` are dropped (fail-closed).
- **Source-level extension**: append the tool name to `KNOWN_SAFE_COMMAND_PREFIXES` in `iterate_cli/personalize.py`, then reinstall.
- Or configure directly via `validation.command_whitelist` + `validation.commands` (must pass `python scripts/validate.py config`).

### Security

**Q: Does this Skill read my keys / `.env`?**
A: No. The skill and onboarding scan only read manifest existence and public context files like `README.md` / `CLAUDE.md`; it explicitly does not read `.env`, `*.key`, `secrets/`, `*.pem`, etc. `projectContext` also never contains API keys, passwords, or tokens.

**Q: Is updating safe?**
A: Yes. `scripts/install.py update` and `npx iterate-skill-installer` download the pre-uploaded `iterate-skill.tar.gz` + `SHA256SUMS.txt` from the GitHub Release and force SHA256 verification after download; install is rejected if missing or mismatched.

---

## Security

- **High autonomy**: this skill autonomously edits files, runs `git` operations, and runs commands in `validation.commands`. All changes first happen on an isolated branch/worktree; architecture fixes require user approval.
- **Secure-by-default Git**: `push_per_round` and `auto_merge` both default to `false`; merge/push are opt-in, so changes stay on the iteration branch unless explicitly enabled. Rollback uses non-destructive commands like `git restore`.
- **Two-layer command whitelist**:
  - Command prefixes are validated at config time.
  - Personalization `extra_validation_commands` only accept 30+ pre-approved tool prefixes and reject shell metacharacters like `;`, `|`, `&`; commands are re-validated on load/merge, so hand-edited config can't bypass the whitelist.
- **Sensitive files**: this skill and its installer never read `.env`, keys, credentials, etc.; onboarding scans only check the existence of public files like manifests.
- **Update security**: `scripts/install.py update` and `npx iterate-skill-installer` download the pre-uploaded `iterate-skill.tar.gz` + `SHA256SUMS.txt` from the GitHub Release and force SHA256 verification; rejected if missing or mismatched.
- **Installer disclosure**: `npx iterate-skill-installer` also installs the `iterate` CLI to PATH (prefer `pipx` isolated, else `--user`). If you don't want the CLI, use the manual-copy or source-script method.

---

## Directory Structure

```text
iterate-skill/
├── SKILL.md                          # core skill file
├── README.md                         # this file (English)
├── README.zh-CN.md                   # Chinese README
├── LICENSE                           # MIT license
├── CONTRIBUTING.md                   # contribution guide
├── CHANGELOG.md                      # version changelog
├── pyproject.toml                    # iterate CLI package definition
├── npm-installer/                    # npx one-command installer source
│   ├── bin/cli.js
│   ├── lib/installer.js
│   └── package.json
├── config/
│   ├── iterate.config.yaml           # default config (Master)
│   ├── config.schema.json            # config JSON Schema
│   ├── dimensions.yaml               # aggregated dimension definitions
│   └── dimensions/                   # data-driven dimension definitions
├── examples/                         # per-language project examples
├── harness/                          # two engineering components of the iterate ecosystem (monorepo)
│   ├── iterate-harness/              # standalone headless engine (npm: iterate-harness, command ih)
│   │   ├── src/iterate_harness/      #   CLI / engine / web / UI source
│   │   ├── frontend/                 #   terminal / web frontend UI
│   │   ├── npm/                      #   npm wrapper (ih)
│   │   └── scripts/                  #   install scripts and e2e tests
│   └── iterate-plugin/               # dsh desktop plugin (npm: iterate-plugin)
│       ├── src/                      #   server logic (TypeScript, compiled to dist/)
│       ├── lib/                      #   client UI injection entry
│       └── cordis.patch.yml          #   dsh bundle declaration
├── templates/
│   ├── ITERATE.template.md           # knowledge-base template
│   └── iterate-decisions.template.md # per-round decision log template
├── iterate_cli/                      # onboarding CLI source
│   ├── cli.py                        #   top-level command dispatcher
│   ├── guard.py                      #   guard pre/post-check (defensive mode)
│   ├── configcmd.py                  #   iterate config get/set
│   ├── dimension_sets.py             #   scope dimension-set suggestion / normalize / merge
│   ├── wizard.py / scan.py / generator.py / refresh.py / personalize.py /
│   │   doctor.py / show.py / fingerprint.py / tui.py
│   └── data/
│       ├── ITERATE.template.md       # wheel-packaged template
│       └── config.schema.json        # wheel-packaged schema (kept in sync)
├── scripts/
│   ├── install.py                    # install/uninstall/config/validate script
│   ├── validate.py                   # config & decision-log validation (incl. scope redefinition checks)
│   └── requirements.txt              # script dependencies
├── tools/                            # per-assistant implementation examples
├── tests/                            # unit tests
└── .github/workflows/                # CI / Release
```

---

## Contributing

Issues and PRs are welcome!

1. Fork this repo
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Commit: `git commit -m "feat: description"`
4. Push: `git push origin feat/your-feature`
5. Open a Pull Request

Please keep `SKILL.md` in its bilingual (English/Chinese) structure and add config examples for new features.

---

## Disclaimer

This project is provided "AS IS", without warranty of any kind, express or implied, including but not limited to warranties of merchantability, fitness for a particular purpose, and non-infringement.

**Automated code review and fixing carry inherent risks.** Changes made in normal mode are generated by AI models and may introduce defects, regressions, or unexpected behavior. Before merging changes, you should:

- Review every diff individually before applying to `main` or pushing.
- Ensure the project is under git version control and can be rolled back (`git restore`, revert, or restore from backup).
- Run your project's own tests and build checks after each round of fixes.
- Never run this project on keys, credentials, `.env`, or any files you're not allowed to modify; configure the corresponding protected paths in `iterate.config.yaml`'s `protected_paths`.

You are solely responsible for the code you produce, modify, or commit while using this project. By using this project you agree that the maintainers and contributors are not liable for any loss, damage, or legal consequences arising from your use of it.

---

## License

[MIT](./LICENSE) © 2026 iterate-skill contributors