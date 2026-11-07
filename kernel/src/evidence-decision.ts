import { EvidencePackSchema, type EvidencePack } from "./evidence-pack.js";
import { schemaErrorFrom } from "./errors.js";
import type { DecisionOutcome } from "./decision-log-entry.js";

/**
 * Transcribing an evidence pack into the decision log's vocabulary.
 *
 * This function deliberately contains **no verification logic of its own**. The
 * three architecture iron laws put "did this change happen because of this
 * operation" inside the Swift engine; the engine already answered that question
 * and wrote it into the pack (`attribution`, `assertion.passed`,
 * `diagnosis.class`, `circuitBreaker.level`). What lives here is only the
 * mapping from those verdicts to the four `DecisionOutcome` values, so that both
 * TypeScript shells log the same words for the same evidence — one of the
 * reasons the mapping is in the kernel instead of in each shell.
 *
 * Order matters, and it is the order of "what actually decides the run":
 *
 *   1. `circuitBreaker.level >= 3`      → `blocked`
 *      The loop was stopped by policy. Whether the interface is fine is not
 *      what this entry is about, and saying `fail` would blame the app for a
 *      harness limit.
 *   2. an assertion present             → `pass` / `fail` from `assertion.passed`
 *      This is the engine's own verdict on the property that was checked.
 *   3. a diagnosis present              → `NO_ANOMALY` = pass, `INCONCLUSIVE` =
 *      inconclusive, any `T*` class = fail
 *   4. neither                          → `inconclusive`
 *      Nothing was asserted and nothing diagnosed: there is no basis to record
 *      a verdict, and an audit log full of unfounded `pass` entries is worse
 *      than an empty one.
 *
 * Then, and only as a downgrade, the pack's own contamination fields are
 * honoured: a `pass` whose attribution is `weak`, or which the engine flagged
 * `contaminated`, is recorded as `inconclusive`. A "pass" the engine itself
 * refuses to attribute to this operation must not be logged as if it had been
 * attributed — that is the failure mode the audit chain exists to catch.
 * Nothing here can upgrade a verdict.
 */
/**
 * The one gate both mappings pass through. Reading a field off whatever was handed
 * in would turn a shape error into a `TypeError` at an arbitrary depth — the
 * package's rule is that a refusal names the field and carries a code.
 *
 * The write-side schema is the one to check against, and `parseEvidencePackRead`
 * folds a pack read off disk onto exactly that shape, so an archived pack still
 * transcribes; a pack that never conformed cannot produce a verdict words.
 */
function checkedPack(evidence: unknown): EvidencePack {
  const checked = EvidencePackSchema.safeParse(evidence);
  if (!checked.success) {
    throw schemaErrorFrom("evidence pack", checked.error);
  }
  return checked.data;
}

export function decisionOutcomeFromEvidence(evidence: EvidencePack): DecisionOutcome {
  const pack = checkedPack(evidence);
  const base = baseOutcome(pack);
  if (base !== "pass") return base;
  if (pack.attribution.contaminated) return "inconclusive";
  if (pack.attribution.level === "weak") return "inconclusive";
  return "pass";
}

function baseOutcome(evidence: EvidencePack): DecisionOutcome {
  if (evidence.circuitBreaker.level >= 3) return "blocked";
  // `assertion` and `diagnosis` are **both** `optional()` and `union([X, null])`:
  // absent and explicit-null are two different shapes the engine really emits
  // (the frozen fixture carries `"diagnosis": null`). A `!== null` test alone
  // would treat an absent key as a present object and throw, so presence is
  // tested with `?? null` instead.
  const assertion = evidence.assertion ?? null;
  if (assertion !== null) return assertion.passed ? "pass" : "fail";
  const diagnosis = evidence.diagnosis ?? null;
  if (diagnosis !== null) {
    if (diagnosis.class === "NO_ANOMALY") return "pass";
    if (diagnosis.class === "INCONCLUSIVE") return "inconclusive";
    return "fail";
  }
  return "inconclusive";
}

/**
 * Human-readable reason for the entry's `summary`, built from the same fields
 * only. Producers use it so that two shells do not invent two phrasings of the
 * same state; it is a *rendering* of the pack, never a new judgement.
 */
export function decisionSummaryFromEvidence(evidence: EvidencePack): string {
  const pack = checkedPack(evidence);
  const parts: string[] = [];
  const assertion = pack.assertion ?? null;
  if (assertion !== null) {
    parts.push(
      `assertion ${assertion.property} ${assertion.passed ? "passed" : "failed"}: expected ${JSON.stringify(assertion.expected)}, actual ${JSON.stringify(assertion.actual)}`
    );
  }
  const diagnosis = pack.diagnosis ?? null;
  if (diagnosis !== null) {
    parts.push(`diagnosis ${diagnosis.class}: ${diagnosis.report.anomaly}`);
  }
  if (pack.circuitBreaker.level > 0) {
    parts.push(
      `circuitBreaker level ${pack.circuitBreaker.level}${pack.circuitBreaker.reason ? ` (${pack.circuitBreaker.reason})` : ""}`
    );
  }
  parts.push(`attribution ${pack.attribution.level}${pack.attribution.contaminated ? ", contaminated" : ""}`);
  const summary = parts.join("; ");
  return summary.length > 2048 ? `${summary.slice(0, 2045)}...` : summary;
}
