import assert from "node:assert/strict";
import { test } from "node:test";

import {
  decisionOutcomeFromEvidence,
  decisionSummaryFromEvidence,
  parseEvidencePackRead
} from "../dist/index.js";
import { readFixture } from "./helpers.mjs";

/**
 * Transcription is a rendering, not a judgement — and a second implementation has to be
 * able to reproduce it exactly, because iterate-harness is Python and `glasspaned` is
 * Swift. `fixtures/evidence-decision.ok-01.json` therefore carries its rules in prose and
 * eight cases whose expected values were derived from those prose rules independently of
 * this file (see the fixture's `comment` for the derivation, and the provenance test
 * below for which cases are real engine packs and which are single-field derivations).
 *
 * The comparison is the point: if this implementation disagrees with the fixture, one of
 * the two changed and the drift is exactly what the consumers cannot afford.
 */
const fixture = readFixture("evidence-decision.ok-01.json");

for (const item of fixture.cases) {
  test(`${item.name} transcribes to ${item.expectedOutcome}`, () => {
    // A pack the contract rejects cannot pin a transcription rule, so shape validity is
    // asserted first — for the derived cases too, which are one-field edits of real bytes.
    // The read-side parser is the path a consumer using archived evidence actually takes
    // (these packs carry the draft `schemaVersion` the engine wrote before the freeze).
    const pack = parseEvidencePackRead(item.input);
    assert.equal(decisionOutcomeFromEvidence(pack), item.expectedOutcome);
    assert.equal(decisionSummaryFromEvidence(pack), item.expectedSummary);
  });
}

test("the fixture's provenance is stated per case, not assumed", () => {
  for (const item of fixture.cases) {
    if (item.origin === "real") {
      assert.equal(item.input.operationId, item.sourceOperationId, `${item.name} claims a real pack`);
      assert.match(String(item.sourceOperationId), /^op_[0-9A-Z]{26}$/, `${item.name} names no engine operation`);
      continue;
    }
    assert.match(String(item.origin), /^derived: /, `${item.name} must say which field was derived`);
    assert.ok(item.input.operationId, `${item.name} lost the operation it was derived from`);
  }
});

test("every documented branch of the transcription is exercised", () => {
  // Without this, the fixture could quietly shrink to "the easy cases" and still be green.
  const outcomes = new Set(fixture.cases.map((item) => item.expectedOutcome));
  for (const outcome of ["blocked", "pass", "fail", "inconclusive"]) {
    assert.ok(outcomes.has(outcome), `no case exercises the ${outcome} branch`);
  }
  assert.ok(
    fixture.cases.some((item) => String(item.origin).includes("weak")),
    "the weak-attribution downgrade is not pinned"
  );
  assert.ok(
    fixture.cases.some((item) => String(item.origin).includes("contaminated")),
    "the contamination downgrade is not pinned"
  );
  assert.ok(
    fixture.cases.some((item) => item.input.assertion && item.input.diagnosis),
    "the assertion-outranks-diagnosis order is not pinned"
  );
  assert.ok(
    fixture.cases.some((item) => item.input.circuitBreaker.level >= 3),
    "the breaker-first rule is not pinned"
  );
});
