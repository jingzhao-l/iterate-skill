import assert from "node:assert/strict";
import { test } from "node:test";
import Ajv2020 from "ajv/dist/2020.js";
import {
  KernelSchemaError,
  RECIPE_CONFIG_JSON_SCHEMA,
  RECIPE_MAX_STEPS,
  parseRecipeConfig
} from "../dist/index.js";
import { readFixture } from "./helpers.mjs";

const ajv = new Ajv2020({ allErrors: true });
const validate = ajv.compile(RECIPE_CONFIG_JSON_SCHEMA);

function assertBothSidesAccept(input, label) {
  assert.equal(validate(input), true, `ajv should accept ${label}: ${JSON.stringify(validate.errors)}`);
  assert.doesNotThrow(() => parseRecipeConfig(input), `zod should accept ${label}`);
}

function assertBothSidesReject(input, label) {
  assert.equal(validate(input), false, `ajv should reject ${label}`);
  assert.throws(() => parseRecipeConfig(input), KernelSchemaError, `zod should reject ${label}`);
}

const base = readFixture("recipe-config.ok-01.json");

function withSteps(count) {
  const recipe = structuredClone(base);
  recipe.steps = [];
  for (let index = 0; index < count; index += 1) {
    recipe.steps.push({ kind: "observe", params: {} });
  }
  return recipe;
}

test("four-step smoke recipe fixture passes ajv and zod", () => {
  assertBothSidesAccept(base, "ok-01");
});

test("steps boundary: 0 steps is rejected on both sides", () => {
  assertBothSidesReject(withSteps(0), "0 steps");
});

test("steps boundary: 1 step passes both sides", () => {
  assertBothSidesAccept(withSteps(1), "1 step");
});

test("steps boundary: 64 steps passes both sides", () => {
  assertBothSidesAccept(withSteps(64), "64 steps");
});

test("steps boundary: 65 steps is rejected on both sides", () => {
  assertBothSidesReject(withSteps(65), "65 steps");
});

test("steps boundary max constant matches the schema contract", () => {
  assert.equal(RECIPE_MAX_STEPS, 64);
});

test("negative: invalid step kind is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.steps[0].kind = "snapshot";
  assertBothSidesReject(broken, "kind=snapshot");
});

test("negative: wrong schemaVersion is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.schemaVersion = "glasspane.recipe/0.2";
  assertBothSidesReject(broken, "schemaVersion const break");
});

test("negative: missing step params is rejected on both sides", () => {
  const broken = structuredClone(base);
  delete broken.steps[0].params;
  assertBothSidesReject(broken, "missing params");
});

test("negative: additional top-level property is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.tags = ["smoke"];
  assertBothSidesReject(broken, "extra property");
});

test("negative: name exceeding 256 chars is rejected on both sides", () => {
  const broken = structuredClone(base);
  broken.name = "n".repeat(257);
  assertBothSidesReject(broken, "name 257 chars");
});
