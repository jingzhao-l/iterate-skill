import assert from "node:assert/strict";
import { test } from "node:test";

import Ajv2020 from "ajv/dist/2020.js";

import {
  CONVERGENCE_REASONS,
  CONVERGENCE_ROUND_STATE_JSON_SCHEMA,
  CONVERGENCE_ROUND_STATE_SCHEMA_ID,
  CONVERGENCE_SCHEMA_VERSION,
  KernelSchemaError,
  ConvergenceDecisionSchema,
  convergenceDecision,
  parseRoundState
} from "../dist/index.js";
import { canonical } from "./helpers.mjs";
import { readFixture } from "./helpers.mjs";

/**
 * The convergence rules are the one place the loop's "what next" is decided, and the
 * whole reason it is in the kernel is that two harnesses with private ideas of "done"
 * diverge silently. So the guard here is completeness of the precedence table: every
 * reason the implementation can give must be named by a case, and each case's expected
 * decision comes from the rule text in the fixture rather than from this code.
 */
const ajv = new Ajv2020({ allErrors: true });
const validate = ajv.compile(CONVERGENCE_ROUND_STATE_JSON_SCHEMA);
const fixture = readFixture("convergence.ok-01.json");

test("the published schema id and version label agree with the module", () => {
  assert.equal(CONVERGENCE_ROUND_STATE_JSON_SCHEMA.$id, CONVERGENCE_ROUND_STATE_SCHEMA_ID);
  assert.equal(CONVERGENCE_ROUND_STATE_JSON_SCHEMA.properties.schemaVersion.const, CONVERGENCE_SCHEMA_VERSION);
  assert.equal(fixture.input.schemaVersion, CONVERGENCE_SCHEMA_VERSION);
});

test("the reference round is accepted by both sides and decides as the rule text says", () => {
  assert.equal(validate(fixture.input), true, JSON.stringify(validate.errors));
  const state = parseRoundState(fixture.input);
  assert.deepEqual(canonical(convergenceDecision(state)), canonical(fixture.expectedDecision));
});

for (const item of fixture.cases) {
  if (item.expect === "refused") {
    test(`${item.name} is refused`, () => {
      assert.throws(
        () => convergenceDecision(item.state),
        (error) => {
          assert.ok(error instanceof KernelSchemaError, `expected a KernelSchemaError, got ${error}`);
          const paths = error.issues.map((issue) => issue.path);
          assert.ok(paths.includes(item.path), `refused, but not at ${JSON.stringify(item.path)}: ${JSON.stringify(paths)}`);
          if (item.messageIncludes) {
            assert.ok(
              error.issues.some((issue) => String(issue.message).includes(item.messageIncludes)),
              `refused, but no issue mentions ${item.messageIncludes}: ${JSON.stringify(error.issues)}`
            );
          }
          return true;
        },
        `${item.name} should have been refused`
      );
      assert.equal(validate(item.state), false, `ajv should also refuse ${item.name}`);
    });
    continue;
  }
  test(`${item.name} decides ${item.expect.action}/${item.expect.reason}`, () => {
    assert.equal(validate(item.state), true, JSON.stringify(validate.errors));
    const decision = convergenceDecision(item.state);
    assert.deepEqual(decision, item.expect);
    // A decision is itself a value both harnesses may need to log.
    assert.doesNotThrow(() => ConvergenceDecisionSchema.parse(decision));
  });
}

test("every reason the rules can give has a case, so no branch is untested", () => {
  const covered = new Set(
    fixture.cases.filter((item) => item.expect !== "refused").map((item) => item.expect.reason)
  );
  covered.add(fixture.expectedDecision.reason);
  const uncovered = Object.values(CONVERGENCE_REASONS).filter((reason) => !covered.has(reason));
  assert.deepEqual(uncovered, [], `precedence branches with no fixture case: ${uncovered.join(", ")}`);
});

test("every action the rules can give has a case", () => {
  const covered = new Set(
    fixture.cases.filter((item) => item.expect !== "refused").map((item) => item.expect.action)
  );
  covered.add(fixture.expectedDecision.action);
  const uncovered = ["fix", "verify", "converged", "halt"].filter((action) => !covered.has(action));
  assert.deepEqual(uncovered, [], `actions with no fixture case: ${uncovered.join(", ")}`);
});

test("the decision echoes the round it judged rather than renumbering it", () => {
  const decision = convergenceDecision({
    round: 5,
    maxRounds: 7,
    invariantState: "pass",
    openFindings: 0,
    evidenceComplete: true,
    breakerLevel: 0
  });
  assert.equal(decision.round, 5);
  assert.equal(decision.maxRounds, 7);
});

test("an unmeasured invariant state never reads as converged", () => {
  // The asymmetry this contract exists to close: a loop that treats "could not look"
  // as "looks fine" stops early and reports a clean result it never earned.
  const unmeasured = convergenceDecision({
    round: 1,
    maxRounds: 7,
    invariantState: "unmeasured",
    openFindings: 0,
    evidenceComplete: true,
    breakerLevel: 0
  });
  assert.equal(unmeasured.action, "verify");
  assert.notEqual(unmeasured.action, "converged");
});

test("a schema version is optional but a wrong one is refused", () => {
  const { schemaVersion, ...rest } = fixture.input;
  assert.equal(schemaVersion, CONVERGENCE_SCHEMA_VERSION);
  assert.equal(convergenceDecision(rest).action, "converged");
  assert.throws(
    () => convergenceDecision({ ...rest, schemaVersion: "iterate.convergence/0.2" }),
    KernelSchemaError
  );
});
