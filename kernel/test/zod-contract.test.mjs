/**
 * The published types are only honest if the declared `zod` is the zod the declarations were
 * emitted against.
 *
 * WHY THIS EXISTS (measured, 2026-10-18, from a consumer's failure rather than from theory).
 * This package declared `"zod": ">=3.25.76 <5"` while its shipped `.d.ts` were emitted by a
 * build that had zod 3 installed. A consumer whose resolver picked zod 4 for this dependency got
 * no type error where one was owed: `z.infer` on our schemas degraded to `any`, and TypeScript
 * complained about *its own* callbacks instead ("Parameter 'ref' implicitly has an 'any' type",
 * TS7006). Compilation succeeded; typing quietly disappeared — the worst shape a shared contract
 * can have, because both sides stay green. GlassPane's shell hit exactly this and pinned it with
 * an `overrides` block on its side, which is a workaround living downstream of the bug.
 *
 * So the range becomes an exact version, and these three checks make the disagreement
 * un-shippable:
 *
 *   1. the declared spec is one exact version — a range here is the defect returning;
 *   2. the zod this build actually resolves is that version (the lock cannot silently move the
 *      emitter to a different major while the declaration still promises 3.x);
 *   3. the emitted declarations still carry the shape zod 3 produces. If a future release
 *      deliberately moves to zod 4, this test is the one that has to change — with the consumers
 *      of the types told in the same release note, instead of discovering it as `any`.
 */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(here, "..");
const require = createRequire(import.meta.url);

const manifest = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8"));

test("the declared zod is one exact version, not a range", () => {
  const spec = manifest.dependencies?.zod;
  assert.equal(typeof spec, "string", "package.json must declare a zod dependency at all");
  assert.match(
    spec,
    /^\d+\.\d+\.\d+$/,
    `zod is declared as "${spec}"; a range lets the resolver emit .d.ts against one major while `
    + "consumers install another, and that silently types our schemas as any",
  );
});

test("the zod this build resolves is the declared one", () => {
  const installed = require("zod/package.json").version;
  assert.equal(
    installed,
    manifest.dependencies.zod,
    "the declaration and the emitter disagree, which is the condition that produced any-typed "
    + "schemas; install from the lockfile that matches package.json before building",
  );
});

test("the shipped declarations are the shape that zod emits at that version", () => {
  const declaration = readFileSync(join(packageRoot, "dist", "evidence-pack.d.ts"), "utf8");
  assert.match(
    declaration,
    /"strict", z\.ZodTypeAny,/,
    "evidence-pack.d.ts no longer looks like zod-3 emission. If this package moved zod majors, "
    + "every consumer that type-checks against these declarations moved with it — say so in the "
    + "release note and update this canary in the same commit.",
  );
});
