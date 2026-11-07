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
  assert.ok(used.includes(DECISION_TRANSCRIBE_CODES.timestamp));
});

/**
 * The pattern in rule 4 bounds the SPELLING; the calendar is the other half, and
 * `Date.parse` silently rolls an impossible date over instead of refusing it
 * (2026-02-31 becomes 2026-03-03) while the Python half constructs the date and
 * raises. The two implementations then transcribe one record into two different
 * instants — which is the exact failure the pattern was written to prevent.
 */
function transcribeTimestamp(timestamp) {
  return decisionLogDraftFromRecord(
    { timestamp, round: 1, type: "validation", data: { passed: true } },
    "dl_0123456789ABCDEFGHJKMNPQRT"
  ).createdAt;
}

test("the calendar is checked: day counts, leap years, and offsets convert instead of rolling over", () => {
  for (const [timestamp, expected] of [
    ["2026-02-28T23:59:59.999Z", "2026-02-28T23:59:59.999Z"],
    ["2028-02-29T00:00:00Z", "2028-02-29T00:00:00.000Z"],
    ["2100-02-28T00:00:00Z", "2100-02-28T00:00:00.000Z"],
    ["2026-04-30T00:00:00Z", "2026-04-30T00:00:00.000Z"],
    ["2026-01-31T00:00:00Z", "2026-01-31T00:00:00.000Z"],
    // West of UTC: the +08:00 case in the fixture is only one direction, and an
    // implementation that accepted a literal "+-" sign would pass it and fail here.
    ["2026-10-11T02:28:11.042-05:00", "2026-10-11T07:28:11.042Z"],
    ["2026-10-11T02:28:11.0425+05:45", "2026-10-10T20:43:11.042Z"],
    ["2026-10-11T00:00:00+00:00", "2026-10-11T00:00:00.000Z"]
  ]) {
    assert.equal(transcribeTimestamp(timestamp), expected, timestamp);
  }

  for (const impossible of [
    "2026-02-29T00:00:00Z", // 2026 is not a leap year
    "2100-02-29T00:00:00Z", // century rule: 2100 is divisible by 100 and not 400
    "2026-02-31T00:00:00Z",
    "2026-04-31T00:00:00Z",
    "2026-06-31T00:00:00Z",
    "2026-00-01T00:00:00Z",
    "2026-13-01T00:00:00Z",
    "2026-01-00T00:00:00Z",
    "0000-01-01T00:00:00Z", // the year the Python half cannot construct either
    "2026-10-11T24:00:00Z",
    "2026-10-11T00:60:00Z",
    "2026-10-11T00:00:60Z",
    "2026-10-11T00:00:00+24:00",
    "2026-10-11T00:00:00+00:60"
  ]) {
    const error = captureError(() => transcribeTimestamp(impossible));
    assert.ok(error instanceof KernelDecisionTranscribeError, `${impossible}: expected a refusal, got ${error}`);
    assert.equal(error.code, DECISION_TRANSCRIBE_CODES.timestamp, impossible);
  }
});

