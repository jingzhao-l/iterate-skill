import assert from "node:assert/strict";
import { test } from "node:test";

import Ajv2020 from "ajv/dist/2020.js";

import {
  CONVERGENCE_ROUND_STATE_JSON_SCHEMA,
  DECISION_LOG_ENTRY_JSON_SCHEMA,
  EVIDENCE_PACK_JSON_SCHEMA,
  INVARIANT_REPORT_JSON_SCHEMA,
  KERNEL_SAFE_INTEGER_MAX,
  KERNEL_SAFE_INTEGER_MIN,
  PROVIDER_REGISTRATION_JSON_SCHEMA,
  RECIPE_CONFIG_JSON_SCHEMA,
  REVERIFICATION_REQUEST_JSON_SCHEMA,
  RUN_PLAN_JSON_SCHEMA,
  parseDecisionLogEntry,
  parseEvidencePack,
  parseInvariantReport,
  parseRoundState
} from "../dist/index.js";
import { newDecisionEntryId } from "../dist/decision-log.js";
import { readFixture } from "./helpers.mjs";

/**
 * Every integer this contract publishes is bounded to the range the canonical
 * form can print identically in every runtime.
 *
 * ECMAScript renders `1e21` as `1e+21` and Python prints
 * `1000000000000000000000`, so above 2^53−1 the same document digests to two
 * different byte sequences in two runtimes — and a digest only one language can
 * recompute is a claim, not evidence. The zod mirrors have always refused such
 * values (`.int()` is a safe-integer check), and the published schemas did not
 * say so: a schema-only reader was told `1e21` was a valid round number while
 * every validator refused it.
 */

const ajv = new Ajv2020({ strict: false, allErrors: true });

const PUBLISHED = [
  ["evidence-pack", EVIDENCE_PACK_JSON_SCHEMA],
  ["decision-log-entry", DECISION_LOG_ENTRY_JSON_SCHEMA],
  ["recipe-config", RECIPE_CONFIG_JSON_SCHEMA],
  ["run-plan", RUN_PLAN_JSON_SCHEMA],
  ["invariant-report", INVARIANT_REPORT_JSON_SCHEMA],
  ["reverification-request", REVERIFICATION_REQUEST_JSON_SCHEMA],
  ["convergence-round-state", CONVERGENCE_ROUND_STATE_JSON_SCHEMA],
  ["provider-registration", PROVIDER_REGISTRATION_JSON_SCHEMA]
];

function integerNodes(node, path, found) {
  if (Array.isArray(node)) {
    node.forEach((item, index) => integerNodes(item, `${path}.${index}`, found));
    return found;
  }
  if (node === null || typeof node !== "object") return found;
  if (node.type === "integer") found.push({ path, node });
  for (const [key, value] of Object.entries(node)) integerNodes(value, `${path}.${key}`, found);
  return found;
}

test("every published schema bounds every integer field, and the bound is the safe-integer range", () => {
  for (const [name, schema] of PUBLISHED) {
    const nodes = integerNodes(schema, "", []);
    for (const { path, node } of nodes) {
      assert.ok(
        typeof node.maximum === "number" || typeof node.exclusiveMaximum === "number",
        `${name}${path}: an integer with no upper bound is accepted by the schema and refused by the validator`
      );
      const upper = node.maximum ?? node.exclusiveMaximum - 1;
      assert.ok(
        upper <= KERNEL_SAFE_INTEGER_MAX,
        `${name}${path}: upper bound ${upper} is past what the canonical form prints identically in every runtime`
      );
      assert.ok(
        typeof node.minimum === "number" || typeof node.exclusiveMinimum === "number",
        `${name}${path}: the validator requires an integer >= 0 or 1; the schema must say so too`
      );
      const lower = node.minimum ?? node.exclusiveMinimum + 1;
      assert.ok(lower >= KERNEL_SAFE_INTEGER_MIN, `${name}${path}: lower bound ${lower} is below the safe range`);
    }
  }
});

test("a value one past the published bound is refused by ajv and by the validator alike", () => {
  const past = KERNEL_SAFE_INTEGER_MAX + 1;
  const roundState = { ...readFixture("convergence.ok-01.json").input, round: past };
  const validateRound = ajv.compile(CONVERGENCE_ROUND_STATE_JSON_SCHEMA);
  assert.equal(validateRound(roundState), false, `ajv accepted round ${past}: ${JSON.stringify(validateRound.errors)}`);
  assert.throws(() => parseRoundState(roundState), /Too big|safe/i);

  const entry = {
    entryId: newDecisionEntryId(),
    sequence: past,
    prevEntryHash: "",
    summary: "s",
    outcome: "pass",
    createdAt: "2026-11-07T00:00:00.000Z"
  };
  const validateEntry = ajv.compile(DECISION_LOG_ENTRY_JSON_SCHEMA);
  assert.equal(validateEntry(entry), false, "ajv accepted an unsafe sequence");
  assert.throws(() => parseDecisionLogEntry(entry));

  const report = { ...readFixture("invariant-report.ok-01.json").input, durationMs: past };
  const validateReport = ajv.compile(INVARIANT_REPORT_JSON_SCHEMA);
  assert.equal(validateReport(report), false, "ajv accepted an unsafe durationMs");
  assert.throws(() => parseInvariantReport(report));

  const pack = JSON.parse(JSON.stringify(readFixture("evidence-pack.ok-01.json")));
  pack.signals.axEvent.nodeCount = past;
  const validatePack = ajv.compile(EVIDENCE_PACK_JSON_SCHEMA);
  assert.equal(validatePack(pack), false, "ajv accepted an unsafe nodeCount");
  assert.throws(() => parseEvidencePack(pack));
});

test("the maximum itself is still accepted on both sides", () => {
  const at = { ...readFixture("convergence.ok-01.json").input, round: KERNEL_SAFE_INTEGER_MAX };
  assert.equal(ajv.compile(CONVERGENCE_ROUND_STATE_JSON_SCHEMA)(at), true);
  assert.equal(parseRoundState(at).round, KERNEL_SAFE_INTEGER_MAX);
});

test("the rules JSON Schema genuinely cannot state are written down where a reader will look", () => {
  // These are the divergences that remain — they are not mistakes, and an
  // implementation coded from the schema alone has to be told to add them.
  const notes = PUBLISHED.map(([name, schema]) => [name, String(schema.description ?? "")]);
  const mustState = [
    ["decision-log-entry", /payload/i],
    ["evidence-pack", /non-finite|NaN/i],
    ["provider-registration", /uniqueItems/i],
    ["reverification-request", /uniqueItems/i]
  ];
  for (const [name, pattern] of mustState) {
    const description = notes.find(([entry]) => entry === name)?.[1] ?? "";
    assert.match(
      description,
      pattern,
      `${name}: a validator-only rule is undocumented, so a second implementation will not reproduce it`
    );
  }
});
