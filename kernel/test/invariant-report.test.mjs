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
