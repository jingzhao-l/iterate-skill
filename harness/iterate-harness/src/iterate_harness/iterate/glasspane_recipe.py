"""The recipe handoff, and the gate that decides whether a recipe may proceed.

综述 §8.5 row 4 reads "GlassPane 修复完成 → 配方下一步挂接 iterate invariant 复核，通过后才进入重验".
The measured state before this module was that neither half existed: GlassPane's recipe never
reached this harness, and ``reverify_trigger.reverification_targets`` therefore could not name
``recipeSteps`` in a re-verification request (its own docstring said so: "a step is something the
engine's own recipe carries, and this harness has never held one").

What this module does is narrow and mechanical:

* it obtains the recipe from one of two real producers — the operator's ``GLASSPANE_RECIPE``
  (the same hand-off discipline as ``GLASSPANE_RUN_PLAN``), or the path the GlassPane shell
  itself reports for the project (``gp_project_get`` -> ``recipeConfigPath``, which is where
  the daemon's own registry keeps it);
* it validates the document against ``glasspane.recipe/0.1-draft``, which is the contract the
  daemon validates with (``engine/Sources/GlassPaneEngine/RecipeLoader.swift``) and the kernel
  publishes (``kernel/src/recipe-config.ts``);
* it digests the document so a published statement can cite the bytes it was computed from,
  and so a recipe swapped mid-run shows up as a different digest rather than as silence;
* and it answers one question — may the recipe proceed to re-verification? — from three things
  it does not invent: the round's measured invariant verdict, the recipe, and a chain-verified
  ledger line that carries an operation id.

What it will not do. It does not execute a step: GlassPane says of itself that "no recipe
executor exists in this build" (``RecipeLoader.executionNote``), and this harness has no more
right to pretend otherwise. So it never claims to know *which* step the run is on — there is no
progress pointer anywhere in either product to read it from. What it can say, and does, is
whether the recipe may move forward at all, and which steps are on the list, verbatim, with the
digest they were read under. A caller that needs a pointer must produce one in the ledger; the
refusal here says so rather than guessing.

The digest prefix ``rc_`` is local provenance, not a contract field: the kernel defines
``iv_`` (invariant report) and ``rp_`` (run plan) and has no recipe digest, so this value is
cited only in this harness's own payloads and ledger lines. It is computed over the canonical
form of the parsed document, so it is stable across key order and whitespace but *not* across
a reordered ``steps`` array — order is the recipe's meaning, and re-serialising it here would
let two different recipes digest alike.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from .canonical_json import canonical_json
from .kernel_decision_log import DecisionLogEntry, DecisionLogVerification, read_decision_log
from .kernel_decision_record import is_legacy_decision_record

#: The contract version the daemon and the kernel both pin.
RECIPE_SCHEMA_VERSION: Final = "glasspane.recipe/0.1-draft"

#: Limits restated as numbers, not imported from the kernel: the fixture comparison in
#: ``test_glasspane_recipe.py`` is what keeps them honest, exactly as ``run_plan.py`` does it.
RECIPE_NAME_MAX_LENGTH: Final = 256
RECIPE_MIN_STEPS: Final = 1
RECIPE_MAX_STEPS: Final = 64
RECIPE_STEP_KINDS: Final = ("act", "observe", "assert", "diagnose")

RECIPE_DIGEST_PREFIX: Final = "rc_"

#: Where a recipe is handed from, and where the engine keeps its own state. The second one is a
#: refusal, not a search path: a recipe inside ``~/.glasspane`` would make this harness a second
#: writer in a directory it does not own — the projects.json failure, in a new costume.
RECIPE_ENV_VAR: Final = "GLASSPANE_RECIPE"
ENGINE_STATE_ROOTS: Final = (".glasspane",)

#: The foreign ledger's own name. 面 B resolves its decision log through ``GLASSPANE_DECISION_LOG``
#: and writes canonical kernel-chain entries there; reading that same variable is what makes ③'s
#: "same contract" into "one verifiable chain" instead of two files that merely look alike.
FIX_LEDGER_ENV_VAR: Final = "GLASSPANE_DECISION_LOG"

RECIPE_E_PATH: Final = "RECIPE_E_PATH"
RECIPE_E_STATE_ROOT: Final = "RECIPE_E_STATE_ROOT"
RECIPE_E_READ: Final = "RECIPE_E_READ"
RECIPE_E_SCHEMA: Final = "RECIPE_E_SCHEMA"
RECIPE_E_CONTEST: Final = "RECIPE_E_CONTEST"
RECIPE_E_ABSENT: Final = "RECIPE_E_ABSENT"
#: "nobody configured a recipe" and "this host never asked the registry" are different sentences,
#: and a run that publishes the first when the truth is the second has just told its reader that
#: the configuration is empty. Only a host with no channel to ask through can produce this one.
RECIPE_E_NOT_ASKED: Final = "RECIPE_E_NOT_ASKED"
GATE_E_NO_VERDICT: Final = "RECIPE_GATE_E_NO_VERDICT"
GATE_E_GATE: Final = "RECIPE_GATE_E_INVARIANT_GATE"
GATE_E_UNPROVEN: Final = "RECIPE_GATE_E_FIX_UNPROVEN"
GATE_E_LEDGER: Final = "RECIPE_GATE_E_LEDGER_UNVERIFIABLE"

#: Outcomes a fix may be cited under. The kernel's own vocabulary — ``pass|fail|blocked|
#: inconclusive`` — and only ``pass`` proves a fix. A ``blocked`` line is the engine saying it
#: could not judge, which is the opposite of permission to proceed.
FIX_PROVING_OUTCOMES: Final = ("pass",)

_OPERATION_ID_PATTERN = re.compile(r"^op_[0-9A-HJKMNP-TV-Z]{26}$")

#: The tail of the shell's coded-refusal line, ``CODE: message | remedy: R``.
_REFUSAL_MARKER: Final = " | remedy: "


class RecipeError(Exception):
    """A recipe that cannot be located, read, parsed, or honoured — with a code and a remedy."""

    def __init__(self, code: str, message: str, remedy: str, path: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.remedy = remedy
        self.path = path

    def to_payload(self) -> dict[str, object]:
        """The refusal as it is published: code, message, remedy, and the path it is about."""
        out: dict[str, object] = {"code": self.code, "message": self.message, "remedy": self.remedy}
        if self.path is not None:
            out["path"] = self.path
        return out


@dataclass(frozen=True)
class RecipeStep:
    """One step, carried verbatim: the params belong to the tool contracts, not to this module."""

    kind: str
    params: Mapping[str, object]

    def to_json(self) -> dict[str, object]:
        return {"kind": self.kind, "params": dict(self.params)}


@dataclass(frozen=True)
class Recipe:
    """A recipe this harness holds, with the bytes it was read under."""

    path: str
    source: str  # "env" | "shell"
    name: str
    digest: str
    steps: tuple[RecipeStep, ...] = ()

    def step_kinds(self) -> tuple[str, ...]:
        return tuple(step.kind for step in self.steps)

    def targets(self) -> list[dict[str, object]]:
        """The recipe's own steps, for a request's ``targets.recipeSteps``.

        Carried as the recipe spells them. Re-shaping a step here would change the bytes the
        engine is meant to act on, and the whole point of naming steps is that they arrive as
        configured.
        """
        return [step.to_json() for step in self.steps]


@dataclass(frozen=True)
class FixProof:
    """The newest ledger line that says a fix was verified, and where it came from."""

    entry_id: str
    operation_id: str
    outcome: str
    ledger_path: str
    ledger_source: str  # "handed" | "project"
    created_at: str


@dataclass(frozen=True)
class StepGate:
    """The answer to "may the recipe proceed to re-verification?", with what it was read from."""

    allowed: bool
    verdict: str
    recipe_digest: str | None = None
    proof: FixProof | None = None
    refusal: dict[str, object] | None = None
    steps: tuple[str, ...] = field(default_factory=tuple)

    def to_payload(self) -> dict[str, object]:
        """What the round publishes under ``recipeStepGate``.

        Absent rather than null everywhere it applies: a reader must be able to tell "the gate
        said no, here is why" from "nobody asked".
        """
        out: dict[str, object] = {
            "allowed": self.allowed,
            "invariantState": self.verdict,
            "steps": list(self.steps),
        }
        if self.recipe_digest is not None:
            out["recipeDigest"] = self.recipe_digest
        if self.proof is not None:
            out["fixProof"] = {
                "entryId": self.proof.entry_id,
                "operationId": self.proof.operation_id,
                "outcome": self.proof.outcome,
                "ledger": self.proof.ledger_path,
                "ledgerSource": self.proof.ledger_source,
                "createdAt": self.proof.created_at,
            }
        if self.refusal is not None:
            out["refusal"] = self.refusal
        return out


def _code_point_length(value: str) -> int:
    """Length in Unicode scalar values, matching the Swift/TS side (surrogate pairs count once)."""
    return len(value.encode("utf-16-le")) // 2


def recipe_digest(document: Mapping[str, object]) -> str:
    """``rc_`` + sha256 over the document's canonical form."""
    return RECIPE_DIGEST_PREFIX + hashlib.sha256(canonical_json(dict(document)).encode("utf-8")).hexdigest()


