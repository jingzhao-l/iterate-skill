import assert from "node:assert/strict";
import { test } from "node:test";
import Ajv2020 from "ajv/dist/2020.js";
import {
  EVIDENCE_PACK_JSON_SCHEMA,
  EVIDENCE_PACK_SCHEMA_ID,
  EvidencePackReadSchema,
  KernelSchemaError,
  parseEvidencePack,
  parseEvidencePackRead
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

/* ------------------------------------------------------------------ *
 * READ side (P0 §4 "冻结前历史值 0.1-draft 只读兼容" + §4.2 required-nullable
 * pixelDiff.bounds). Two archive shapes are refused by the frozen schema and by
 * the write path, yet were produced by the engine itself and must stay
 * readable: the pre-freeze version label, and a `pixelDiff` whose `bounds` key
 * the old Swift encoder omitted instead of writing null.
 * ------------------------------------------------------------------ */

const legacyDraft = readFixture("evidence-pack.ok-04-legacy-draft.json");
const pixelBoundsOmitted = readFixture("evidence-pack.ok-05-pixelbounds-null.json");

test("read fixture sanity: each archive carries exactly one legacy shape", () => {
  assert.equal(legacyDraft.schemaVersion, "glasspane.evidence/0.1-draft");
  assert.deepEqual(legacyDraft.signals.pixelDiff.bounds, {
    x: 512, y: 344, width: 168, height: 32
  });
  assert.equal(pixelBoundsOmitted.schemaVersion, "glasspane.evidence/0.1");
  assert.equal("bounds" in pixelBoundsOmitted.signals.pixelDiff, false);
});

test("legacy draft label: refused by ajv and the write path, readable on the read path", () => {
  assertBothSidesReject(legacyDraft, "schemaVersion=0.1-draft");
  assert.deepEqual(parseEvidencePackRead(legacyDraft), {
    ...legacyDraft,
    schemaVersion: "glasspane.evidence/0.1"
  });
});

test("omitted pixelDiff.bounds: refused by ajv and the write path, reads as null", () => {
  assertBothSidesReject(pixelBoundsOmitted, "pixelDiff without the bounds key");
  assert.deepEqual(parseEvidencePackRead(pixelBoundsOmitted), {
    ...pixelBoundsOmitted,
    signals: {
      ...pixelBoundsOmitted.signals,
      pixelDiff: { ...pixelBoundsOmitted.signals.pixelDiff, bounds: null }
    }
  });
});

test("the two legacy shapes together (the shape actually on disk) still reads", () => {
  const onDisk = structuredClone(pixelBoundsOmitted);
  onDisk.schemaVersion = "glasspane.evidence/0.1-draft";
  assert.throws(() => parseEvidencePack(onDisk), KernelSchemaError);
  const read = parseEvidencePackRead(onDisk);
  assert.equal(read.schemaVersion, "glasspane.evidence/0.1");
  assert.equal(read.signals.pixelDiff.bounds, null);
  assert.equal(read.operationId, pixelBoundsOmitted.operationId);
});

test("reading never rewrites the archive value the caller passed in", () => {
  // The shell hands the daemon's frame straight to the agent, so the pack the
  // user reads must keep its own label and its own key set: normalisation
  // happens on a copy, never in place.
  parseEvidencePackRead(legacyDraft);
  parseEvidencePackRead(pixelBoundsOmitted);
  assert.equal(legacyDraft.schemaVersion, "glasspane.evidence/0.1-draft");
  assert.equal("bounds" in pixelBoundsOmitted.signals.pixelDiff, false);
});

test("read path is not a rubber stamp: strictness and patterns still apply", () => {
  const withExtraKey = structuredClone(legacyDraft);
  withExtraKey.unexpectedField = true;
  assert.throws(() => parseEvidencePackRead(withExtraKey), KernelSchemaError, "unknown key");

  const unknownLabel = structuredClone(legacyDraft);
  unknownLabel.schemaVersion = "glasspane.evidence/0.9-next";
  assert.throws(() => parseEvidencePackRead(unknownLabel), KernelSchemaError, "third label");
  try {
    parseEvidencePackRead(unknownLabel);
    assert.fail("expected KernelSchemaError");
  } catch (error) {
    assert.ok(error.issues.some((issue) => issue.path === "schemaVersion"));
  }

  const missingRequired = structuredClone(pixelBoundsOmitted);
  delete missingRequired.attribution;
  assert.throws(() => parseEvidencePackRead(missingRequired), KernelSchemaError, "missing attribution");

  // A present-but-invalid bounds is a violation, not an omission: it is never
  // quietly replaced by null.
  const badBounds = structuredClone(pixelBoundsOmitted);
  badBounds.signals.pixelDiff.bounds = "top-left";
  assert.throws(() => parseEvidencePackRead(badBounds), KernelSchemaError, "bounds wrong type");
  try {
    parseEvidencePackRead(badBounds);
    assert.fail("expected KernelSchemaError");
  } catch (error) {
    assert.ok(error.issues.some((issue) => issue.path === "signals.pixelDiff.bounds"));
  }

  const badOperationId = structuredClone(legacyDraft);
  badOperationId.operationId = "op_not-valid";
  assert.throws(() => parseEvidencePackRead(badOperationId), KernelSchemaError, "operationId pattern");
});

test("read path leaves a conformant pack untouched and fabricates no signals", () => {
  assert.deepEqual(parseEvidencePackRead(base), base);
  const readDegraded = parseEvidencePackRead(degraded);
  assert.equal("pixelDiff" in readDegraded.signals, false);
  assert.deepEqual(readDegraded, degraded);
});

test("EvidencePackReadSchema validates the read contract directly", () => {
  assert.equal(EvidencePackReadSchema.safeParse(base).success, true);
  assert.equal(EvidencePackReadSchema.safeParse(legacyDraft).success, true);
  assert.equal(EvidencePackReadSchema.safeParse(pixelBoundsOmitted).success, true);
  assert.equal(EvidencePackReadSchema.safeParse({ ...base, schemaVersion: "nope" }).success, false);
});
