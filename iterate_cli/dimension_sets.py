"""Named review-dimension blueprint sets (审查维度集).

Addresses a design gap in onboarding: historically the wizard only preset a
single global ``dimensions`` list, so a later user request scoped to a specific
area (e.g. "review the frontend", "audit the API layer") would still fall back
to that one global set. This module introduces ``dimension_sets`` — named
presets, each bundling a subset of dimensions plus optional per-dimension focus
overrides — so onboarding can pre-provision several scope-specific blueprints
and the runtime can route a scoped goal to the matching set.

A set entry has the shape::

    "<name>":
      dimensions: [correctness, security, ...]   # <= canonical dims
      focus:                                      # optional
        "<dimension>": "extra focus text for this scope"

The global ``dimensions`` list remains the default for whole-project/full review;
``dimension_sets`` are additive overrides keyed by named scope.
"""

from __future__ import annotations

import re
from typing import Any

from iterate_cli.scan import ScanResult

# Canonical dimension ids (single source of truth; kept in sync by
# tests/test_dimension_lock.py and scripts/validate.py). Referencing this here
# (rather than importing from iterate_cli.doctor) avoids a circular import while
# staying the same value set the schema enum locks.
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

# Named presets offered during onboarding, keyed by scope name. ``dims`` are
# the base dimension keys for that scope. The scanner prunes these by what the
# project actually contains (see ``suggest_dimension_sets``).
DIMENSION_SET_CATALOG: dict[str, dict[str, Any]] = {
    "frontend": {
        "dimensions": ["ui-ux", "frontend-backend", "performance", "correctness"],
    },
    "api": {
        "dimensions": ["security", "architecture", "frontend-backend", "correctness"],
    },
    "security": {
        "dimensions": ["security", "correctness", "architecture"],
    },
    "performance": {
        "dimensions": ["performance", "architecture", "correctness"],
    },
    "style-tests": {
        "dimensions": ["style-tests", "correctness", "tech-debt"],
    },
}

# Scope-name charset (safe for use as an ITERATE.md anchor / config key).
_SCOPE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# Focus override shape: an optional mapping dimension -> free text.
DIMENSION_SET_STRUCT_DESC = "dimension_sets.<name> must map to {dimensions: [...], focus?: {...}}"


def is_valid_set_name(name: str) -> bool:
    """Return True when ``name`` is usable as a dimension-set key.

    Restricts scope names to alphanumerics/underscore/dot/dash so a user-supplied
    name can never smuggle TOC-breaking or injection characters into either the
    config key or an ITERATE.md anchor.
    """
    return bool(_SCOPE_NAME_RE.match(name))


def _normalize_set(raw: Any) -> dict[str, Any] | None:
    """Normalize a raw dimension-set value to ``{dimensions, focus}``.

    Returns None when the shape is invalid. Focus overrides are kept only for
    dimensions actually present in that set's ``dimensions``, so a stale focus
    key can never reference a disabled dimension.
    """
    if not isinstance(raw, dict):
        return None

    dims_raw = raw.get("dimensions")
    if not isinstance(dims_raw, list) or not dims_raw:
        return None
    if not all(isinstance(d, str) for d in dims_raw):
        return None
    dims = [d for d in dims_raw if d in CANONICAL_DIMENSIONS]
    if not dims:
        return None

    # Deduplicate while preserving order (schema requires uniqueItems).
    seen: set[str] = set()
    dims_out: list[str] = []
    for d in dims:
        if d not in seen:
            seen.add(d)
            dims_out.append(d)

    focus_raw = raw.get("focus") or {}
    focus: dict[str, str] = {}
    if isinstance(focus_raw, dict):
        for dim, text in focus_raw.items():
            if dim in seen and isinstance(text, str) and text.strip():
                focus[dim] = text.strip()

    return {"dimensions": dims_out, **({"focus": focus} if focus else {})}


def normalize_dimension_sets(raw: Any) -> dict[str, dict[str, Any]]:
    """Normalize an arbitrary dimension_sets value to a clean ``{name: {...}}`` map.

    Malformed entries are dropped (rather than raising) so a hand-edited config
    degrades gracefully while valid entries are preserved.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, raw_set in raw.items():
        if not isinstance(name, str) or not is_valid_set_name(name):
            continue
        normalized = _normalize_set(raw_set)
        if normalized is not None:
            out[name] = normalized
    return out


def suggest_dimension_sets(scan: ScanResult) -> dict[str, dict[str, Any]]:
    """Suggest scope-specific dimension sets based on scan results.

    Prunes the fixed catalog by what the project actually contains. The caller
    (wizard) lets the user confirm/adjust the enabled sets.

    Returns:
        Ordered mapping of scope-name -> normalized set spec. Always includes
        the ``security`` and ``performance`` cross-cutting audits regardless of
        stack; layer-specific sets are added only when detected.
    """
    from iterate_cli.scan import _has_api_layer

    catalog = {
        name: {"dimensions": list(spec["dimensions"])}
        for name, spec in DIMENSION_SET_CATALOG.items()
    }

    if scan.has_frontend:
        if "frontend" not in catalog:
            catalog["frontend"] = {"dimensions": list(DIMENSION_SET_CATALOG["frontend"]["dimensions"])}
    else:
        # Keep frontend-only set out when there is no detected UI layer.
        catalog.pop("frontend", None)

    if _has_api_layer(scan):
        if "api" not in catalog:
            catalog["api"] = {"dimensions": list(DIMENSION_SET_CATALOG["api"]["dimensions"])}
    else:
        catalog.pop("api", None)

    # Cross-cutting audits always offered.
    for name in ("security", "performance", "style-tests"):
        catalog.setdefault(name, {"dimensions": list(DIMENSION_SET_CATALOG[name]["dimensions"])})

    return catalog


def merge_dimension_sets(
    existing: dict[str, dict[str, Any]],
    suggested: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Merge suggested sets into existing, preserving user customisation.

    Existing user sets win (never overwritten by a suggestion); only sets that
    are absent are defaulted from the scan suggestion. Used by refresh so a
    newly-detected layer (e.g. frontend added after onboarding) gets its preset
    without clobbering a manually-configured one.
    """
    out = {name: dict(spec) for name, spec in existing.items()}
    for name, spec in suggested.items():
        out.setdefault(name, dict(spec))
    return out