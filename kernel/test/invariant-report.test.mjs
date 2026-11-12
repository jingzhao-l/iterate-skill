import assert from "node:assert/strict";
import { test } from "node:test";

import Ajv2020 from "ajv/dist/2020.js";

import {
  INVARIANT_CHECK_MAX,
  INVARIANT_REPORT_JSON_SCHEMA,
  INVARIANT_REPORT_SCHEMA_ID,
  INVARIANT_REPORT_SCHEMA_VERSION,
  KernelSchemaError,
  REVERIFICATION_SCHEMA_VERSION,
  failingChecks,
  invariantReportDigest,
  parseInvariantReport,
  parseReverificationRequest,
  reVerificationRequestFrom
} from "../dist/index.js";
import { REVERIFICATION_REQUEST_JSON_SCHEMA } from "../dist/schemas.js";
import { readFixture } from "./helpers.mjs";

/**
 * The invariant report is the artifact that lets one harness tell the other "this
 * claim broke" (5.7 R40 scenario 1). Everything the re-verification depends on is
 * decided here, so the rule this file guards hardest is the contradiction rule:
 * a report may not call itself a pass while carrying a failed check.
 *
 * The digest is pinned against values derived independently (see the fixture's
 * `comment` for the rules and the capture they came from), so the implementation
 * is not its own oracle.
 */
const ajv = new Ajv2020({ allErrors: true });
const validateReport = ajv.compile(INVARIANT_REPORT_JSON_SCHEMA);
const validateRequest = ajv.compile(REVERIFICATION_REQUEST_JSON_SCHEMA);
const fixture = readFixture("invariant-report.ok-01.json");

test("the published schema ids and version labels agree with the module", () => {
  assert.equal(INVARIANT_REPORT_JSON_SCHEMA.$id, INVARIANT_REPORT_SCHEMA_ID);
  assert.equal(INVARIANT_REPORT_JSON_SCHEMA.properties.schemaVersion.const, INVARIANT_REPORT_SCHEMA_VERSION);
  assert.equal(REVERIFICATION_REQUEST_JSON_SCHEMA.properties.schemaVersion.const, REVERIFICATION_SCHEMA_VERSION);
  assert.equal(fixture.input.schemaVersion, INVARIANT_REPORT_SCHEMA_VERSION);
});

test("a real failing run is accepted by both sides and its failing checks are named", () => {
  assert.equal(validateReport(fixture.input), true, JSON.stringify(validateReport.errors));
  const report = parseInvariantReport(fixture.input);
  assert.deepEqual(failingChecks(report), fixture.expectedFailingChecks);
  assert.equal(invariantReportDigest(report), fixture.expectedDigest);
  assert.match(fixture.expectedDigest, /^iv_[0-9a-f]{64}$/);
});

test("the digest is bound to the content, not just the verdict", () => {
  const report = parseInvariantReport(fixture.input);
  assert.equal(invariantReportDigest(report), fixture.expectedDigest);

  const dropped = parseInvariantReport({
    ...fixture.input,
    checks: fixture.input.checks.slice(0, -1)
  });
  assert.notEqual(invariantReportDigest(dropped), fixture.expectedDigest, "a dropped check changes the digest");

  const relabelled = parseInvariantReport({
    ...fixture.input,
    checks: fixture.input.checks.map((check, i) => (i === 0 ? { ...check, detail: "exists" } : check))
  });
  assert.notEqual(invariantReportDigest(relabelled), fixture.expectedDigest, "a detail is part of the digest");

  const rescalated = parseInvariantReport({ ...fixture.input, outcome: "error" });
  assert.notEqual(invariantReportDigest(rescalated), fixture.expectedDigest, "the verdict is part of the digest");
});

test("a passing report digests independently of the failing one", () => {
  assert.equal(validateReport(fixture.passInput), true, JSON.stringify(validateReport.errors));
  assert.equal(invariantReportDigest(parseInvariantReport(fixture.passInput)), fixture.passDigest);
  assert.notEqual(fixture.passDigest, fixture.expectedDigest);
});

