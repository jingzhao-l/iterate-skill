import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DIMENSION_CONTEXT_CODES,
  KernelDimensionError,
  dimensionContext,
  formatDimensionContext,
  parseDimensionContext,
  parseDimensionContextInput,
  KernelSchemaError
} from "../dist/index.js";
import { readFixture } from "./helpers.mjs";

/** The nine ids the iterate config owns; the kernel validates their shape, not this list. */
const CANONICAL = [
  "correctness",
  "security",
  "performance",
  "architecture",
  "style-tests",
  "tech-debt",
  "spec-compliance",
  "frontend-backend",
  "ui-ux"
];

function plan(...ids) {
  return ids.map((id) => ({ id }));
}

test("the nine canonical ids parse and account for correctly", () => {
  const context = dimensionContext({
    planned: plan(...CANONICAL),
    recorded: { correctness: { decisions: 4 }, security: { decisions: 1 } }
  });

  assert.equal(context.totals.planned, 9);
  assert.equal(context.totals.verified, 2);
  assert.equal(context.totals.unverified, 7);
  assert.equal(context.totals.unplanned, 0);
  assert.equal(context.totals.decisions, 5);
  // verified + unverified === planned is the invariant a consumer may assert.
  assert.equal(context.totals.verified + context.totals.unverified, context.totals.planned);
  // Planned order is the caller's, not sorted: the report should read like the plan.
  assert.deepEqual(
    context.planned.map((entry) => entry.id),
    CANONICAL
  );
});

test("an absent recorded id and a recorded zero are the same fact", () => {
  const absent = dimensionContext({ planned: plan("security"), recorded: {} });
  const zero = dimensionContext({ planned: plan("security"), recorded: { security: { decisions: 0 } } });

  assert.equal(absent.planned[0].status, "unverified");
  assert.equal(zero.planned[0].status, "unverified");
  // The evidence is normalised to the same shape so a consumer reading
  // `.evidence.decisions` does not have to handle undefined.
  assert.deepEqual(absent.planned[0].evidence, { decisions: 0 });
  assert.deepEqual(zero.planned[0].evidence, { decisions: 0 });
  assert.deepEqual(absent, zero);
});

test("a recorded dimension the run never planned is reported, not dropped", () => {
  const context = dimensionContext({
    planned: plan("correctness"),
    recorded: { correctness: { decisions: 2 }, "not-a-real-dimension": { decisions: 7 } }
  });

  assert.equal(context.totals.planned, 1);
  assert.equal(context.totals.unplanned, 1);
  // The unplanned decision still counts: totals.decisions is every decision
  // recorded, counted once — not only the ones the plan predicted.
  assert.equal(context.totals.decisions, 9);
  assert.equal(context.unplanned[0].id, "not-a-real-dimension");
  assert.equal(context.unplanned[0].status, "unplanned");
});

test("a duplicate planned id throws rather than silently collapsing", () => {
  assert.throws(
    () => dimensionContext({ planned: plan("security", "security"), recorded: {} }),
    (error) => {
      assert.ok(error instanceof KernelDimensionError);
      assert.equal(error.code, DIMENSION_CONTEXT_CODES.duplicate);
      assert.equal(error.dimension, "security");
      // code + message + remedy: a caller can act without reading the source.
      assert.match(error.message, /KERNEL_E_DIMENSION_DUPLICATE/);
      assert.ok(error.remedy.length > 0);
      return true;
    }
  );
});

test("an id that is not kebab-case is refused — the kernel does not enumerate ids", () => {
  for (const bad of ["Security", "correctness_", "-leading", "with space", "double--dash"]) {
    assert.throws(
      () => parseDimensionContextInput({ planned: [{ id: bad }], recorded: {} }),
      KernelSchemaError,
      `should refuse ${JSON.stringify(bad)}`
    );
  }
});

test("label and focus are carried through verbatim and stay optional", () => {
  const context = dimensionContext({
    planned: [{ id: "ui-ux", label: "UI/UX", focus: "Layout, focus order" }, { id: "security" }],
    recorded: { "ui-ux": { decisions: 1 } }
  });

  assert.equal(context.planned[0].label, "UI/UX");
  assert.equal(context.planned[0].focus, "Layout, focus order");
  assert.equal("label" in context.planned[1], false);
  assert.equal("focus" in context.planned[1], false);
});

