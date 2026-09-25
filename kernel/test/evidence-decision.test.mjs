import assert from "node:assert/strict";
import { test } from "node:test";

import {
  decisionOutcomeFromEvidence,
  decisionSummaryFromEvidence,
  parseDecisionLogEntry,
  parseEvidencePack,
  parseEvidencePackRead,
} from "../dist/index.js";
import { readFixture } from "./helpers.mjs";

/**
 * evidence → DecisionOutcome transcription (kernel/src/evidence-decision.ts).
 *
 * The rule under test is a *vocabulary mapping*, not a verification: every input
 * field is the engine's own verdict. These tests exist so that neither shell can
 * invent its own meaning for pass/fail/blocked/inconclusive — which is what
 * would make two logs of the same run disagree.
 */

const OUTCOMES = new Set(["pass", "fail", "blocked", "inconclusive"]);

function pack(overrides = {}) {
  const base = structuredClone(readFixture("evidence-pack.ok-01.json"));
  return { ...base, ...overrides };
}

function entryFor(evidence) {
  return {
    entryId: "dl_01K2ABCDEFGHJKMNPQRSTVWXZ0",
    sequence: 0,
    prevEntryHash: "",
    operationId: evidence.operationId,
    summary: decisionSummaryFromEvidence(evidence),
    outcome: decisionOutcomeFromEvidence(evidence),
    createdAt: "2026-09-25T04:00:00.000Z",
  };
}

// ------------------------------------------------- the five real fixtures, by name

test("the evidence fixtures map to the outcomes they actually describe", () => {
  const expectations = {
    "evidence-pack.ok-01.json": "pass", // assertion passed, soft attribution
    "evidence-pack.ok-02.json": "inconclusive", // nothing asserted, nothing diagnosed
    "evidence-pack.ok-03.json": "pass", // diagnosis NO_ANOMALY, strong attribution
    "evidence-pack.ok-04-legacy-draft.json": "pass", // same shape, pre-freeze label
    "evidence-pack.ok-05-pixelbounds-null.json": "fail", // diagnosis class T2
  };
  for (const [file, want] of Object.entries(expectations)) {
    const evidence = parseEvidencePackRead(readFixture(file));
    assert.equal(decisionOutcomeFromEvidence(evidence), want, `${file} → ${want}`);
  }
});

test("every mapped outcome is accepted by the decision-log schema on both sides", () => {
  for (const file of [
    "evidence-pack.ok-01.json",
    "evidence-pack.ok-02.json",
    "evidence-pack.ok-03.json",
    "evidence-pack.ok-04-legacy-draft.json",
    "evidence-pack.ok-05-pixelbounds-null.json",
  ]) {
    const evidence = parseEvidencePackRead(readFixture(file));
    const entry = entryFor(evidence);
    assert.ok(OUTCOMES.has(entry.outcome), `outcome must stay inside the enum, got ${entry.outcome}`);
    assert.doesNotThrow(() => parseDecisionLogEntry(entry), `${file} produced an unloggable entry`);
    assert.equal(entry.operationId, evidence.operationId, "the entry cites the operation it came from");
  }
});

test("the legacy-labelled pack cannot be logged through the strict write path", () => {
  // `gp_last_evidence` may hand back archived bytes verbatim; the writer must
  // still refuse to mint a new pack from a pre-freeze label.
  const legacy = readFixture("evidence-pack.ok-04-legacy-draft.json");
  assert.throws(() => parseEvidencePack(legacy));
  const read = parseEvidencePackRead(legacy);
  assert.equal(read.schemaVersion, "glasspane.evidence/0.1", "reading folds the label onto the copy only");
  assert.equal(legacy.schemaVersion, "glasspane.evidence/0.1-draft", "the archived object the caller passed is untouched");
  assert.equal(decisionOutcomeFromEvidence(read), "pass");
});

// ------------------------------------------------------------------- precedence

test("a stopped circuit breaker is blocked, even when the assertion passed", () => {
  const evidence = pack({ circuitBreaker: { level: 3, reason: "repeated handler probe failures" } });
  assert.equal(evidence.assertion.passed, true, "the fixture really does carry a passing assertion");
  assert.equal(decisionOutcomeFromEvidence(evidence), "blocked");
  assert.match(decisionSummaryFromEvidence(evidence), /circuitBreaker level 3 \(repeated handler probe failures\)/);
});

