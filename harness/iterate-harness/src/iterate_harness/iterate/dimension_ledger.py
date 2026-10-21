"""Who attributed what: the ledger's dimension attribution, and the kernel's verdict on it.

Scenario ② asks a compaction hook to compress the history of the dimensions the kernel
already verified before it touches anything else. Ordering that needs two facts, and this
module's whole job is to hand both over *without judging them*:

- PLANNED ids: the published run-plan file when one exists — that file is the contract the
  other harness reads — and the caller's fallback (the effective config's dimensions) when
  there is none. A file that exists but lists nothing is a plan, so ``[]`` and ``None`` are
  different facts and never collapsed.
- RECORDED attribution: the ledger's own entries. A decision whose data carries no valid
  ``dimension`` belongs to no dimension and is not guessed at — the same rule
  :func:`~iterate_harness.iterate.dimension_context.dimension_context_from_evidence` applies
  to evidence packs without the key.

The verdict is the kernel's: :func:`project_dimension_context` only feeds
``dimension_context`` the two halves and returns what it says. A caller that compared
decision counts and concluded "verified" on its own would be re-litigating a judgement this
repo already delegated — which is exactly how the convergence rule was lost the first time.

The shapes are imported, never restated: ``DIMENSION_ID_PATTERN``/``DIMENSION_ID_MAX_LENGTH``
come from the dimension-context contract and ``OPERATION_ID_PATTERN`` from the invariant
report's. A validation rule written twice here would be free to drift from the transcription
that decides whether the value survives into the ledger.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import decision_log, run_plan
from .dimension_context import (
    DIMENSION_E_ID,
    DIMENSION_ID_MAX_LENGTH,
    DIMENSION_ID_PATTERN,
    DimensionContext,
    DimensionContextError,
    dimension_context,
)
from .invariant_report import OPERATION_ID_PATTERN

log = logging.getLogger(__name__)

#: The dimension half already has a kernel code (``KERNEL_E_DIMENSION_ID``); the operation
#: half has none, so it follows the same ``KERNEL_E_*`` shape instead of inventing a
#: harness-private name that the other side would never recognise.
OPERATION_ID_E_CODE = "KERNEL_E_OPERATION_ID"

#: What the ledger's ``data`` payloads call these two facts. The kernel's transcription
#: (``kernel_decision_record``) reads exactly these keys; a writer that uses another name
#: gets a silently unattributed decision.
DIMENSION_DATA_KEY = "dimension"
OPERATION_ID_DATA_KEY = "operationId"


def is_valid_dimension_id(value: object) -> bool:
    """Whether ``value`` is a dimension id the kernel would carry into the ledger draft."""
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= DIMENSION_ID_MAX_LENGTH
        and DIMENSION_ID_PATTERN.match(value) is not None
    )


def is_valid_operation_id(value: object) -> bool:
    """Whether ``value`` is an operation id the kernel would carry into the ledger draft."""
    return isinstance(value, str) and OPERATION_ID_PATTERN.match(value) is not None


def attribution_refusal(
    *, dimension: object, operation_id: object
) -> dict[str, str] | None:
    """The tool-shaped refusal for a malformed attribution, or ``None`` when it validates.

    A typo'd id that the transcription drops is worse than a rejected call: the coverage
    line then reports a dimension as unverified while the run believes it recorded one, so
    the gap reads as measured. Refusing costs the caller nothing it was not already going
    to pay — the decision simply is not written until the attribution is right.

    The messages interpolate the imported pattern and limit rather than restating them, so
    this cannot disagree with the rule it enforces.
    """
    if dimension is not None and not is_valid_dimension_id(dimension):
        return {
            "error": f"{dimension!r} is not a dimension id this ledger can attribute the decision to",
            "code": DIMENSION_E_ID,
            "remedy": (
                f"a dimension id is lower-case kebab-case, at most {DIMENSION_ID_MAX_LENGTH} "
                f"characters and matches {DIMENSION_ID_PATTERN.pattern}; copy it from "
                "config/dimensions.yaml instead of retyping it, and omit the field when this "
                "call served no declared dimension"
            ),
        }
    if operation_id is not None and not is_valid_operation_id(operation_id):
        return {
            "error": f"{operation_id!r} is not an operation id",
            "code": OPERATION_ID_E_CODE,
            "remedy": (
                f"an operation id matches {OPERATION_ID_PATTERN.pattern}; take it from the "
                "engine's own evidence rather than composing one, and omit the field when this "
                "decision is not tied to one operation"
            ),
        }
    return None


def _plan_file(project_root: str | Path) -> Path:
    """The plan path, composed read-only.

    ``run_plan.plan_path`` creates its directory; reading a plan must not leave a ``.iterate``
    behind in a project that never started a run.
    """
    return Path(project_root) / decision_log.LOG_DIR / run_plan.RUN_PLAN_FILENAME


def planned_ids_from_plan_file(path: Path) -> list[str] | None:
    """The ids in the published plan file, or ``None`` when there is none to read."""
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    dimensions = parsed.get("dimensions")
    if not isinstance(dimensions, list):
        return None
    return [
        str(item["id"])
        for item in dimensions
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]


def planned_dimension_ids(
    project_root: str | Path, *, fallback: Sequence[str] | None = None
) -> list[str]:
    """The run's planned dimension ids: the published plan wins over the config fallback."""
    from_file = planned_ids_from_plan_file(_plan_file(project_root))
    return from_file if from_file is not None else [str(item) for item in (fallback or [])]


