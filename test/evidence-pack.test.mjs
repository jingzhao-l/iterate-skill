import assert from "node:assert/strict";
import { test } from "node:test";
import Ajv2020 from "ajv/dist/2020.js";
import {
  EVIDENCE_PACK_JSON_SCHEMA,
  EVIDENCE_PACK_SCHEMA_ID,
  KernelSchemaError,
  parseEvidencePack
} from "../dist/index.js";
import { readFixture } from "./helpers.mjs";

const ajv = new Ajv2020({ allErrors: true });
const validate = ajv.compile(EVIDENCE_PACK_JSON_SCHEMA);

function assertBothSidesAccept(input, label) {
  assert.equal(validate(input), true, `ajv should accept ${label}: ${JSON.stringify(validate.errors)}`);
  assert.doesNotThrow(() => parseEvidencePack(input), `zod should accept ${label}`);
}

function assertBothSidesReject(input, label) {
  assert.equal(validate(input), false, `ajv should reject ${label}`);
  assert.throws(() => parseEvidencePack(input), KernelSchemaError, `zod should reject ${label}`);
}

const base = readFixture("evidence-pack.ok-01.json");
const degraded = readFixture("evidence-pack.ok-02.json");

test("schema $id is the fixed iterate kernel namespace", () => {
  assert.equal(EVIDENCE_PACK_JSON_SCHEMA.$id, EVIDENCE_PACK_SCHEMA_ID);
});

test("full-featured fixture passes ajv and zod", () => {
  assertBothSidesAccept(base, "ok-01");
});

test("degraded fixture (pixel denied, null assertion/diagnosis) passes ajv and zod", () => {
  assertBothSidesAccept(degraded, "ok-02");
});

test("negative: missing required field is rejected on both sides", () => {
  const broken = structuredClone(base);
  delete broken.createdAt;
  assertBothSidesReject(broken, "missing createdAt");
});

test("negative: invalid attribution enum is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.attribution.level = "medium";
  assertBothSidesReject(broken, "attribution.level=medium");
});

test("negative: additional top-level property is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.extraField = true;
  assertBothSidesReject(broken, "top-level extra property");
});

test("negative: nested additional property in signals.act is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.signals.act.extra = 1;
  assertBothSidesReject(broken, "signals.act extra property");
});

test("negative: broken operationId pattern is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.operationId = "op_not-a-valid-ulid";
  assertBothSidesReject(broken, "operationId pattern break");
});

test("negative: operationId with excluded Crockford char (I) is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.operationId = "op_0123456789ABCDEFGHIJKLMNOP";
  assertBothSidesReject(broken, "operationId contains I");
});

test("negative: wrong schemaVersion const is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.schemaVersion = "glasspane.evidence/0.2";
  assertBothSidesReject(broken, "schemaVersion const break");
});

test("P6 §3.1: probe-carrying fixture (handlerProbe/stateDiff objects) passes ajv and zod", () => {
  assertBothSidesAccept(readFixture("evidence-pack.ok-03.json"), "ok-03");
});

test("negative: malformed handlerProbe object is rejected on both sides (P6 oneOf shape)", () => {
  const broken = structuredClone(base);
  broken.signals.handlerProbe = { entered: [] };
  assertBothSidesReject(broken, "handlerProbe wrong shape");
});

test("negative: handlerProbe with unknown key is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.signals.handlerProbe = {
    probeVersion: "gp-probe/0.1.0",
    hitCount: 1,
    handlers: [],
    lateCount: 0,
    extra: true
  };
  assertBothSidesReject(broken, "handlerProbe extra key");
});

test("negative: stateDiff with unknown source is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.signals.stateDiff = { source: "z9-magic", changed: true, entries: [] };
  assertBothSidesReject(broken, "stateDiff unknown source");
});

test("negative: circuitBreaker level out of range is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.circuitBreaker.level = 7;
  assertBothSidesReject(broken, "circuitBreaker.level=7");
});

test("negative: changedPixelRatio out of range is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.signals.pixelDiff.changedPixelRatio = 1.5;
  assertBothSidesReject(broken, "changedPixelRatio=1.5");
});

test("negative: assertion expected wrong type is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.assertion.expected = 5;
  assertBothSidesReject(broken, "assertion.expected number");
});

test("negative: malformed tree digest is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.signals.axEvent.treeDigestBefore = "XYZ";
  assertBothSidesReject(broken, "treeDigestBefore not 32-hex");
});

test("negative: invalid createdAt format is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.createdAt = "2026-09-14 12:34:56";
  assertBothSidesReject(broken, "createdAt not ISO millis");
});

test("negative: selector field exceeding max length is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.signals.act.selector.title = "x".repeat(513);
  assertBothSidesReject(broken, "selector title 513 chars");
});

test("KernelSchemaError carries stable code and located issues", () => {
  const broken = structuredClone(base);
  broken.attribution.level = "medium";
  try {
    parseEvidencePack(broken);
    assert.fail("expected KernelSchemaError");
  } catch (error) {
    assert.ok(error instanceof KernelSchemaError);
    assert.equal(error.code, "KERNEL_E_SCHEMA");
    assert.ok(error.issues.length >= 1);
    assert.ok(error.issues.some((issue) => issue.path === "attribution.level"));
  }
});
