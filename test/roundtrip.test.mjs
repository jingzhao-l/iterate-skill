import assert from "node:assert/strict";
import { test } from "node:test";
import Ajv2020 from "ajv/dist/2020.js";
import {
  DECISION_LOG_ENTRY_JSON_SCHEMA,
  EVIDENCE_PACK_JSON_SCHEMA,
  RECIPE_CONFIG_JSON_SCHEMA,
  parseDecisionLogEntry,
  parseEvidencePack,
  parseRecipeConfig
} from "../dist/index.js";
import { canonical, readFixture, rawFixture } from "./helpers.mjs";

const ajv = new Ajv2020({ allErrors: true });

/**
 * C35 (kernel side): for every truth fixture, ajv validates it, zod decodes
 * it, and the decoded value re-encoded canonically equals the fixture's own
 * canonical form. The engine-side XCTest suite runs the mirror image of this
 * test against the same files; together they pin the cross-language contract.
 */
const FIXTURE_MATRIX = [
  {
    file: "evidence-pack.ok-01.json",
    schema: EVIDENCE_PACK_JSON_SCHEMA,
    parse: parseEvidencePack
  },
  {
    file: "evidence-pack.ok-02.json",
    schema: EVIDENCE_PACK_JSON_SCHEMA,
    parse: parseEvidencePack
  },
  {
    file: "decision-log-entry.ok-01.json",
    schema: DECISION_LOG_ENTRY_JSON_SCHEMA,
    parse: parseDecisionLogEntry
  },
  {
    file: "recipe-config.ok-01.json",
    schema: RECIPE_CONFIG_JSON_SCHEMA,
    parse: parseRecipeConfig
  }
];

for (const { file, schema, parse } of FIXTURE_MATRIX) {
  test(`roundtrip ${file}: ajv validate -> zod parse -> canonical equals fixture canonical`, () => {
    const raw = rawFixture(file);
    assert.ok(raw.trim().length > 0, "fixture must not be empty");

    const fixtureValue = readFixture(file);
    const validate = ajv.compile(schema);
    assert.equal(validate(fixtureValue), true, `ajv: ${JSON.stringify(validate.errors)}`);

    const decoded = parse(fixtureValue);
    assert.equal(
      canonical(decoded),
      canonical(fixtureValue),
      "canonical roundtrip mismatch"
    );
  });
}

test("canonical helper sorts keys and strips whitespace deterministically", () => {
  const a = { b: 1, a: { d: [3, 2], c: null } };
  const b = { a: { c: null, d: [3, 2] }, b: 1 };
  assert.equal(canonical(a), canonical(b));
  assert.equal(canonical(a), '{"a":{"c":null,"d":[3,2]},"b":1}');
});

test("canonical helper delegates numbers to shortest roundtrip form", () => {
  assert.equal(canonical({ n: 0.023 }), '{"n":0.023}');
  assert.equal(canonical({ n: 12 }), '{"n":12}');
});