def validate_recipe_document(raw: object) -> tuple[str, tuple[RecipeStep, ...], dict[str, object]]:
    """Return ``(name, steps, document)`` or raise :class:`RecipeError`.

    The rules are the contract's, and the order matters only in that a reader who got the
    version wrong should not be told about a step. Unknown keys are refused rather than ignored:
    ``RecipeLoader`` and the kernel schema both say ``additionalProperties: false``, and a
    consumer that tolerated extras would accept a recipe the daemon rejects.
    """
    if not isinstance(raw, Mapping):
        raise RecipeError(
            RECIPE_E_SCHEMA,
            f"a recipe must be a JSON object, got {type(raw).__name__}",
            "the recipe document is `glasspane.recipe/0.1-draft`: {schemaVersion, name, steps}; "
            "emit it as JSON, not YAML or prose",
        )
    if set(raw) != {"schemaVersion", "name", "steps"}:
        extra = sorted(key for key in raw if key not in {"schemaVersion", "name", "steps"})
        missing = sorted(key for key in ("schemaVersion", "name", "steps") if key not in raw)
        raise RecipeError(
            RECIPE_E_SCHEMA,
            f"a recipe carries exactly schemaVersion, name and steps (missing {missing or 'nothing'}, "
            f"unexpected {extra or 'nothing'})",
            "remove the extra keys or add the missing ones; the daemon refuses the same document "
            "with `glasspaned --recipe-validate <path>`",
        )
    version = raw["schemaVersion"]
    if version != RECIPE_SCHEMA_VERSION:
        raise RecipeError(
            RECIPE_E_SCHEMA,
            f"schemaVersion is {version!r}, expected {RECIPE_SCHEMA_VERSION!r}",
            "this build speaks one recipe contract; check it with `glasspaned --recipe-validate <path>`",
            "schemaVersion",
        )
    name = raw["name"]
    if not isinstance(name, str):
        raise RecipeError(RECIPE_E_SCHEMA, f"name must be a string, got {type(name).__name__}", "name the recipe")
    if _code_point_length(name) > RECIPE_NAME_MAX_LENGTH:
        raise RecipeError(
            RECIPE_E_SCHEMA,
            f"name exceeds {RECIPE_NAME_MAX_LENGTH} code points",
            "shorten the recipe name",
        )

    steps_raw = raw["steps"]
    if not isinstance(steps_raw, Sequence) or isinstance(steps_raw, (str, bytes, bytearray)):
        raise RecipeError(
            RECIPE_E_SCHEMA,
            f"steps must be an array of step objects, got {type(steps_raw).__name__}",
            "steps is 1..64 objects of exactly {kind, params}",
        )
    if not RECIPE_MIN_STEPS <= len(steps_raw) <= RECIPE_MAX_STEPS:
        raise RecipeError(
            RECIPE_E_SCHEMA,
            f"{len(steps_raw)} steps is outside the contract's {RECIPE_MIN_STEPS}..{RECIPE_MAX_STEPS}",
            "keep the recipe within 64 steps; a longer sequence is several recipes and should be named as such",
        )

    steps: list[RecipeStep] = []
    for index, item in enumerate(steps_raw):
        if not isinstance(item, Mapping):
            raise RecipeError(
                RECIPE_E_SCHEMA,
                f"steps.{index} must be an object, got {type(item).__name__}",
                "a step is {kind, params}; params is an object even when empty",
                f"steps.{index}",
            )
        if set(item) != {"kind", "params"}:
            raise RecipeError(
                RECIPE_E_SCHEMA,
                f"steps.{index} carries exactly kind and params (unexpected "
                f"{sorted(key for key in item if key not in {'kind', 'params'}) or 'nothing'})",
                "per-step params are validated by the tool contracts, not by an extra key here",
                f"steps.{index}",
            )
        kind = item["kind"]
        if not isinstance(kind, str) or kind not in RECIPE_STEP_KINDS:
            raise RecipeError(
                RECIPE_E_SCHEMA,
                f"steps.{index}.kind is {kind!r}, expected one of {', '.join(RECIPE_STEP_KINDS)}",
                "the engine dispatches on these four kinds; anything else is not a step it can run",
                f"steps.{index}.kind",
            )
        params = item["params"]
        if not isinstance(params, Mapping):
            raise RecipeError(
                RECIPE_E_SCHEMA,
                f"steps.{index}.params must be an object, got {type(params).__name__}",
                "pass {} when the step takes nothing; a null or a string is not a parameter set",
                f"steps.{index}.params",
            )
        steps.append(RecipeStep(kind=kind, params=dict(params)))

    document: dict[str, object] = {
        "schemaVersion": RECIPE_SCHEMA_VERSION,
        "name": name,
        "steps": [step.to_json() for step in steps],
    }
    return name, tuple(steps), document