def _attributed_entries(project_root: str | Path) -> list[tuple[str, str | None]]:
    """``(dimension, operationId)`` per ledger entry that names a valid dimension, in file order.

    An entry naming no valid dimension is skipped rather than guessed at, and an entry that
    names a dimension but no operation id still counts toward that dimension's evidence.
    """
    out: list[tuple[str, str | None]] = []
    for entry in decision_log.read_entries(project_root):
        data: Mapping[str, Any] = entry.data if isinstance(entry.data, dict) else {}
        dimension = data.get(DIMENSION_DATA_KEY)
        if not is_valid_dimension_id(dimension):
            continue
        operation_id = data.get(OPERATION_ID_DATA_KEY)
        out.append(
            (
                str(dimension),
                operation_id if is_valid_operation_id(operation_id) else None,
            )
        )
    return out


def recorded_dimension_counts(project_root: str | Path) -> dict[str, int]:
    """Decisions per attributed dimension — the ``recorded`` half of the kernel's contract."""
    counts: dict[str, int] = {}
    for dimension, _operation_id in _attributed_entries(project_root):
        counts[dimension] = counts.get(dimension, 0) + 1
    return counts


def operation_dimension_map(project_root: str | Path) -> dict[str, str]:
    """Operation id → dimension, as the ledger attributes it.

    Deterministic winner on a collision: an operation id named by more than one decision
    takes the dimension of the LAST such entry in ledger (file) order. The ledger is
    append-only and in decision order, so the most recent attribution is the one the run
    settled on; a tie broken by dict order or by sorting would give two readers of the same
    file different answers.
    """
    mapping: dict[str, str] = {}
    for dimension, operation_id in _attributed_entries(project_root):
        if operation_id is not None:
            mapping[operation_id] = dimension
    return mapping


def project_dimension_context(
    project_root: str | Path, *, fallback: Sequence[str] | None = None
) -> DimensionContext | None:
    """The kernel's verdict for this project, or ``None`` when either half cannot be built.

    ``None`` is the honest answer and it is not the same answer as an all-zero context: a
    caller that ordered compaction on an invented verdict would be clearing evidence the
    kernel never said was verified.
    """
    planned = planned_dimension_ids(project_root, fallback=fallback)
    if not planned:
        return None
    recorded = {
        dimension: {"decisions": count}
        for dimension, count in recorded_dimension_counts(project_root).items()
    }
    try:
        return dimension_context(planned, recorded)
    except DimensionContextError as error:
        # A malformed id on either side is a producer bug; the run keeps working, but this
        # verdict is not printed rather than printed wrong.
        log.warning("iterate dimension coverage could not be computed: %s", error)
        return None
