import assert from "node:assert/strict";
import { test } from "node:test";

import Ajv2020 from "ajv/dist/2020.js";

import {
  KernelSchemaError,
  RUN_PLAN_JSON_SCHEMA,
  RUN_PLAN_SCHEMA_ID,
  RUN_PLAN_SCHEMA_VERSION,
  parseRunPlan,
  plannedIds,
  runPlanDigest
} from "../dist/index.js";
import { readFixture } from "./helpers.mjs";

/**
 * The run plan is the missing input to dimension coverage: `dimensionContext` refuses to
 * invent a plan, and today nobody hands it one, so the coverage line renders "0 verified"
 * in a real session no matter how much was verified. This is that contract.
 *
 * The digest matters as much as the shape: a ledger line has to be able to say which plan
 * a run was held to, and a reader has to be able to notice the plan changed mid-run. It is
 * pinned here against a value derived independently (the fixture's `comment` states the
 * canonical-JSON rules; a Python pass produced the expected digest from those rules), so the
 * implementation is not its own oracle.
 */
const ajv = new Ajv2020({ allErrors: true });
const validate = ajv.compile(RUN_PLAN_JSON_SCHEMA);
const fixture = readFixture("run-plan.ok-01.json");

test("the published schema id and version label agree with the module", () => {
  assert.equal(RUN_PLAN_JSON_SCHEMA.$id, RUN_PLAN_SCHEMA_ID);
  assert.equal(RUN_PLAN_JSON_SCHEMA.properties.schemaVersion.const, RUN_PLAN_SCHEMA_VERSION);
  assert.equal(fixture.input.schemaVersion, RUN_PLAN_SCHEMA_VERSION);
});

test("the real config vocabulary is accepted by both sides", () => {
  assert.equal(validate(fixture.input), true, JSON.stringify(validate.errors));
  const plan = parseRunPlan(fixture.input);
  assert.deepEqual(plannedIds(plan), fixture.expectedIds);
  // Planned order belongs to the caller. Sorted output here would mean the two
  // shells' coverage lines read in different orders than the plan the human wrote.
  assert.deepEqual(
    plan.dimensions.map((dimension) => dimension.id),
    ["correctness", "security", "performance", "architecture", "style-tests", "tech-debt", "spec-compliance", "frontend-backend", "ui-ux"]
  );
});

test("the digest matches the independently derived one, and is bound to the content", () => {
  const plan = parseRunPlan(fixture.input);
  assert.equal(runPlanDigest(plan), fixture.expectedDigest);
  assert.match(fixture.expectedDigest, /^rp_[0-9a-f]{64}$/);

  const reordered = parseRunPlan({ ...fixture.input, dimensions: [...fixture.input.dimensions].reverse() });
  assert.notEqual(runPlanDigest(reordered), fixture.expectedDigest, "plan order is part of the digest");

  const relabelled = parseRunPlan({
    ...fixture.input,
    dimensions: fixture.input.dimensions.map((d, i) => (i === 0 ? { ...d, label: "correctness?" } : d))
  });
  assert.notEqual(runPlanDigest(relabelled), fixture.expectedDigest, "a label is part of the digest");

  const unsourced = parseRunPlan({ schemaVersion: fixture.input.schemaVersion, dimensions: fixture.input.dimensions });
  assert.notEqual(runPlanDigest(unsourced), fixture.expectedDigest, "the declared source is part of the digest");
});

for (const item of fixture.cases) {
  if (item.expect === "accepted") {
    test(`${item.name} is accepted by both sides`, () => {
      assert.equal(validate(item.input), true, JSON.stringify(validate.errors));
      const plan = parseRunPlan(item.input);
      assert.match(runPlanDigest(plan), new RegExp(`^${item.digestPrefix}`));
    });
    continue;
  }
  test(`${item.name} is refused`, () => {
    assert.throws(
      () => parseRunPlan(item.input),
      (error) => {
        assert.ok(error instanceof KernelSchemaError, `expected a KernelSchemaError, got ${error}`);
        const paths = error.issues.map((issue) => issue.path);
        assert.ok(paths.includes(item.path), `refused, but not at ${JSON.stringify(item.path)}: ${JSON.stringify(paths)}`);
        if (item.messageIncludes) {
          // The two validators locate an unknown key differently (zod puts it on the
          // object, ajv on the key), so the shared fact is the message.
          assert.ok(
            error.issues.some((issue) => String(issue.message).includes(item.messageIncludes)),
            `refused, but no issue mentions ${item.messageIncludes}: ${JSON.stringify(error.issues)}`
          );
        }
        return true;
      },
      `${item.name} should have been refused`
    );
    if (item.jsonSchemaAccepts) {
      // Documented, deliberate divergence: JSON Schema cannot express id-level
      // uniqueness, so the validator is the stricter side here. Asserting the
      // mismatch is what keeps it from being "fixed" by deleting one of the two.
      assert.equal(validate(item.input), true, "this case is the schema-vs-validator divergence; ajv must accept it");
    } else {
      assert.equal(validate(item.input), false, `ajv should also refuse ${item.name}`);
    }
  });
}

test("a plan wider than the contract refuses rather than truncating", () => {
  const wide = {
    schemaVersion: RUN_PLAN_SCHEMA_VERSION,
    dimensions: Array.from({ length: 65 }, (_, i) => ({ id: `dimension-${i}` }))
  };
  assert.throws(() => parseRunPlan(wide), KernelSchemaError);
  assert.equal(validate(wide), false);
  const atLimit = { schemaVersion: RUN_PLAN_SCHEMA_VERSION, dimensions: wide.dimensions.slice(0, 64) };
  assert.equal(parseRunPlan(atLimit).dimensions.length, 64);
});
