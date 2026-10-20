"""The trigger half of scenario ①: an invariant failure asks the engine again.

``iterate/glasspane_reverification.py`` can already send an ``iterate.reverification/0.1``
request and relay whatever the engine said; until this module nothing in the loop ever handed
it one. This is that missing hand-off, and it is deliberately the *only* place the decision is
made, because every other candidate site would have to invent a fact to do the same job:

- ``loop_policy.IterateLoopPolicy`` is consulted at the round boundary, but it only ever sees
  the *already-relayed* verdict string inside the published ``iterate_state`` — never the
  invariant report the request's ``trigger.reportDigest`` is a citation *of*. Building a request
  there would mean re-deriving a report nobody handed it, i.e. minting a digest for a run it
  cannot see. It also has no project root, which is where the ledger and the recorded
  operations live.
- ``engine/query.py`` could reach both, but it deliberately does not own iterate semantics
  (it merges tool metadata and explicitly refuses to carry the defensive kernel across turns:
  ``DEFENSIVE_KERNEL_KEY`` is skipped when tool metadata is folded back).

What remains is the round's publish site — the ``iterate_review`` aggregate call, where
``loop_gates.measured_gates`` has just *measured* the invariant verdict from the defensive
kernel in the tool metadata, where the round's state object is about to be published, and where
the run's ledger has its root. This module takes those three things and adds nothing to them.

THE RULES THIS MODULE IS BOUND BY (all of them pre-existing, restated here because this is the
site where they can actually be broken):

1. **No verdict, no words.** When the round published no ``invariant_state`` gate, this returns
   ``None`` and the caller publishes nothing. Not a ``False``, not an empty run, not a
   "nothing to re-verify" line: the loop did not measure anything, so it may not say anything.
2. **The judgement is not ours.** Whether the engine's answers add up to anything is read out of
   :attr:`ReverificationRun.any_verified` / ``all_clean`` and relayed. Nothing here compares
   counts, inspects outcomes, or decides that a failure is now cleared.
3. **A gate never becomes measured on the strength of a re-verification.** This module writes
   into no gate key; a missing/unreachable/refusing engine leaves the round's gates exactly as
   ``loop_gates`` produced them (see its docstring on why absent beats a default).
4. **A refusal is relayed, never re-decoded** — the contract's ``InvariantReportError`` and the
   engine's coded refusals travel with their code/message/remedy intact.
5. **The transport is the host's, and its absence is stated.** The harness's own MCP client
   (``McpClientManager``) is async; ``run_reverification`` is the synchronous sender and the
   module it lives in refuses an awaitable with ``GP_E_ASYNC_HOST`` rather than filing a
   coroutine as an answer. So the host must hand over a *synchronous* read-only transport under
   :data:`GLASSPANE_TRANSPORT_KEY`; when it has not, the send is recorded as not-attempted —
   which is a stated state, not a silence. The transport's reply shape is the engine's own
   boundary: prefer ``McpClientManager.call_tool_parts``, whose ``list[str]`` keeps one entry
   per content item (the shipped ``gp_diagnose`` answers with the daemon frame *plus* an
   ``update state:`` block *plus* a ``provider:`` line, and relaying that as a joined string
   measured ``unparseable``); a transport that hands back a plain ``str`` still works, it just
   keeps only the single-item and already-parsed shapes. :func:`relay_answer` classifies per
   item and keeps the side items verbatim as annotations.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .decision_log import DECISION_LOG_REFUSALS, append_entry, make_entry, read_entries
from .glasspane_reverification import RelayedAnswer, ReverificationRun, run_reverification
from .invariant_report import (
    OPERATION_ID_PATTERN,
    InvariantReportError,
    from_defensive_report,
    re_verification_request_from_targets,
)
from .loop_gates import GATE_KEYS

log = logging.getLogger(__name__)

#: The gate this trigger keys on, read from the producer's own key list: a trigger that
#: re-spelled ``invariant_state`` by hand would be a second contract that can drift.
INVARIANT_GATE_KEY = GATE_KEYS[0]

#: Where the round's answer is published inside ``iterate_state`` (and therefore survives the
#: compaction attachment, which reads that same dict).
REVERIFICATION_STATE_KEY = "reverification"

#: Metadata key a host uses to hand this loop a **synchronous** GlassPane transport, called as
#: ``call_tool(tool_name, arguments) -> the engine's reply`` — either the boundary-preserving
#: ``list[str]`` of content items (``McpClientManager.call_tool_parts``, what the shipped shell
#: actually sends) or a plain ``str`` for a host that has only the joined view. Absent (or not
#: callable) is not an error: it is recorded as a send that was never attempted.
GLASSPANE_TRANSPORT_KEY = "glasspane_reverify_transport"

#: The ledger kind this decision is filed under. Shape-checked by the kernel, not by a list.
LEDGER_DECISION_TYPE = "decision"
LEDGER_DATA_KIND = "reverification"

#: How many recorded operations one round re-asks. The cap is the ledger's own: one entry has to
#: carry the citation of every answer it relays under ``PAYLOAD_MAX_CANONICAL_LENGTH``, and
#: asking without saying so is the lie — the remainder is counted in the published payload.
MAX_REQUESTED_OPERATIONS = 4


def _sync_transport(metadata: Mapping[str, Any] | None) -> Callable[[str, dict[str, Any]], object] | None:
    """The host's synchronous transport, or ``None`` when the host has not provided one.

    A transport may answer with ``list[str]`` (one entry per MCP content item, the
    shape ``McpClientManager.call_tool_parts`` preserves) or with a plain ``str``;
    :func:`.glasspane_reverification.relay_answer` classifies both, per item where
    there are items. The missing-verdict rule is the caller's and is unchanged: when
    the round measured no invariant verdict this trigger says nothing and publishes
    nothing.
    """
    candidate = (metadata or {}).get(GLASSPANE_TRANSPORT_KEY)
    return candidate if callable(candidate) else None


def _copied_mapping(value: object) -> dict[str, Any]:
    """A JSON-safe copy of one contract sub-object, or ``{}`` when it is not a mapping.

    The request is the kernel's own frame; relaying it means carrying its keys, not re-shaping
    them, and a copy keeps the published payload from aliasing the request the sender read.
    """
    return dict(value) if isinstance(value, Mapping) else {}


def recorded_operation_ids(project_root: Path | str) -> list[str]:
    """Operation ids the run actually recorded, newest first, deduplicated.

    The ledger is the only place this harness can cite an engine operation from: an id typed
    here, or read off a report the reviewer self-declared, would be a claim about the engine
    that nothing measured.
    """
    ids: list[str] = []
    for entry in read_entries(project_root):
        data = entry.data if isinstance(entry.data, Mapping) else {}
        value = data.get("operationId")
        if isinstance(value, str) and OPERATION_ID_PATTERN.match(value) and value not in ids:
            ids.append(value)
    return list(reversed(ids))


def reverification_targets(
    project_root: Path | str,
    planned_dimensions: Sequence[str] = (),
) -> tuple[dict[str, object], int]:
    """The targets this round may honestly name, plus how many ids it could not ask about.

    ``recipeSteps`` are not produced here: a step is something the engine's own recipe carries,
    and this harness has never held one. Dimensions come from the report the reviewer aggregated,
    so the list is what this run planned rather than what a config once said.
    """
    recorded = recorded_operation_ids(project_root)
    asked = recorded[:MAX_REQUESTED_OPERATIONS]
    targets: dict[str, object] = {}
    if asked:
        targets["operationIds"] = list(asked)
    dimensions = [str(dimension) for dimension in planned_dimensions if str(dimension).strip()]
    if dimensions:
        targets["dimensions"] = dimensions
    return targets, max(0, len(recorded) - len(asked))


def _relay_answer(answer: RelayedAnswer, *, full: bool) -> dict[str, Any]:
    """One engine answer, in the engine's own words — including the refusal fields verbatim."""
    relayed: dict[str, Any] = {
        "tool": answer.tool,
        "state": answer.state,
        "operationId": answer.operation_id,
        "code": answer.code,
        # Provenance, not a verdict: which registered AE method licensed this reading.
        "method": answer.method,
    }
    # Side items are cited verbatim where they exist; an empty tuple adds nothing, so the
    # payload of a single-item answer keeps the byte length it had before multi-item relay.
    if answer.annotations:
        relayed["annotations"] = list(answer.annotations)
    if full:
        relayed["arguments"] = dict(answer.arguments)
        relayed["outcome"] = answer.outcome
        relayed["summary"] = answer.summary
        relayed["message"] = answer.message
        relayed["remedy"] = answer.remedy
    return relayed


