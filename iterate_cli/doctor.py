"""Project health diagnostics for the iterate skill.

``iterate doctor`` checks a project's iterate.config.yaml, ITERATE.md and
onboarding state against the skill's own canonical definitions so that a
project drifting from the skill's expectations is surfaced early.

Checks performed:
- Onboarding completeness (ITERATE.md + iterate.config.yaml exist).
- Config loads as a YAML mapping.
- ``dimensions`` reference only canonical dimension ids.
- ``review.scope`` is one of the supported values.
- ``git.target_branch`` is a non-empty string.
- ``validation.commands`` values are non-empty lists of strings.
- Onboarding ``skill_version`` vs the installed skill version.
- Manifest drift (tech-stack changed since onboarding).

All checks can be run in a structured (``--json``) or human (TUI) mode.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from iterate_cli import __version__ as SKILL_VERSION
from iterate_cli.refresh import (
    check_onboarding_drift,
    is_onboarding_complete,
    load_onboarding_config,
)

# Canonical dimension ids declared in config/dimensions.yaml (the single
# source of truth for the skill). Kept in sync by tests/test_dimension_lock.py.
CANONICAL_DIMENSIONS: tuple[str, ...] = (
    "correctness",
    "security",
    "performance",
    "architecture",
    "style-tests",
    "tech-debt",
    "spec-compliance",
    "frontend-backend",
    "ui-ux",
)

# Supported review.scope values.
SUPPORTED_SCOPES: frozenset[str] = frozenset({"full", "changed-only"})

# config keys that must be a mapping of module -> non-empty command list.
_COMMAND_MODULES_KEYS: tuple[str, ...] = ("validation.commands", "commands.validation")


@dataclass
class DoctorFinding:
    """A single diagnostic finding."""

    severity: str  # "ok" | "warn" | "error"
    check: str
    message: str
    detail: str = ""


@dataclass
class DoctorReport:
    """Aggregated doctor output for a project."""

    project: str
    findings: list[DoctorFinding] = field(default_factory=list)

    def has_errors(self) -> bool:
        return any(f.severity == "error" for f in self.findings)

    def has_warnings(self) -> bool:
        return any(f.severity == "warn" for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        """Structured representation for ``--json`` output."""
        return {
            "project": self.project,
            "skill_version": SKILL_VERSION,
            "healthy": not self.has_errors(),
            "findings": [
                {
                    "severity": f.severity,
                    "check": f.check,
                    "message": f.message,
                    "detail": f.detail,
                }
                for f in self.findings
            ],
        }


def _ok(report: DoctorReport, check: str, message: str) -> None:
    report.findings.append(DoctorFinding("ok", check, message))


def _warn(report: DoctorReport, check: str, message: str, detail: str = "") -> None:
    report.findings.append(DoctorFinding("warn", check, message, detail))


def _err(report: DoctorReport, check: str, message: str, detail: str = "") -> None:
    report.findings.append(DoctorFinding("error", check, message, detail))


def _dimension_ids(config: dict[str, Any]) -> list[str]:
    """Return the declared dimensions (default to canonical when unset)."""
    dims = config.get("dimensions")
    if isinstance(dims, list):
        return [str(d) for d in dims]
    return list(CANONICAL_DIMENSIONS)


def run_doctor(project_root: Path) -> DoctorReport:
    """Run all health checks against ``project_root``.

    Args:
        project_root: Project root directory.

    Returns:
        A DoctorReport aggregating every finding.
    """
    canonical_set = set(CANONICAL_DIMENSIONS)
    report = DoctorReport(str(project_root))

    # 1. Onboarding completeness.
    if not is_onboarding_complete(project_root):
        _err(
            report,
            "onboarding",
            "Onboarding is not complete: ITERATE.md and/or iterate.config.yaml are missing.",
            "Run `iterate onboard` to initialize the project.",
        )
        return report
    _ok(report, "onboarding", "ITERATE.md and iterate.config.yaml present.")

    # 2. Config loads as a mapping.
    config = load_onboarding_config(project_root)
    if config is None:
        _err(
            report,
            "config.parse",
            "iterate.config.yaml is missing, unreadable, or not a YAML mapping.",
        )
        return report
    _ok(report, "config.parse", "iterate.config.yaml parsed as a valid YAML mapping.")

    # 3. Dimensions reference only canonical ids.
    dims = _dimension_ids(config)
    unknown = [d for d in dims if d not in canonical_set]
    if unknown:
        _warn(
            report,
            "dimensions",
            f"Config references {len(unknown)} unknown dimension(s): {', '.join(sorted(unknown))}.",
            "Unknown dimensions are ignored by reviewers; check config/dimensions.yaml.",
        )
    else:
        _ok(report, "dimensions", f"All {len(dims)} configured dimension(s) are canonical.")

    # 4. review.scope is supported.
    scope = (config.get("review") or {}).get("scope") if isinstance(config.get("review"), dict) else None
    if scope is not None and scope not in SUPPORTED_SCOPES:
        _warn(
            report,
            "review.scope",
            f"review.scope {scope!r} is not a supported value.",
            f"Supported: {', '.join(sorted(SUPPORTED_SCOPES))}.",
        )
    else:
        _ok(report, "review.scope", "review.scope is valid (or defaults to full).")

    # 5. git.target_branch is a non-empty string.
    git_cfg = config.get("git") if isinstance(config.get("git"), dict) else None
    branch = git_cfg.get("target_branch") if git_cfg else None
    if branch is not None and (not isinstance(branch, str) or not branch.strip()):
        _err(report, "git.target_branch", "git.target_branch must be a non-empty string.")
    else:
        _ok(report, "git.target_branch", "git.target_branch is valid (or defaults to main).")

    # 6. validation.commands values are non-empty lists of strings.
    validation = config.get("validation") if isinstance(config.get("validation"), dict) else None
    commands = validation.get("commands") if validation else None
    if commands is not None:
        bad_module = None
        for module, cmds in commands.items():
            if not isinstance(cmds, list) or not cmds or not all(isinstance(c, str) and c.strip() for c in cmds):
                bad_module = module
                break
        if bad_module is not None:
            _err(
                report,
                "validation.commands",
                f"validation.commands[{bad_module!r}] must be a non-empty list of strings.",
            )
        else:
            _ok(report, "validation.commands", "validation.commands module lists are valid.")
    else:
        _ok(report, "validation.commands", "no validation.commands configured (optional).")

    # 7. Onboarding skill_version vs installed skill version.
    onboarding = config.get("onboarding") if isinstance(config.get("onboarding"), dict) else None
    recorded_version = onboarding.get("skill_version") if onboarding else None
    if recorded_version is not None and recorded_version != SKILL_VERSION:
        _warn(
            report,
            "skill_version",
            f"Onboarded with skill {recorded_version!r}, but current skill is {SKILL_VERSION!r}.",
            "Run `iterate refresh` to update the recorded skill version.",
        )
    else:
        _ok(report, "skill_version", f"Skill version {SKILL_VERSION!r} matches onboarding record.")

    # 8. Manifest drift.
    drift = check_onboarding_drift(project_root)
    if drift is None:
        _ok(report, "drift", "No drift check applicable (no fingerprints configured).")
    elif drift.has_drift:
        _warn(report, "drift", f"Manifest drift detected: {drift.summary()}", drift.advice())
    else:
        _ok(report, "drift", "No manifest drift detected.")

    return report


def render_report(report: DoctorReport, json_output: bool = False) -> int:
    """Render a DoctorReport to the terminal.

    Args:
        report: The report to render.
        json_output: When True, print a structured JSON blob instead of TUI.

    Returns:
        Exit code: 0 when healthy, 1 when errors are present.
    """
    if json_output:
        import json

        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 1 if report.has_errors() else 0

    from iterate_cli.tui import tui

    tui.intro(f"Iterate Skill — Doctor / {report.project}")
    has_error = report.has_errors()

    for finding in report.findings:
        if finding.severity == "ok":
            tui.success(f"[{finding.check}] {finding.message}", indent=2)
        elif finding.severity == "warn":
            tui.warning(f"[{finding.check}] {finding.message}", indent=2)
            if finding.detail:
                tui.hint(finding.detail, indent=4)
        else:
            tui.error(f"[{finding.check}] {finding.message}", indent=2)
            if finding.detail:
                tui.hint(finding.detail, indent=4)

    tui.empty_line()
    if has_error:
        tui.error(f"Doctor: {sum(1 for f in report.findings if f.severity == 'error')} error(s) found.")
        return 1
    tui.success(f"Doctor: healthy ({len(report.findings)} checks passed).")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``iterate doctor`` (standalone, for tests)."""
    import argparse

    parser = argparse.ArgumentParser(prog="iterate doctor")
    parser.add_argument("-p", "--project", default=".", help="Project root directory.")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON.")
    args = parser.parse_args(argv)

    report = run_doctor(Path(args.project).resolve())
    return render_report(report, json_output=args.json)


if __name__ == "__main__":
    sys.exit(main())