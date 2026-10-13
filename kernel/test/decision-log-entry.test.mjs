import assert from "node:assert/strict";
import { test } from "node:test";
import Ajv2020 from "ajv/dist/2020.js";
import {
  DECISION_LOG_ENTRY_JSON_SCHEMA,
  DECISION_LOG_ENTRY_SCHEMA_ID,
  KernelSchemaError,
  parseDecisionLogEntry
} from "../dist/index.js";
import { canonical, readFixture } from "./helpers.mjs";

const ajv = new Ajv2020({ allErrors: true });
const validate = ajv.compile(DECISION_LOG_ENTRY_JSON_SCHEMA);

function assertBothSidesAccept(input, label) {
  assert.equal(validate(input), true, `ajv should accept ${label}: ${JSON.stringify(validate.errors)}`);
  assert.doesNotThrow(() => parseDecisionLogEntry(input), `zod should accept ${label}`);
}

function assertBothSidesReject(input, label) {
  assert.equal(validate(input), false, `ajv should reject ${label}`);
  assert.throws(() => parseDecisionLogEntry(input), KernelSchemaError, `zod should reject ${label}`);
}

const base = readFixture("decision-log-entry.ok-01.json");

test("schema $id is the fixed iterate kernel namespace", () => {
  assert.equal(DECISION_LOG_ENTRY_JSON_SCHEMA.$id, DECISION_LOG_ENTRY_SCHEMA_ID);
});

test("genesis entry (empty prevEntryHash) fixture passes ajv and zod", () => {
  assertBothSidesAccept(base, "ok-01");
});

test("chained entry with full 64-hex prevEntryHash passes both sides", () => {
  const chained = structuredClone(base);
  chained.sequence = 1;
  chained.prevEntryHash = "a".repeat(64);
  chained.outcome = "fail";
  assertBothSidesAccept(chained, "chained entry");
});

test("entry without operationId passes both sides (non-op decisions allowed)", () => {
  const noOp = structuredClone(base);
  delete noOp.operationId;
  assertBothSidesAccept(noOp, "no operationId");
});

test("negative: broken entryId pattern is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.entryId = "dl_short";
  assertBothSidesReject(broken, "entryId pattern break");
});

test("negative: prevEntryHash wrong length is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.prevEntryHash = "a".repeat(63);
  assertBothSidesReject(broken, "prevEntryHash 63 chars");
});

test("negative: uppercase prevEntryHash is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.prevEntryHash = "A".repeat(64);
  assertBothSidesReject(broken, "prevEntryHash uppercase");
});

test("negative: invalid outcome enum is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.outcome = "pending";
  assertBothSidesReject(broken, "outcome=pending");
});

test("negative: negative sequence is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.sequence = -1;
  assertBothSidesReject(broken, "sequence=-1");
});

test("negative: missing required field is rejected on both sides", () => {
  const broken = structuredClone(base);
  delete broken.summary;
  assertBothSidesReject(broken, "missing summary");
});

test("negative: additional property is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.actor = "agent";
  assertBothSidesReject(broken, "extra property");
});

test("negative: summary exceeding 2048 chars is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.summary = "s".repeat(2049);
  assertBothSidesReject(broken, "summary 2049 chars");
});

// ── The producer-vocabulary fields (kind / round / dimension / payload) ─────────
//
// These exist so the ledgers both ecosystems already run can BE this shape instead of
// sitting beside it. Two properties matter and neither is obvious from the type: the new
// fields must be absent-not-null when unset (or every chain written before them would
// re-hash differently), and the payload bound is enforced by the validators, not the
// schema — so it has to be pinned as a named divergence rather than quietly assumed.

const extended = readFixture("decision-log-entry.ok-02.json");

test("entry carrying kind/round/dimension/payload passes both sides", () => {
  assertBothSidesAccept(extended, "ok-02");
});

test("omitting the new fields leaves the canonical bytes untouched (old chains still verify)", () => {
  const asStored = canonical(base);
  const withNulls = structuredClone(base);
  assert.equal(asStored.includes("\"kind\""), false, "absent is not null");
  assert.equal(asStored.includes("null"), false, "no null placeholders in the stored form");
  // An entry that declares the fields as null must NOT validate: a producer cannot spell
  // "unset" as null, because that would change what the ledger's hashes cover.
  for (const field of ["kind", "round", "dimension", "payload"]) {
    const nulled = structuredClone(base);
    nulled[field] = null;
    assertBothSidesReject(nulled, `${field}=null`);
  }
});

test("negative: kind outside the snake_case vocabulary is rejected on both sides", () => {
  const broken = structuredClone(extended);
  broken.kind = "Review Result";
  assertBothSidesReject(broken, "kind with a space and capitals");
  const tooLong = structuredClone(extended);
  tooLong.kind = "k".repeat(33);
  assertBothSidesReject(tooLong, "kind 33 chars (max 32)");
});

test("negative: round and dimension keep their own bounds", () => {
  const negRound = structuredClone(extended);
  negRound.round = -1;
  assertBothSidesReject(negRound, "round=-1");
  const upperDim = structuredClone(extended);
  upperDim.dimension = "UI_Consistency";
  assertBothSidesReject(upperDim, "dimension not a kernel dimension id");
  const longDim = structuredClone(extended);
  longDim.dimension = "d".repeat(65);
  assertBothSidesReject(longDim, "dimension 65 chars");
});

test("documented divergence: the payload length bound is validator-only, JSON Schema cannot state it", () => {
  const oversized = structuredClone(extended);
  oversized.payload = { blob: "x".repeat(9000) };
  // The serialized-length bound has no JSON Schema equivalent...
  assert.equal(validate(oversized), true, "ajv has no way to bound canonical-JSON length");
  // ...so the TypeScript side must refuse it. If this stops throwing, the bound is fiction
  // and the ledger is back to an unbounded line whose digest can grow without limit.
  assert.throws(() => parseDecisionLogEntry(oversized), KernelSchemaError);
});

test("payload contents are structured, not stringified, and stay inside the entry hash", () => {
  const parsed = parseDecisionLogEntry(extended);
  assert.equal(typeof parsed.payload, "object");
  assert.equal(parsed.payload.blocking, 1);
  assert.equal(parsed.payload.findings.length, 2);
  // Re-serializing must reproduce the fixture's canonical form byte for byte.
  assert.equal(canonical(parsed), canonical(extended));
});

