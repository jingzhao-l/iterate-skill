import assert from "node:assert/strict";
import { test } from "node:test";
import Ajv2020 from "ajv/dist/2020.js";
import {
  DECISION_LOG_ENTRY_JSON_SCHEMA,
  DECISION_LOG_ENTRY_SCHEMA_ID,
  KernelSchemaError,
  parseDecisionLogEntry
} from "../dist/index.js";
import { readFixture } from "./helpers.mjs";

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
