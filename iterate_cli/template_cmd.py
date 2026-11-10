"""Bundled template surfacing (``iterate template``).

The onboarding / refresh / decision-log templates have always lived inside the
package, consumed silently by the generator — a user who wanted to know *what
structure* ``iterate onboard`` produces, or to customise a copy of the
ITERATE.md skeleton for their own team, had to locate the file inside the
installed skill directory by hand. ``iterate template`` closes that gap: it
lists every bundled template and prints one verbatim, so the skill's own
template surface is discoverable without reading the package source.

The module is read-only and side-effect free: it never writes, never touches
the project, and works from any directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from iterate_cli.tui import tui

#: Canonical template name -> (repo-relative path, one-line description).
#: The repo-relative ``templates/`` dir is what the package ships (and what the
#: generator falls back to when ``iterate_cli/data/`` is absent), so these are
#: the templates a user can actually reach after install.
TEMPLATE_REGISTRY: dict[str, tuple[str, str]] = {
    "ITERATE.template.md": (
        "templates/ITERATE.template.md",
        (
            "ITERATE.md skeleton: the project knowledge base structure that "
            "onboarding / refresh render (AI-maintained + user-owned sections)."
        ),
    ),
    "onboarding-playbook.md": (
        "templates/onboarding-playbook.md",
        (
            "AI onboarding reference: per-language dimension and "
            "validation-command suggestions the AI adapts, never copies "
            "mechanically."
        ),
    ),
    "iterate-decisions.template.md": (
        "templates/iterate-decisions.template.md",
        (
            "Decision-log structure: the per-round ``.iterate_decisions.md`` "
            "format the AI appends during ``/iterate`` sessions."
        ),
    ),
}

#: Friendly aliases so ``iterate template show iterate`` is not forced to spell
#: the full filename.
_ALIASES: dict[str, str] = {
    "iterate": "ITERATE.template.md",
    "iteratemd": "ITERATE.template.md",
    "playbook": "onboarding-playbook.md",
    "onboarding-playbook": "onboarding-playbook.md",
    "decisions": "iterate-decisions.template.md",
    "decision-log": "iterate-decisions.template.md",
    "decisionlog": "iterate-decisions.template.md",
}

#: The templates root as shipped. Generator falls back to the repo-relative
#: ``templates/`` dir; using the same base keeps this command correct whether
#: it runs from a checkout or an installed package.
_TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates"


def _templates_root() -> Path:
    """Return the templates directory (may not exist in an odd install)."""
    return _TEMPLATES_ROOT


def list_templates() -> list[dict[str, Any]]:
    """Return metadata for every bundled template.

    Returns:
        A list of ``{name, description, path, exists}`` dicts, ordered by the
        registry. ``exists`` is False when the file is missing from disk so a
        caller (and ``iterate template``) can still name it instead of silently
        dropping it — a missing bundled template is a packaging problem worth
        surfacing, not hiding.
    """
    root = _templates_root()
    items: list[dict[str, Any]] = []
    for name, (rel, description) in TEMPLATE_REGISTRY.items():
        path = root / Path(rel).name
        items.append(
            {
                "name": name,
                "description": description,
                "path": str(path),
                "exists": path.is_file(),
            }
        )
    return items


def resolve_template(name: str) -> str | None:
    """Resolve a template name or alias to its canonical registry name.

    Args:
        name: A canonical filename or a friendly alias (``iterate``,
            ``playbook``, ``decisions``).

    Returns:
        The canonical template name, or None when unknown.
    """
    if name in TEMPLATE_REGISTRY:
        return name
    return _ALIASES.get(name)


def read_template(name: str) -> tuple[str, str, str] | None:
    """Read a template's content.

    Args:
        name: A canonical filename or friendly alias.

    Returns:
        ``(canonical_name, content, path)`` on success, or None when the name
        is unknown or the file is missing/unreadable.
    """
    canonical = resolve_template(name)
    if canonical is None:
        return None
    rel, _ = TEMPLATE_REGISTRY[canonical]
    path = _templates_root() / Path(rel).name
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return canonical, content, str(path)


def run_template(
    action: str | None,
    name: str | None,
    json_output: bool = False,
) -> int:
    """Handle the ``iterate template`` subcommand.

    Args:
        action: ``list`` (default when omitted) or ``show``.
        name: Template name/alias to show (required for ``show``).
        json_output: When True, emit structured JSON instead of TUI lines.

    Returns:
        Exit code: 0 on success, 2 on usage error (unknown template name),
        1 when a known template file is missing/unreadable.
    """
    if action in (None, "list"):
        items = list_templates()
        if json_output:
            import json

            print(
                json.dumps(
                    {"templates": items},
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )
            return 0
        tui.intro("Iterate Skill — Templates")
        for item in items:
            tui.key_value(
                item["name"],
                "missing" if not item["exists"] else "",
                indent=2,
            )
            tui.hint(item["description"], indent=4)
            tui.empty_line()
        tui.hint("Show one with `iterate template show <name>`.")
        return 0

    if action == "show":
        if not name:
            if json_output:
                import json

                print(
                    json.dumps(
                        {"error": "template show requires a name"},
                        ensure_ascii=False,
                    )
                )
            else:
                tui.error("`iterate template show` requires a template name.")
                tui.hint("List them with `iterate template list`.", indent=2)
            return 2
        result = read_template(name)
        if result is None:
            if json_output:
                import json

                print(
                    json.dumps(
                        {
                            "error": f"unknown template: {name}",
                            "hint": "run `iterate template list`",
                        },
                        ensure_ascii=False,
                    )
                )
            else:
                tui.error(f"Unknown template: {name}")
                tui.hint("Run `iterate template list` for the available names.", indent=2)
            return 2
        canonical, content, path = result
        if json_output:
            import json

            print(
                json.dumps(
                    {
                        "name": canonical,
                        "path": path,
                        "content": content,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        print(content, end="" if content.endswith("\n") else "\n")
        return 0

    # Unknown action.
    if json_output:
        import json

        print(
            json.dumps(
                {
                    "error": f"unknown template action: {action}",
                    "hint": "use 'list' or 'show'",
                },
                ensure_ascii=False,
            )
        )
    else:
        tui.error(f"Unknown template action: {action}")
        tui.hint("Use `list` or `show`.", indent=2)
    return 2
