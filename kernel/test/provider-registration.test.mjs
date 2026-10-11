import assert from "node:assert/strict";
import { test } from "node:test";

import Ajv2020 from "ajv/dist/2020.js";

import {
  KernelProviderError,
  KernelSchemaError,
  PROVIDER_CODES,
  PROVIDER_REGISTRATION_JSON_SCHEMA,
  PROVIDER_REGISTRATION_SCHEMA_ID,
  PROVIDER_SCHEMA_VERSION,
  ProviderRegistrationSchema,
  emptyProviderRegistry,
  parseProviderRegistration,
  providerIdsInCommon,
  registerProvider,
  requireMethod,
  resolveProvider
} from "../dist/index.js";
import { readFixture } from "./helpers.mjs";

/**
 * Provider registration is the metadata half of scenario 5: who offers which judgement,
 * and what they need to do it. The registry functions are where the two-harness accident
 * is actually prevented — a silent override, or a lookup that guesses — so they get named
 * negative controls here rather than only a shape test.
 */
const ajv = new Ajv2020({ allErrors: true });
const validate = ajv.compile(PROVIDER_REGISTRATION_JSON_SCHEMA);
const fixture = readFixture("provider-registration.ok-01.json");

function registryOf(providers) {
  return providers.reduce((registry, provider) => registerProvider(registry, provider), emptyProviderRegistry());
}

test("the published schema id and version label agree with the module", () => {
  assert.equal(PROVIDER_REGISTRATION_JSON_SCHEMA.$id, PROVIDER_REGISTRATION_SCHEMA_ID);
  assert.equal(PROVIDER_REGISTRATION_JSON_SCHEMA.properties.schemaVersion.const, PROVIDER_SCHEMA_VERSION);
  assert.equal(fixture.input.schemaVersion, PROVIDER_SCHEMA_VERSION);
});

test("the engine's own registration is accepted by both sides", () => {
  assert.equal(validate(fixture.input), true, JSON.stringify(validate.errors));
  const provider = parseProviderRegistration(fixture.input);
  assert.equal(provider.id, "glasspane-engine-ae");
  assert.equal(provider.kind, "ae-diagnosis");
  assert.deepEqual(
    provider.methods.map((method) => method.name),
    fixture.expectedMethods
  );
});

test("prerequisites name signals the evidence pack actually carries", () => {
  // A `requires` list that names nothing real is decoration. These are
  // `SignalsSchema` keys rendered kebab-case, so a consumer can check them
  // against a pack rather than against prose.
  const provider = parseProviderRegistration(fixture.input);
  const known = new Set(["ax-event", "handler-probe", "state-diff", "pixel-diff", "responsiveness", "crash", "attribution", "circuit-breaker"]);
  for (const method of provider.methods) {
    for (const requirement of method.requires) {
      assert.ok(known.has(requirement), `${method.name} requires ${requirement}, which is not contract vocabulary`);
    }
  }
});