def parse_recipe_text(text: str, path: str | None = None) -> tuple[str, tuple[RecipeStep, ...], dict[str, object]]:
    """Parse then validate; a file that is not JSON is refused as a schema problem, not a crash."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise RecipeError(
            RECIPE_E_READ,
            f"{path or 'the recipe'} is not valid JSON ({error.msg} at line {error.lineno})",
            "the recipe document is JSON; write it with json.dump, and re-check it with "
            "`glasspaned --recipe-validate <path>`",
            path,
        ) from error
    return validate_recipe_document(raw)


def _reject_engine_root(target: Path) -> None:
    if any(part in ENGINE_STATE_ROOTS for part in target.parts):
        raise RecipeError(
            RECIPE_E_STATE_ROOT,
            f"{target} is inside an engine state root",
            "choose a directory whoever configures the run owns; the engine owns ~/.glasspane",
            str(target),
        )


def read_recipe(
    *,
    env: Mapping[str, str] | None = None,
    shell_reported_path: str | None = None,
) -> Recipe | None:
    """Locate and validate the recipe this run is configured with, or raise :class:`RecipeError`.

    Two producers, both of them real, and they must agree. ``GLASSPANE_RECIPE`` is what the
    operator handed over; ``shell_reported_path`` is what the GlassPane registry says the project
    uses. When both exist and differ, neither wins: the run refuses, because a recipe chosen by
    tie-break is a recipe nobody configured.

    ``None`` means *nobody declared a recipe at all* — which is not a failure of this module. The
    caller turns it into :data:`RECIPE_E_ABSENT` when the gate needs a recipe, so the round says
    what is missing instead of this function inventing one.
    """
    environment: Mapping[str, str] = os.environ if env is None else env
    handed = environment.get(RECIPE_ENV_VAR)
    candidates: list[tuple[str, str]] = []
    if isinstance(handed, str) and handed.strip():
        candidates.append(("env", handed.strip()))
    if isinstance(shell_reported_path, str) and shell_reported_path.strip():
        candidates.append(("shell", shell_reported_path.strip()))
    if not candidates:
        return None

    for source, value in candidates:
        if not value.startswith("/"):
            raise RecipeError(
                RECIPE_E_PATH,
                f"the recipe path from {source} is not absolute: {value!r}",
                "point it at an absolute path; a relative one lands wherever the agent happened "
                "to be, which is not the recipe anyone configured",
                value,
            )
    if len(candidates) == 2 and candidates[0][1] != candidates[1][1]:
        raise RecipeError(
            RECIPE_E_CONTEST,
            f"{RECIPE_ENV_VAR}={candidates[0][1]!r} but the GlassPane registry says "
            f"{candidates[1][1]!r} for this project",
            "one of the two is stale: point the environment variable at the recipe the project "
            "actually uses, or unset it so the registry answers alone",
            candidates[0][1],
        )

    source, value = candidates[0]
    target = Path(value).resolve()
    _reject_engine_root(target)
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise RecipeError(
            RECIPE_E_READ,
            f"no recipe at {target} (declared by {source})",
            "write the recipe before the session starts, or unset the declaration so the round "
            "says the recipe is absent instead of half-read",
            str(target),
        ) from error
    except (OSError, UnicodeDecodeError) as error:
        raise RecipeError(
            RECIPE_E_READ,
            f"cannot read the recipe at {target}: {error}",
            "this file decides whether a run may proceed; repair access to it rather than "
            "deleting or replacing it",
            str(target),
        ) from error

    name, steps, document = parse_recipe_text(text, str(target))
    return Recipe(
        path=str(target),
        source=source,
        name=name,
        digest=recipe_digest(document),
        steps=steps,
    )


@dataclass(frozen=True)
class RecipeRead:
    """The outcome of one recipe hand-off: a held recipe, or the named reason there is not one.

    Carried as a value rather than raised because the round publishes both cases. A caller that
    had to catch an exception to learn "no recipe was configured" tends to publish nothing, which
    is the silence this whole module was written to replace.

    ``registry_asked`` separates the two kinds of nothing-on-file: an env-only host that never
    reached ``gp_project_list`` has not established that no recipe is configured, and saying so
    would be a claim about somebody else's registry.
    """

    recipe: Recipe | None = None
    refusal: RecipeError | None = None
    registry_asked: bool = True

    @property
    def held(self) -> bool:
        return self.recipe is not None


def read_recipe_or_refusal(
    *,
    env: Mapping[str, str] | None = None,
    shell_reported_path: str | None = None,
    registry_asked: bool = True,
) -> RecipeRead:
    """:func:`read_recipe` as a value: the refusal travels instead of being caught at the call site.

    A path the registry reported and a path the registry *could not* report are not the same
    argument: ``shell_reported_path`` arrives already decoded by the caller, so a decode failure
    is handed here as :data:`RECIPE_E_READ` inside ``refusal`` rather than being flattened into
    "the registry said there is nothing".
    """
    if not registry_asked and shell_reported_path is None:
        environment: Mapping[str, str] = os.environ if env is None else env
        if not (environment.get(RECIPE_ENV_VAR) or "").strip():
            return RecipeRead(
                registry_asked=False,
                refusal=RecipeError(
                    RECIPE_E_NOT_ASKED,
                    f"this host handed no recipe through {RECIPE_ENV_VAR} and had no channel to "
                    "ask the GlassPane registry over, so nothing was learned about the recipe",
                    "bind the re-verification transport (glasspane_host_transport binds both "
                    f"shapes at the publish site), or set {RECIPE_ENV_VAR} to the absolute path "
                    "of the recipe this run is under",
                ),
            )
    try:
        return RecipeRead(
            recipe=read_recipe(env=env, shell_reported_path=shell_reported_path),
            registry_asked=registry_asked,
        )
    except RecipeError as error:
        return RecipeRead(refusal=error, registry_asked=registry_asked)


def recipe_path_from_project_list(raw: object) -> str | None:
    """The one project path the GlassPane registry reports as its recipe, or ``None``.

    ``gp_project_list`` answers with one text item holding ``{"projects": [...]}`` — the shell's
    own ``canonicalJson`` of the registry file (``mcp-shell/src/tools.ts:projectListTool``). Items
    are walked one at a time and never joined: the shipped shell sends the frame *plus* other
    items, and a join destroys the boundary that makes an extra item readable as an extra item
    rather than as part of the answer.

    Zero configured recipes is ``None`` — a stated absence the caller turns into
    :data:`RECIPE_E_ABSENT`. Two or more *different* paths is a refusal, not a pick: which project
    a run belongs to is not something this module gets to decide by iteration order. A reply that
    is not the documented frame is also a refusal, because reading "I did not understand" as
    "there is no recipe" would be a silent downgrade of a transport failure into a configuration
    statement.
    """
    items: list[object]
    if isinstance(raw, (str, Mapping)):
        items = [raw]
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        items = list(raw)
    else:
        raise RecipeError(
            RECIPE_E_READ,
            f"the registry read answered with something that is not a content item: {type(raw).__name__}",
            "the channel must return one entry per MCP content item "
            "(McpClientManager.call_tool_parts); a reply of another shape cannot be read as a "
            "project list",
        )

    projects: list[object] | None = None
    refusals: list[str] = []
    for item in items:
        payload: object = item
        if isinstance(payload, str):
            # The shell's refusal line is `CODE: message | remedy: R` (mcp-shell/src/errors.ts),
            # recognised here by its structure rather than by a re-typed pattern: a re-typed regex
            # would be a second opinion about what a refusal looks like.
            if _REFUSAL_MARKER in payload:
                refusals.append(payload)
                continue
            try:
                payload = json.loads(payload)
            except ValueError:
                continue
        if isinstance(payload, Mapping) and isinstance(payload.get("projects"), list):
            projects = list(payload["projects"])
            break

    if projects is None:
        if refusals:
            raise RecipeError(
                RECIPE_E_READ,
                f"the registry read refused rather than listing projects: {refusals[0]}",
                "the refusal is the shell's own; clear it (a registry file the service cannot "
                "read is the usual cause) before the run claims a recipe it never read",
            )
        raise RecipeError(
            RECIPE_E_READ,
            "the registry read carried no {projects: [...]} frame, so nothing was learned about "
            "the configured recipe",
            "check that the server answering this call is glasspane-mcp: an unrelated MCP server "
            "will happily answer with something else entirely",
        )

    found: list[str] = []
    for entry in projects:
        if not isinstance(entry, Mapping):
            continue
        value = entry.get("recipeConfigPath")
        if isinstance(value, str) and value.strip() and value.strip() not in found:
            found.append(value.strip())
    if not found:
        return None
    if len(found) > 1:
        raise RecipeError(
            RECIPE_E_CONTEST,
            "the GlassPane registry lists "
            f"{len(found)} different recipe paths ({', '.join(found)}), and a run has no way to "
            "tell which project it is reviewing",
            f"set exactly one project's recipeConfigPath, or hand this run the one it means "
            f"through {RECIPE_ENV_VAR} — the environment wins only when it agrees with the "
            "registry, which is what the contest check above enforces",
        )
    return found[0]


def _entry_proves_fix(entry: DecisionLogEntry) -> bool:
    if entry.outcome not in FIX_PROVING_OUTCOMES:
        return False
    operation_id = entry.operation_id
    return isinstance(operation_id, str) and bool(_OPERATION_ID_PATTERN.match(operation_id))


def _broken_ledger_remedy(path_str: str, verified: DecisionLogVerification) -> str:
    """Say which kind of unreadable ledger this is, because the two have different fixes.

    A line in the pre-chain shape is not tampering — it is history the write side has not yet
    migrated, and telling the operator to "investigate the broken link" would send them looking for
    a corruption that is not there. Everything else is treated as what it says: a chain that stops.
    """
    if verified.first_broken_line is not None:
        try:
            raw = Path(path_str).read_text(encoding="utf-8").split("\n")[verified.first_broken_line - 1]
            decoded = json.loads(raw)
        except (OSError, ValueError, IndexError):
            decoded = None
        if is_legacy_decision_record(decoded):
            return (
                "that line predates the kernel chain — it is the old {timestamp, round, type, data} "
                "shape, and it carries nothing this gate could verify. The write side migrates on the "
                f"next append; cite a fix from a chained line, or hand this run a chained ledger "
                f"through {FIX_LEDGER_ENV_VAR}"
            )
    return (
        "a fix claim cited from a broken chain proves nothing: preserve the file and investigate "
        "the broken link, or point the run at the ledger that holds the chain"
    )


def fix_proof(
    project_root: Path | str,
    env: Mapping[str, str] | None = None,
) -> FixProof:
    """The newest chain-verified ledger line that proves a fix, or a refusal saying why there is none.

    This is ③ doing real work: the ledger is read through the kernel's chain verifier, and it may
    be a ledger *the other harness wrote* (``GLASSPANE_DECISION_LOG``), which is the only way
    "opID ↔ decision 条目哈希链互通" is more than two files that share a format.

    A broken chain is a refusal, never a fallback to the lenient reader. ``decision_log.read_entries``
    deliberately skips unparseable lines because it answers "what did the loop decide"; this
    question is "is this claim verifiable", and a line that does not verify cannot license a run.
    """
    environment: Mapping[str, str] = os.environ if env is None else env
    handed = environment.get(FIX_LEDGER_ENV_VAR)
    if isinstance(handed, str) and handed.strip():
        ledger_path = Path(handed.strip())
        source = "handed"
        if not ledger_path.is_absolute():
            raise RecipeError(
                RECIPE_E_PATH,
                f"{FIX_LEDGER_ENV_VAR}={str(ledger_path)!r} is not absolute",
                "point it at an absolute path to the ledger (the same rule 面 B applies when it "
                "resolves its own decision log)",
                str(ledger_path),
            )
        _reject_engine_root(ledger_path)
    else:
        ledger_path = Path(project_root) / ".iterate" / "decision-log.jsonl"
        source = "project"

    path_str = str(ledger_path)
    try:
        verified = read_decision_log(path_str)
    except (OSError, ValueError) as error:  # read_decision_log raises for an unusable location
        raise RecipeError(
            GATE_E_LEDGER,
            f"the ledger at {path_str} could not be read for verification: {error}",
            "fix the permissions or ownership; this is evidence, so repair access rather than "
            "deleting the file",
            path_str,
        ) from error
    if not verified.ok:
        raise RecipeError(
            GATE_E_LEDGER,
            f"the ledger at {path_str} stops being trustworthy at line "
            f"{verified.first_broken_line} ({verified.broken_kind}: {verified.reason})",
            _broken_ledger_remedy(path_str, verified),
            path_str,
        )
    for entry in reversed(verified.entries):
        if _entry_proves_fix(entry):
            return FixProof(
                entry_id=entry.entry_id,
                operation_id=str(entry.operation_id),
                outcome=entry.outcome,
                ledger_path=path_str,
                ledger_source=source,
                created_at=entry.created_at,
            )
    raise RecipeError(
        GATE_E_UNPROVEN,
        f"no verified ledger line in {path_str} records a passing outcome for an operation id",
        "the claim to re-verify has to be a claim something recorded: run the engine call that "
        "produces the evidence pack and let the write side append its chain entry, or hand this "
        f"run the ledger that already holds it through {FIX_LEDGER_ENV_VAR}",
        path_str,
    )


def recipe_step_gate(
    *,
    project_root: Path | str,
    invariant_verdict: object,
    read: RecipeRead,
    env: Mapping[str, str] | None = None,
) -> StepGate:
    """May the recipe proceed to re-verification? Answered from three measured things, in one order.

    1. **The verdict first, and only a measured one counts.** ``pass`` is the only verdict that
       lets the recipe move. ``unmeasured`` — no commands declared, or all refused before running —
       is not a pass, and neither is an absent gate: a loop that never checked anything may not
       converge on the strength of a verdict nobody produced.
    2. **Then the recipe.** Without it there is nothing that *has* a next step, and the answer is
       the absence stated, not a guess about what the project probably runs.
    3. **Then the fix.** "The fix is done" is only a fact if a chain-verified ledger line says so;
       that read is also what makes the two products' ledgers one verifiable chain rather than two
       files in the same format.

    The caller resolves the hand-off and passes it in as :class:`RecipeRead`, because answering
    "what does the registry say" may need an await while this function does not own a loop.

    Nothing here decides whether the GUI claim is true. That stays 100% in the Swift engine — this
    gate only decides whether the run is allowed to ask.
    """
    verdict = invariant_verdict if isinstance(invariant_verdict, str) and invariant_verdict else "absent"
    if verdict == "absent":
        return StepGate(
            allowed=False,
            verdict=verdict,
            refusal=RecipeError(
                GATE_E_NO_VERDICT,
                "this round published no invariant verdict, so there is nothing to grant",
                "run the round with the defensive kernel wired in, or read the gate as unmeasured "
                "and say so — an absent gate is not a passed one",
            ).to_payload(),
        )
    if verdict != "pass":
        return StepGate(
            allowed=False,
            verdict=verdict,
            refusal=RecipeError(
                GATE_E_GATE,
                f"the invariant re-check reported {verdict!r}, so the recipe may not proceed to "
                "re-verification",
                "a failed re-check is answered by the failing checks themselves: clear them, or "
                "let the re-verification request this report already earns name what to re-run. "
                "Proceeding past a failed gate is the lie this function exists to stop",
            ).to_payload(),
        )

    if read.refusal is not None:
        return StepGate(allowed=False, verdict=verdict, refusal=read.refusal.to_payload())
    recipe = read.recipe
    if recipe is None:
        return StepGate(
            allowed=False,
            verdict=verdict,
            refusal=RecipeError(
                RECIPE_E_ABSENT,
                f"neither {RECIPE_ENV_VAR} nor the GlassPane registry named a recipe for this "
                "project, so there is no next step to gate",
                "set the project's recipeConfigPath (面 A: gp_project_set) or hand the run a "
                f"recipe through {RECIPE_ENV_VAR}; a recipe nobody configured cannot be 'passed'",
            ).to_payload(),
        )

    try:
        proof = fix_proof(project_root, env=env)
    except RecipeError as error:
        return StepGate(
            allowed=False,
            verdict=verdict,
            recipe_digest=recipe.digest,
            steps=recipe.step_kinds(),
            refusal=error.to_payload(),
        )
    return StepGate(
        allowed=True,
        verdict=verdict,
        recipe_digest=recipe.digest,
        proof=proof,
        steps=recipe.step_kinds(),
    )


__all__ = [
    "FIX_LEDGER_ENV_VAR",
    "GATE_E_GATE",
    "GATE_E_LEDGER",
    "GATE_E_NO_VERDICT",
    "GATE_E_UNPROVEN",
    "RECIPE_E_ABSENT",
    "RECIPE_E_CONTEST",
    "RECIPE_E_NOT_ASKED",
    "RECIPE_E_PATH",
    "RECIPE_E_READ",
    "RECIPE_E_SCHEMA",
    "RECIPE_E_STATE_ROOT",
    "RECIPE_MAX_STEPS",
    "RECIPE_MIN_STEPS",
    "RECIPE_NAME_MAX_LENGTH",
    "RECIPE_SCHEMA_VERSION",
    "RECIPE_STEP_KINDS",
    "Recipe",
    "RecipeError",
    "RecipeRead",
    "RecipeStep",
    "StepGate",
    "fix_proof",
    "parse_recipe_text",
    "read_recipe",
    "read_recipe_or_refusal",
    "recipe_digest",
    "recipe_path_from_project_list",
    "recipe_step_gate",
    "validate_recipe_document",
]
