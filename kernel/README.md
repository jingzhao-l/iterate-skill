# iterate-kernel

The iterate ecosystem's shared semantic kernel: schemas, the evidence → decision
transcription, the decision-log audit chain, and public validators.

**What it is not.** It carries no verification reasoning. Judging whether a claim is true
belongs to the engine that produced the evidence; this package transcribes what that engine
already decided, so that every shell in the ecosystem speaks the same language instead of
each inventing its own.

## Install

```bash
npm install iterate-kernel
```

## Import per module, not through the barrel

```ts
import { decisionOutcomeFromEvidence } from "iterate-kernel/evidence-decision"
import { appendDecisionEntry } from "iterate-kernel/decision-log"
import { parseEvidencePack } from "iterate-kernel/parse"
```

Each module is its own subpath export. Importing the barrel (`iterate-kernel`) also pulls
in `schemas`, which reads the JSON Schema files next to the package at load time — fine in a
repository, but a runtime file read is a trap for anyone bundling to a single file. The
subpaths avoid it, and they keep a consumer's dependency on this package as narrow as the
APIs it actually uses.

## The pieces

| Module | What it is for |
| --- | --- |
| `evidence-pack` / `parse` | the evidence pack shape, and parsing/validating one |
| `evidence-decision` | the **transcription**: evidence (attribution level, circuit-breaker level, pass/fail/inconclusive) → a decision outcome and a human summary. It reads fields the engine already decided; it never infers. |
| `decision-log-entry` / `decision-log` | the append-only decision-log entry and the `opID ↔ entry` hash chain that makes it auditable |
| `dimension-context` / `parse` | the dimension-coverage transcription: a plan plus what the engine actually recorded → verified / unverified / unplanned, and one line to put in a summary. It validates id *shape*, never which ids exist — that list belongs to whoever configured the run. |
| `errors` / `schemas` / `canonical-json` / `recipe-config` | `KernelSchemaError`, the JSON Schemas, canonical serialisation, recipe validation |

## A runnable example

This is the whole surface in one file, and it is the shape the API actually wants. Two details
cost real time to discover, so they are written out here rather than left to the error messages:

- **the ledger path is a first argument, not a field.** There is no default location, on purpose:
  a durable audit chain should not be created wherever a process happened to start.
- **`entryId` and `createdAt` are yours to supply** (`sequence` and `prevEntryHash` are derived
  from the ledger and must *not* be sent). `newDecisionEntryId()` mints one in the required
  `dl_<26 Crockford>` form.

```ts
import { decisionOutcomeFromEvidence, decisionSummaryFromEvidence } from "iterate-kernel/evidence-decision"
import { appendDecisionLogEntry, newDecisionEntryId } from "iterate-kernel/decision-log"
import { parseEvidencePack, parseDimensionContextInput } from "iterate-kernel/parse"
import { dimensionContext, formatDimensionContext } from "iterate-kernel/dimension-context"
import { resolve } from "node:path"

const pack = parseEvidencePack(await readFile("evidence.json", "utf8").then(JSON.parse))
const outcome = decisionOutcomeFromEvidence(pack)

// the transcription — never an inference; it reads what the engine already decided
console.log(outcome, decisionSummaryFromEvidence(pack))

// the audit chain — refuses to append onto a tail it cannot re-hash
appendDecisionLogEntry(resolve("ledger.jsonl"), {
  entryId: newDecisionEntryId(),
  createdAt: new Date().toISOString(),
  operationId: pack.operationId,
  outcome,
  summary: decisionSummaryFromEvidence(pack),
})

// dimension coverage — `recorded` is what the engine logged, not what you hoped it would
const input = parseDimensionContextInput({
  planned: [{ id: "correctness" }, { id: "security" }, { id: "ui-ux" }],
  recorded: { security: { decisions: 3, operationIds: [pack.operationId] } },
})
// -> "1/3 dimensions verified, 2 unverified (correctness, ui-ux), 3 decisions"
console.log(formatDimensionContext(dimensionContext(input)))
```

`parseDimensionContextInput` returns the *validated input*; `dimensionContext` computes the
context; `formatDimensionContext` renders the line. Anything recorded but never planned shows up
as `unplanned` — a reporter that quietly dropped it would be the failure this exists to prevent.

## Versioning

`0.1.x` is pre-stable. The schemas and the transcription rules are the contract every
consumer depends on, so a change to either is a minor-version change at minimum, and the
fixtures in `fixtures/` are the executable statement of what the contract means.

## Consumers

Vendored or installed, a consumer's kernel is one of two things, and the difference is a
distribution decision rather than a semantic one:

- **vendored source**, hash-pinned per file, with a probe that asks whether the canonical
  branch has moved (what the GlassPane Harness fork does), or
- **this package**, pinned by semver.

Either way, run the fixtures: they are how you find out that the kernel you have is not the
kernel you think you have.