for (const item of fixture.cases) {
  if (item.expect === "accepted") {
    test(`${item.name} is accepted by both sides`, () => {
      assert.equal(validate(item.input), true, JSON.stringify(validate.errors));
      assert.doesNotThrow(() => parseProviderRegistration(item.input));
    });
    continue;
  }
  test(`${item.name} is refused`, () => {
    assert.throws(
      () => parseProviderRegistration(item.input),
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
    if (item.jsonSchemaAccepts) {
      // Documented divergence: JSON Schema compares whole objects for `uniqueItems`,
      // so method-name uniqueness lives on the validator side only.
      assert.equal(validate(item.input), true, "this case is the schema-vs-validator divergence; ajv must accept it");
    } else {
      assert.equal(validate(item.input), false, `ajv should also refuse ${item.name}`);
    }
  });
}

test("registering twice under one id is refused, not an override", () => {
  const registry = registryOf(fixture.registry.glasspane);
  const [first] = fixture.registry.glasspane;
  assert.throws(
    () => registerProvider(registry, first),
    (error) => {
      assert.ok(error instanceof KernelProviderError, `expected a KernelProviderError, got ${error}`);
      assert.equal(error.code, PROVIDER_CODES.duplicateId);
      assert.equal(error.providerId, first.id);
      assert.ok(error.remedy.length > 0, "the caller must be able to act without reading the source");
      return true;
    }
  );
});

test("a registration is replaced whole or not at all", () => {
  const registry = registryOf(fixture.registry.glasspane);
  const before = Object.keys(registry).sort();
  const [first] = fixture.registry.glasspane;
  try {
    registerProvider(registry, { ...first, version: "9.9.9" });
  } catch {
    // The rejected attempt must not have touched anything.
    assert.deepEqual(Object.keys(registry).sort(), before);
    assert.equal(resolveProvider(registry, first.id).version, first.version);
    return;
  }
  assert.fail("re-registering an id should have been refused");
});

test("resolution refuses instead of guessing", () => {
  const registry = registryOf(fixture.registry.glasspane);
  assert.throws(
    () => resolveProvider(registry, "engine-ae"),
    (error) => {
      assert.ok(error instanceof KernelProviderError);
      assert.equal(error.code, PROVIDER_CODES.unknown);
      // The remedy names what is actually registered, so a typo is self-correcting.
      assert.ok(error.remedy.includes("glasspane-engine-ae"), error.remedy);
      return true;
    }
  );
  // A single registered provider is still not a default.
  const alone = registerProvider(emptyProviderRegistry(), fixture.input);
  assert.throws(() => resolveProvider(alone, "anything-else"), KernelProviderError);
});

test("asking a provider for a method it does not offer names what it does", () => {
  const registry = registryOf(fixture.registry.glasspane);
  const method = requireMethod(registry, "glasspane-engine-ae", "diagnose");
  assert.deepEqual(method.requires, ["ax-event", "attribution", "circuit-breaker"]);
  assert.throws(
    () => requireMethod(registry, "glasspane-engine-ae", "diagnose-pixel"),
    (error) => {
      assert.ok(error instanceof KernelProviderError);
      assert.equal(error.code, PROVIDER_CODES.missingMethod);
      assert.ok(error.remedy.includes("diagnose"), error.remedy);
      return true;
    }
  );
});

test("two harnesses with disjoint ids read as disjoint", () => {
  const glasspane = registryOf(fixture.registry.glasspane);
  const iterate = registryOf(fixture.registry.iterate);
  assert.deepEqual(providerIdsInCommon(glasspane, iterate), fixture.registry.idsInCommon);
});

test("the collision case is caught, and reported in a stable order", () => {
  const a = registryOf(fixture.registry.collision.a);
  const b = registryOf(fixture.registry.collision.b);
  const common = providerIdsInCommon(a, b);
  assert.deepEqual(common, fixture.registry.collision.expect);
  // Same id, different prerequisites: exactly the state where "the AE provider"
  // means one thing in each product and both look satisfied.
  assert.deepEqual(requireMethod(a, "glasspane-ae", "diagnose").requires, ["ax-event"]);
  assert.deepEqual(requireMethod(b, "glasspane-ae", "diagnose").requires, ["evidence-pack"]);
});

test("an empty registry is a value, not an error", () => {
  const empty = emptyProviderRegistry();
  assert.deepEqual(Object.keys(empty), []);
  assert.deepEqual(providerIdsInCommon(empty, empty), []);
  assert.throws(() => resolveProvider(empty, "glasspane-engine-ae"), KernelProviderError);
});

test("a provider wider than the contract refuses rather than truncating", () => {
  const wide = {
    ...fixture.input,
    methods: Array.from({ length: 33 }, (_, i) => ({ name: `diagnose-${i}`, requires: [] }))
  };
  assert.throws(() => parseProviderRegistration(wide), KernelSchemaError);
  assert.equal(validate(wide), false);
  const atLimit = { ...wide, methods: wide.methods.slice(0, 32) };
  assert.equal(ProviderRegistrationSchema.parse(atLimit).methods.length, 32);
});