test("the formatted line names what was not checked", () => {
  const context = dimensionContext({
    planned: plan("correctness", "security", "ui-ux"),
    recorded: { correctness: { decisions: 4 }, "ui-ux": { decisions: 1 }, "tech-debt": { decisions: 2 } }
  });

  assert.equal(
    formatDimensionContext(context),
    "2/3 dimensions verified, 1 unverified (security), 1 unplanned (tech-debt), 7 decisions"
  );
});

test("a run where nothing was verified still says so", () => {
  const line = formatDimensionContext(
    dimensionContext({ planned: plan("correctness", "security"), recorded: {} })
  );

  // The line a naive reporter would omit entirely is the one that matters most.
  assert.equal(line, "0/2 dimensions verified, 2 unverified (correctness, security), 0 decisions");
});

test("a single decision is singular", () => {
  const line = formatDimensionContext(
    dimensionContext({ planned: plan("security"), recorded: { security: { decisions: 1 } } })
  );

  assert.equal(line, "1/1 dimensions verified, 1 decision");
});

test("parseDimensionContext round-trips a built context", () => {
  const context = dimensionContext({
    planned: plan("correctness", "security"),
    recorded: { correctness: { decisions: 2, operationIds: ["op_1"] } }
  });

  const parsed = parseDimensionContext(JSON.parse(JSON.stringify(context)));
  assert.deepEqual(parsed, context);
  // and the formatter agrees on the re-parsed value
  assert.match(formatDimensionContext(parsed), /1\/2 dimensions verified/);
});

test("an empty plan is refused — 'I reviewed nothing' is not a valid context", () => {
  assert.throws(
    () => parseDimensionContextInput({ planned: [], recorded: {} }),
    KernelSchemaError
  );
});

test("a negative decision count is refused", () => {
  assert.throws(
    () => parseDimensionContextInput({ planned: plan("security"), recorded: { security: { decisions: -1 } } }),
    KernelSchemaError
  );
});

test("a built context satisfies its own schema", () => {
  const context = dimensionContext({
    planned: plan("correctness", "security", "ui-ux"),
    recorded: { correctness: { decisions: 2 }, "tech-debt": { decisions: 1, operationIds: ["op_a", "op_b"] } }
  });

  // Guards the one thing a pure function can get wrong: emitting a shape the
  // published schema would then reject in a consumer.
  assert.doesNotThrow(() => parseDimensionContext(context));
});


test("the cross-implementation fixture reproduces byte for byte", () => {
  const fixture = readFixture("dimension-context.ok-01.json");
  const context = dimensionContext(parseDimensionContextInput(fixture.input));

  assert.deepEqual(context, fixture.expected);
  assert.equal(formatDimensionContext(context), fixture.expectedLine);
  // And the expected block satisfies the published schema, so the fixture
  // cannot encode a shape the kernel would refuse in a consumer.
  assert.doesNotThrow(() => parseDimensionContext(fixture.expected));
  // 7 verified + 2 unverified === 9 planned: the invariant the fixture asserts
  // by construction, checked so a future edit to the fixture cannot break it.
  assert.equal(context.totals.verified + context.totals.unverified, context.totals.planned);
});


test("unplanned ids are sorted so two implementations emit the same bytes", () => {
  const first = dimensionContext({
    planned: plan("security"),
    recorded: { zeta: { decisions: 1 }, alpha: { decisions: 1 }, mu: { decisions: 1 } }
  });
  const second = dimensionContext({
    planned: plan("security"),
    recorded: { mu: { decisions: 1 }, zeta: { decisions: 1 }, alpha: { decisions: 1 } }
  });

  assert.deepEqual(
    first.unplanned.map((entry) => entry.id),
    ["alpha", "mu", "zeta"]
  );
  // Insertion order of the record must not change the result.
  assert.deepEqual(first, second);
});