def _refusal_payload(error: InvariantReportError, verdict: str) -> dict[str, Any]:
    """A contract refusal, relayed: the loop did not send, and says which rule stopped it."""
    return {
        "spawned": False,
        "invariantState": verdict,
        "refusal": {"code": error.code, "message": error.message, "remedy": error.remedy},
    }


def record_reverification_run(
    project_root: Path | str,
    round_number: int,
    request: Mapping[str, object],
    run: ReverificationRun,
) -> str | None:
    """Append the one ledger entry this send earns; return the refusal text, never raise.

    Mirrors ``tools/iterate_tools._publish_run_plan``: a ledger that will not take the entry does
    not cancel the send (the engine already answered), and it does not get swallowed either —
    the caller puts the returned text into the round's payload.
    """
    data: dict[str, object] = {
        "kind": LEDGER_DATA_KIND,
        "summary": f"re-verification of {run.request_digest}: attempted={run.attempted}",
        "schemaVersion": request.get("schemaVersion"),
        "trigger": _copied_mapping(request.get("trigger")),
        "targets": _copied_mapping(request.get("targets")),
        "digest": run.request_digest,
        "attempted": run.attempted,
        # Relayed from the run's own judgement properties; this module computes nothing.
        "verified": run.any_verified,
        "clean": run.all_clean,
        "answers": [_relay_answer(answer, full=False) for answer in run.answers],
    }
    if run.not_attempted_reason is not None:
        data["notAttemptedReason"] = run.not_attempted_reason
    try:
        append_entry(
            project_root,
            make_entry(
                entry_type=LEDGER_DECISION_TYPE,
                round_number=round_number,
                data=data,
            ),
        )
    except (OSError, *DECISION_LOG_REFUSALS) as error:
        log.warning("iterate re-verification decision could not be logged: %s", error, exc_info=True)
        return f"{getattr(error, 'code', type(error).__name__)}: {error}"
    return None