for (const item of fixture.cases) {
  if (item.expect === "accepted") {
    test(`${item.name} is accepted by both sides`, () => {
      assert.equal(validateReport(item.input), true, JSON.stringify(validateReport.errors));
      const report = parseInvariantReport(item.input);
      if (item.digest) {
        assert.equal(invariantReportDigest(report), item.digest);
      }
      if (item.failingChecks) {
        assert.deepEqual(failingChecks(report), item.failingChecks);
      }
    });
    continue;
  }
  test(`${item.name} is refused by both sides`, () => {
    assert.throws(
      () => parseInvariantReport(item.input),
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
    // Both sides must refuse the contradiction: a schema-only consumer that
    // accepted `pass` over a failed check would let a loop report a convergence
    // it never earned, which is the accident this contract exists to prevent.
    assert.equal(validateReport(item.input), false, `ajv should also refuse ${item.name}`);
  });
}

test("the contradiction rule is checked in both directions", () => {
  const passing = parseInvariantReport(fixture.passInput);
  assert.deepEqual(failingChecks(passing), []);

  const report = parseInvariantReport(fixture.input);
  const flippedToPass = { ...report, outcome: "pass" };
  assert.throws(() => parseInvariantReport(flippedToPass), KernelSchemaError);

  const everyCheckOk = {
    schemaVersion: INVARIANT_REPORT_SCHEMA_VERSION,
    outcome: "fail",
    checks: report.checks.map((check) => ({ ...check, ok: true }))
  };
  assert.throws(() => parseInvariantReport(everyCheckOk), KernelSchemaError);
});

test("an unmeasured run is `error` and is not a finding", () => {
  assert.equal(validateReport(fixture.errorInput), true, JSON.stringify(validateReport.errors));
  const report = parseInvariantReport(fixture.errorInput);
  assert.equal(report.outcome, "error");
  // The digest still pins it, so the ledger can record that nothing was measured.
  assert.equal(invariantReportDigest(report), fixture.errorDigest);
});

test("a pass schedules nothing", () => {
  const request = reVerificationRequestFrom(parseInvariantReport(fixture.passInput), {
    dimensions: ["spec-compliance"]
  });
  assert.equal(request, null, "a passing run must not produce a re-verification to log");
});

test("an error refuses to be laundered into activity", () => {
  assert.throws(
    () => reVerificationRequestFrom(parseInvariantReport(fixture.errorInput), { dimensions: ["spec-compliance"] }),
    (error) => {
      assert.equal(error.name, "KernelReverificationError");
      assert.equal(error.code, "KERNEL_E_REVERIFY_UNMEASURED");
      assert.ok(error.remedy.length > 0, "the caller must be able to act without reading the source");
      return true;
    }
  );
});

/**
 * `errors.ts` names this function alongside `convergenceDecision` and
 * `registerProvider` as one that validates its own input and raises the same error
 * `parse.ts` raises. It digests the report into a re-verification citation, so a
 * report that is not a contract value must never reach `invariantReportDigest` —
 * otherwise it manufactures an `iv_…` citation over a non-value.
 */
test("a report that is not a contract value is refused, not cited by digest", () => {
  // No `schemaVersion`, no `checks`: `parseInvariantReport` refuses this shape.
  assert.throws(
    () => reVerificationRequestFrom({ outcome: "fail" }, { dimensions: ["spec-compliance"] }),
    (error) => {
      assert.ok(error instanceof KernelSchemaError, `expected a KernelSchemaError, got ${error}`);
      assert.ok(error.issues.some((issue) => issue.path.startsWith("schemaVersion")), `refused, but not at schemaVersion: ${JSON.stringify(error.issues)}`);
      return true;
    },
    "a report with no schemaVersion must be refused"
  );
  // An empty `checks` list violates `.min(1)` even with a `schemaVersion` present.
  assert.throws(
    () => reVerificationRequestFrom(
      { schemaVersion: INVARIANT_REPORT_SCHEMA_VERSION, outcome: "fail", checks: [] },
      { dimensions: ["spec-compliance"] }
    ),
    KernelSchemaError,
    "a report with zero checks must be refused"
  );
});

test("a failure becomes a request that cites the failure by digest", () => {
  const report = parseInvariantReport(fixture.input);
  const request = reVerificationRequestFrom(report, { dimensions: ["spec-compliance", "frontend-backend"] });
  assert.ok(request);
  assert.equal(request.schemaVersion, REVERIFICATION_SCHEMA_VERSION);
  assert.equal(request.trigger.kind, "invariant");
  assert.equal(request.trigger.reportDigest, invariantReportDigest(report));
  assert.deepEqual(request.targets.dimensions, ["spec-compliance", "frontend-backend"]);
  assert.equal(validateRequest(request), true, JSON.stringify(validateRequest.errors));
  assert.deepEqual(parseReverificationRequest(request), request);
});

test("an empty target set is not a re-verification", () => {
  const report = parseInvariantReport(fixture.input);
  assert.throws(
    () => reVerificationRequestFrom(report, {}),
    (error) => {
      assert.ok(error instanceof KernelSchemaError, `expected a KernelSchemaError, got ${error}`);
      return true;
    }
  );
  // Expressed in JSON Schema too, via `anyOf`, so a schema-only consumer refuses it.
  assert.equal(
    validateRequest({
      schemaVersion: REVERIFICATION_SCHEMA_VERSION,
      trigger: { kind: "invariant", reportDigest: invariantReportDigest(report) },
      targets: {}
    }),
    false
  );
});

for (const item of fixture.reverificationCases) {
  const report = parseInvariantReport(fixture.input);
  const request = {
    schemaVersion: REVERIFICATION_SCHEMA_VERSION,
    trigger: { kind: "invariant", reportDigest: invariantReportDigest(report) },
    targets: item.targets
  };
  if (item.expect === "accepted") {
    test(`target set ${item.name} is accepted by both sides`, () => {
      assert.equal(validateRequest(request), true, JSON.stringify(validateRequest.errors));
      const built = reVerificationRequestFrom(report, item.targets);
      assert.ok(built);
      assert.deepEqual(parseReverificationRequest(built), built);
    });
    continue;
  }
  test(`target set ${item.name} is refused`, () => {
    assert.throws(() => reVerificationRequestFrom(report, item.targets), KernelSchemaError);
    assert.equal(validateRequest(request), false, `ajv should also refuse ${item.name}`);
  });
}

test("the request's own digest is not trusted: a malformed citation is refused", () => {
  const report = parseInvariantReport(fixture.input);
  const good = reVerificationRequestFrom(report, { dimensions: ["security"] });
  assert.ok(good);
  for (const bad of ["", "iv_deadbeef", `iv_${"0".repeat(63)}`, `iv_${"Z".repeat(64)}`]) {
    assert.throws(
      () => parseReverificationRequest({ ...good, trigger: { ...good.trigger, reportDigest: bad } }),
      KernelSchemaError,
      `${JSON.stringify(bad)} should not pass as a report digest`
    );
  }
});

test("a report wider than the contract refuses rather than truncating", () => {
  const wide = {
    schemaVersion: INVARIANT_REPORT_SCHEMA_VERSION,
    outcome: "pass",
    checks: Array.from({ length: INVARIANT_CHECK_MAX + 1 }, (_, i) => ({
      name: `ensure:file-${i}`,
      kind: "ensure",
      ok: true
    }))
  };
  assert.throws(() => parseInvariantReport(wide), KernelSchemaError);
  assert.equal(validateReport(wide), false);
  const atLimit = { ...wide, checks: wide.checks.slice(0, INVARIANT_CHECK_MAX) };
  assert.equal(parseInvariantReport(atLimit).checks.length, INVARIANT_CHECK_MAX);
});

/**
 * `uniqueItems` on `targets.dimensions` and `targets.operationIds` is declared in
 * the published schema, and until now only ajv honoured it. A target listed twice
 * is a schedule that one reader runs once and another runs twice, which is exactly
 * the class of disagreement this contract exists to end — so the validator refuses
 * it too, and the two sides are checked against each other here.
 */
test("a target listed twice is refused by the schema and the validator alike", () => {
  const base = structuredClone(fixture.request);
  const cases = [
    ["dimensions", (targets) => ({ ...targets, dimensions: [...targets.dimensions, targets.dimensions[0]] })],
    ["operationIds", (targets) => ({ operationIds: ["op_0123456789ABCDEFGHJKMNPQRT", "op_0123456789ABCDEFGHJKMNPQRT"] })]
  ];
  for (const [name, mutate] of cases) {
    const duplicated = { ...base, targets: mutate(structuredClone(base.targets)) };
    assert.equal(validateRequest(duplicated), false, `ajv accepted a doubled ${name}`);
    assert.throws(
      () => parseReverificationRequest(duplicated),
      (error) => {
        assert.ok(error instanceof KernelSchemaError, `${name}: got ${error}`);
        assert.match(error.message, /listed twice/);
        assert.ok(error.issues.some((issue) => issue.path.startsWith(`targets.${name}`)), `${name}: ${JSON.stringify(error.issues)}`);
        return true;
      },
      name
    );
  }
  const once = { ...base, targets: { dimensions: ["spec-compliance", "security"] } };
  assert.equal(validateRequest(once), true, JSON.stringify(validateRequest.errors));
  assert.equal(parseReverificationRequest(once).targets.dimensions.length, 2);
});
