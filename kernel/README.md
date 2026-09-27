# @iterate/kernel

The iterate ecosystem's shared semantic kernel: schemas, the evidence → decision
transcription, the decision-log audit chain, and public validators.

**What it is not.** It carries no verification reasoning. Judging whether a claim is true
belongs to the engine that produced the evidence; this package transcribes what that engine
already decided, so that every shell in the ecosystem speaks the same language instead of
each inventing its own.

## Install

```bash
npm install @iterate/kernel
```

## Import per module, not through the barrel

```ts
import { decisionOutcomeFromEvidence } from "@iterate/kernel/evidence-decision"
import { appendDecisionEntry } from "@iterate/kernel/decision-log"
import { parseEvidencePack } from "@iterate/kernel/parse"
```

Each module is its own subpath export. Importing the barrel (`@iterate/kernel`) also pulls
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
| `errors` / `schemas` / `canonical-json` / `recipe-config` | `KernelSchemaError`, the JSON Schemas, canonical serialisation, recipe validation |

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