test("a failing assertion outranks a clean diagnosis — nothing here upgrades", () => {
  const evidence = pack({ assertion: { ...pack().assertion, passed: false }, diagnosis: { class: "NO_ANOMALY", report: pack().diagnosis.report } });
  assert.equal(decisionOutcomeFromEvidence(evidence), "fail");
});

test("levels below the trip point do not read as blocked", () => {
  for (const level of [0, 1, 2]) {
    const evidence = pack({ circuitBreaker: { level, reason: "degraded capture" } });
    assert.equal(decisionOutcomeFromEvidence(evidence), "pass", `cb level ${level} must not mask the assertion`);
  }
});

// ------------------------------------------------------------------ downgrades

test("a pass the engine will not attribute strongly is logged as inconclusive", () => {
  const weak = pack({ attribution: { level: "weak", contaminated: false } });
  assert.equal(decisionOutcomeFromEvidence(weak), "inconclusive");
  const contaminated = pack({ attribution: { level: "strong", contaminated: true } });
  assert.equal(decisionOutcomeFromEvidence(contaminated), "inconclusive");
  assert.match(decisionSummaryFromEvidence(contaminated), /attribution strong, contaminated/);
});

test("downgrades never flip a fail into something kinder", () => {
  const failing = pack({
    assertion: { ...pack().assertion, passed: false },
    attribution: { level: "weak", contaminated: true },
  });
  assert.equal(decisionOutcomeFromEvidence(failing), "fail");
});

// ------------------------------- the absent-vs-null trap that this mapping exists to survive

test("an absent key and an explicit null are both 'nothing was asserted'", () => {
  const withNull = pack({ assertion: null, diagnosis: null });
  const withAbsent = { ...pack() };
  delete withAbsent.assertion;
  delete withAbsent.diagnosis;
  assert.notEqual(withNull.assertion, withAbsent.assertion, "the two shapes really differ on the wire");
  assert.equal(decisionOutcomeFromEvidence(withNull), "inconclusive");
  assert.equal(decisionOutcomeFromEvidence(withAbsent), "inconclusive", "a `!== null` test would have thrown here");
  const diagnosisOnly = { ...pack() };
  delete diagnosisOnly.assertion;
  diagnosisOnly.diagnosis = { class: "T4", report: pack().diagnosis.report };
  assert.equal(decisionOutcomeFromEvidence(diagnosisOnly), "fail");
});

test("a diagnosis with no assertion and no anomaly still logs as pass", () => {
  const evidence = { ...pack() };
  delete evidence.assertion;
  evidence.diagnosis = { class: "NO_ANOMALY", report: pack().diagnosis.report };
  assert.equal(decisionOutcomeFromEvidence(evidence), "pass");
});

// --------------------------------------------------------------------- summary

test("the summary names the property, the expected and the actual value", () => {
  const evidence = pack({ assertion: { ...pack().assertion, property: "enabled", expected: true, actual: false, passed: false } });
  const summary = decisionSummaryFromEvidence(evidence);
  assert.match(summary, /assertion enabled failed: expected true, actual false/);
  assert.match(summary, /diagnosis NO_ANOMALY/);
  assert.match(summary, /attribution soft$/);
});

test("a pathological anomaly string is clamped to the schema's 2048 limit, not rejected at write time", () => {
  // The assertion is cleared on purpose: with it present the passing assertion
  // would decide the outcome (see the precedence test above), and this case is
  // about the diagnosis-driven `fail` carrying an absurd anomaly string.
  const evidence = { ...pack({ assertion: null }) };
  evidence.diagnosis = { class: "T7", report: { ...pack().diagnosis.report, anomaly: "x".repeat(5000) } };
  const summary = decisionSummaryFromEvidence(evidence);
  assert.ok(summary.length <= 2048, `summary was ${summary.length} chars`);
  assert.ok(summary.endsWith("..."));
  assert.doesNotThrow(() => parseDecisionLogEntry(entryFor(evidence)), "the clamp must keep the entry loggable");
  assert.equal(decisionOutcomeFromEvidence(evidence), "fail");
});