def trigger_reverification(
    *,
    project_root: Path | str,
    metadata: Mapping[str, Any] | None,
    gates: Mapping[str, object],
    round_number: int,
    planned_dimensions: Sequence[str] = (),
) -> dict[str, Any] | None:
    """Send the failing invariant's re-verification, or state why nothing was sent.

    Returns ``None`` when the round measured no invariant verdict at all — the caller then
    publishes nothing, which is the difference between "not needed" and "not known". Otherwise a
    JSON-safe payload for the round's ``iterate_state`` and the tool output.
    """
    verdict = gates.get(INVARIANT_GATE_KEY)
    if not isinstance(verdict, str) or not verdict:
        return None

    from ..defensive.kernel import DEFENSIVE_KERNEL_KEY

    kernel = (metadata or {}).get(DEFENSIVE_KERNEL_KEY)
    report = getattr(kernel, "last_invariant_report", None)
    if report is None:
        # A verdict with no report behind it is a producer bug, and the honest answer about our
        # own action is "nothing was asked": no request, no ledger line, no published key.
        log.warning("iterate invariant gate %r carries no report; no re-verification was sent", verdict)
        return None

    ensure = getattr(kernel, "invariant_ensure", None)
    commands = getattr(kernel, "invariant_commands", None)
    if ensure is None or commands is None:
        return _refusal_payload(
            InvariantReportError(
                "INVARIANT_REPORT_E_CONFIGURED",
                f"the invariant verdict {verdict!r} came from a kernel that does not name the "
                "checks it ran",
                "the request's digest is a citation of the report, and the report has to carry "
                "every configured check; expose the runner's own ensure list and command map "
                "(defensive.kernel.DefensiveKernel.invariant_ensure / invariant_commands) "
                "instead of letting the loop guess them",
                "checks",
            ),
            verdict,
        )

    try:
        contract_report = from_defensive_report(list(ensure), dict(commands), report)
    except InvariantReportError as error:
        return _refusal_payload(error, verdict)

    targets, not_asked = reverification_targets(project_root, planned_dimensions)
    try:
        request = re_verification_request_from_targets(contract_report, targets)
    except InvariantReportError as error:
        return _refusal_payload(error, verdict)
    if request is None:
        # The kernel's own rule: a passing report earns no request. Nothing is sent, and the
        # round records that it sent nothing because nothing was broken.
        return {
            "spawned": False,
            "invariantState": verdict,
            "reason": "the invariant report passed; the kernel builds no re-verification request",
        }

    run = run_reverification(request, _sync_transport(metadata))
    payload: dict[str, Any] = {
        "spawned": True,
        "invariantState": verdict,
        "schemaVersion": request["schemaVersion"],
        "trigger": _copied_mapping(request["trigger"]),
        "targets": _copied_mapping(request["targets"]),
        "digest": run.request_digest,
        "attempted": run.attempted,
        "notAttemptedReason": run.not_attempted_reason,
        # Judgement relayed from the run, never recomputed here.
        "verified": run.any_verified,
        "clean": run.all_clean,
        "answers": [_relay_answer(answer, full=True) for answer in run.answers],
        "deferred": [
            {"kind": target.kind, "detail": target.detail, "reason": target.reason}
            for target in run.deferred
        ],
        "lines": run.to_model_lines(),
    }
    if not_asked:
        payload["operationIdsNotRequested"] = not_asked
    ledger_error = record_reverification_run(project_root, round_number, request, run)
    if ledger_error is not None:
        payload["ledgerError"] = ledger_error
    return payload


__all__ = [
    "GLASSPANE_TRANSPORT_KEY",
    "INVARIANT_GATE_KEY",
    "MAX_REQUESTED_OPERATIONS",
    "REVERIFICATION_STATE_KEY",
    "record_reverification_run",
    "recorded_operation_ids",
    "reverification_targets",
    "trigger_reverification",
]
