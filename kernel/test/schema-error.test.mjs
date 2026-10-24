import assert from "node:assert/strict";
import { test } from "node:test";

import { z } from "zod";

import { KernelSchemaError, schemaErrorFrom } from "../dist/errors.js";

/**
 * `schemaErrorFrom` is the one place a validation failure becomes the error this package throws, and
 * it is driven from five call sites that never see a zod type (`errors.ts` stays free of a zod import
 * so the module graph has no cycle). That structural decoupling is also why the shape it accepts has
 * to be stated honestly: zod 4 types an issue path as `PropertyKey[]`, so a symbol can arrive here,
 * and `String(symbol)` throws. A crash on the way to reporting "your input is invalid" would be a
 * worse failure than the invalid input, so these cases pin the renderer, not the type.
 */

test("a symbol in an issue path is rendered instead of throwing", () => {
  // A throw here fails this case with the conversion error as its reason, which is the point: the
  // crash is the regression, not a different answer.
  const failure = schemaErrorFrom("pack", { issues: [{ path: ["signals", Symbol("unnamed-node"), "role"], message: "bad" }] });
  assert.equal(failure.issues[0].path, "signals.unnamed-node.role");
});

test("a symbol with no description says it was unnamed rather than vanishing", () => {
  const failure = schemaErrorFrom("pack", { issues: [{ path: [Symbol()], message: "bad" }] });
  assert.equal(failure.issues[0].path, "<symbol>");
});

test("numeric segments still join as a dotted path", () => {
  const failure = schemaErrorFrom("pack", { issues: [{ path: ["entries", 3, "key"], message: "bad" }] });
  assert.equal(failure.issues[0].path, "entries.3.key");
});

test("an empty path is the root, and the label leads the message", () => {
  const failure = schemaErrorFrom("pack", { issues: [{ path: [], message: "bad" }] });
  assert.ok(failure instanceof KernelSchemaError);
  assert.equal(failure.code, "KERNEL_E_SCHEMA");
  assert.match(failure.message, /^invalid pack: <root>: bad$/);
});

test("several issues join in order, one segment per violation", () => {
  const failure = schemaErrorFrom("pack", {
    issues: [
      { path: ["a"], message: "first" },
      { path: ["b", 0], message: "second" },
    ],
  });
  assert.equal(failure.issues.length, 2);
  assert.equal(failure.message, "invalid pack: a: first; b.0: second");
});

test("a real zod 4 rejection survives the handoff", () => {
  const schema = z.strictObject({ role: z.string().min(1), title: z.string().optional() });
  const checked = schema.safeParse({ role: "", title: 7 });
  assert.equal(checked.success, false, "the fixture must actually be a rejection, or this proves nothing");
  assert.ok(checked.error.issues.length > 0);
  const failure = schemaErrorFrom("selector", checked.error);
  assert.equal(failure.issues.length, checked.error.issues.length);
  for (const issue of failure.issues) {
    assert.equal(typeof issue.path, "string", `a path reached the contract as ${typeof issue.path}`);
    assert.ok(!issue.path.includes("undefined"), `a missing segment leaked into ${issue.path}`);
    assert.ok(!issue.path.includes("[object"), `a non-text segment printed as an object in ${issue.path}`);
  }
});

test("zod 4 lets a custom issue carry a symbol path, which is why the renderer had to change", () => {
  const schema = z.strictObject({ body: z.string() }).superRefine((value, ctx) => {
    ctx.addIssue({ code: "custom", message: "symbolic", path: [Symbol("kernel-symbol")] });
  });
  const checked = schema.safeParse({ body: "anything" });
  assert.equal(checked.success, false, "the superRefine issue was not raised, so this case proved nothing");
  const symbolic = checked.error.issues.find((issue) => issue.path.some((segment) => typeof segment === "symbol"));
  if (!symbolic) {
    // Honest reading if zod normalises the path itself: the guard is still required because
    // `SchemaErrorLike` promises `PropertyKey[]`, and a test that only runs the friendly case would
    // let a future zod re-introduce the symbol without any red here.
    assert.ok(
      typeof checked.error.issues[0].path[0] === "string",
      `the path segment arrived as ${typeof checked.error.issues[0].path[0]}, which is neither a string nor a symbol`,
    );
    return;
  }
  const failure = schemaErrorFrom("report", checked.error);
  assert.match(failure.issues.map((issue) => issue.path).join("."), /kernel-symbol/);
});
