import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DecisionLogDraftSchema,
  DECISION_TRANSCRIBE_CODES,
  KernelDecisionTranscribeError,
  canonicalJson,
  decisionLogDraftFromRecord,
  isLegacyDecisionRecord,
  parseDecisionLogEntry
} from "../dist/index.js";
import { readFixture } from "./helpers.mjs";

/**
 * The transcription rules are the contract scenario 3 turns on: the iterate ledgers already
 * on disk (`{timestamp, round, type, data}` JSONL, written independently in Python and
 * TypeScript) have to become THIS shape, or the two ecosystems keep two logs and the shared
 * contract is a document. So the cases come from `fixtures/decision-record-transcription.ok-01.json`
 * — the same file the Python port is coded from — and this suite asserts the TypeScript side
 * against it rather than against itself.
 */

const corpus = readFixture("decision-record-transcription.ok-01.json");

function expand(caseItem) {
  const record = structuredClone(caseItem.record);
  if (typeof caseItem.blobRepeat === "number") {
    record.data[caseItem.blobKey ?? "blob"] = "x".repeat(caseItem.blobRepeat);
  }
  if (typeof caseItem.summaryRepeat === "number") {
    record.data.summary = "s".repeat(caseItem.summaryRepeat);
  }
  return record;
}

/** Absent in the expectation means ABSENT in the result, not null: the canonical bytes the
 *  chain hashes are sensitive to the difference, and a `null` here would re-hash history. */
function assertExactDraft(actual, expected, label) {
  for (const [field, value] of Object.entries(expected)) {
    assert.deepEqual(actual[field], value, `${label}: ${field}`);
  }
  for (const field of ["entryId", "summary", "outcome", "createdAt", "kind", "round", "dimension", "operationId", "payload"]) {
    if (!(field in expected)) {
      assert.equal(field in actual, false, `${label}: ${field} must be absent, not null/undefined-valued`);
      assert.equal(actual[field], undefined, `${label}: ${field} present as undefined-valued`);
    }
  }
}

function captureError(run) {
  try {
    run();
  } catch (error) {
    return error;
  }
  return undefined;
}

for (const caseItem of corpus.cases) {
  if (caseItem.expectError !== undefined) {
    test(`refuses ${caseItem.id} with ${caseItem.expectError}`, () => {
      const err = captureError(() => decisionLogDraftFromRecord(expand(caseItem), caseItem.entryId));
      assert.ok(err instanceof KernelDecisionTranscribeError, `${caseItem.id}: expected a KernelDecisionTranscribeError, got ${err}`);
      assert.equal(err.code, caseItem.expectError, `wrong code for ${caseItem.id}`);
      assert.equal(typeof err.remedy, "string");
      assert.ok(err.remedy.length > 0, `${caseItem.id}: a refusal without a remedy is not actionable`);
    });
    continue;
  }

  test(`transcribes ${caseItem.id}`, () => {
    const draft = decisionLogDraftFromRecord(expand(caseItem), caseItem.entryId);
    assertExactDraft(draft, caseItem.expect, caseItem.id);
    // Closure check: the whole point is that the transcribed record can be appended. A draft
    // that the ledger's own schema refuses means the convergence is decorative.
    assert.doesNotThrow(() => DecisionLogDraftSchema.parse(draft), `${caseItem.id}: draft not accepted by the ledger`);
  });
}

test("a transcribed record reaches the ledger with its vocabulary intact", () => {
  const full = corpus.cases.find((item) => item.id === "review-result-full");
  const draft = decisionLogDraftFromRecord(expand(full), full.entryId);
  const entry = { ...draft, sequence: 0, prevEntryHash: "" };
  const parsed = parseDecisionLogEntry(entry);
  assert.equal(parsed.kind, "review_result");
  assert.equal(parsed.round, 3);
  assert.equal(parsed.dimension, "ui-consistency");
  assert.equal(parsed.payload.findings.length, 2);
  // Nothing about the record is dropped on the way in, and the payload survives structured.
  assert.equal(canonicalJson(parsed.payload), canonicalJson(full.record.data));
});

test("isLegacyDecisionRecord classifies by shape, so a migrated log can mix formats", () => {
  assert.equal(isLegacyDecisionRecord({ timestamp: "x", round: 1, type: "decision", data: {} }), true);
  assert.equal(isLegacyDecisionRecord({ timestamp: "x", type: "decision" }), true);
  assert.equal(isLegacyDecisionRecord({ entryId: "dl_0", sequence: 0, prevEntryHash: "", summary: "s", outcome: "pass", createdAt: "x" }), false);
  assert.equal(isLegacyDecisionRecord({ timestamp: "x", type: "decision", extra: 1 }), false, "unknown key is not a legacy record either");
  assert.equal(isLegacyDecisionRecord(null), false);
  assert.equal(isLegacyDecisionRecord("{}"), false);
});

test("every documented refusal has a named code", () => {
  const used = corpus.cases.map((item) => item.expectError).filter((code) => code !== undefined);
  for (const code of used) {
    assert.ok(Object.values(DECISION_TRANSCRIBE_CODES).includes(code), `${code} is not a code this module emits`);
  }
  // The bound cases must refuse with codes, not crash: a blob and an over-long sentence are
  // both ordinary producer mistakes, and a stack trace gives the caller nothing to act on.
  assert.ok(used.includes(DECISION_TRANSCRIBE_CODES.payload));
  assert.ok(used.includes(DECISION_TRANSCRIBE_CODES.summary));
});
