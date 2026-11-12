import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CANONICAL_JSON_CODES,
  CANONICAL_JSON_MAX_DEPTH,
  KernelCanonicalJsonError,
  canonicalJson,
  parseEvidencePack
} from "../dist/index.js";
import { canonical as helperCanonical } from "./helpers.mjs";

/**
 * The canonical form is what every digest in this package is taken over, and
 * what the Swift engine and `sha256sum` recompute from the bytes on disk.
 *
 * `JSON.stringify` is total: it prints *something* for any value, and the
 * something is a lie for values JSON has no token for. Each case below is a
 * value that used to reach the bytes — and either produced a line no reader can
 * parse, or collapsed two different documents onto one digest.
 */

function expectRefusal(code, run, label) {
  assert.throws(
    run,
    (error) => {
      assert.ok(error instanceof KernelCanonicalJsonError, `${label}: expected KernelCanonicalJsonError, got ${error}`);
      assert.equal(error.code, code, `${label}: expected ${code}, got ${error.code}`);
      assert.ok(error.remedy.length > 0, `${label}: a refusal without a remedy is not actionable`);
      return true;
    },
    label
  );
}

test("values JSON has no token for are refused instead of printed as a token", () => {
  const cases = [
    ["undefined", { a: undefined }],
    ["a function", { a: () => 1 }],
    ["a symbol", { a: Symbol("s") }],
    ["a bigint", { a: 10n }],
    ["NaN", { a: NaN }],
    ["Infinity", { a: Infinity }],
    ["-Infinity", { a: -Infinity }]
  ];
  for (const [label, value] of cases) {
    expectRefusal(CANONICAL_JSON_CODES.value, () => canonicalJson(value), label);
  }
  // Top level too: `JSON.stringify(undefined)` returns the value undefined, not a
  // string, and the old code handed that to the hash chain as if it were text.
  expectRefusal(CANONICAL_JSON_CODES.value, () => canonicalJson(undefined), "undefined at the root");
  expectRefusal(CANONICAL_JSON_CODES.value, () => canonicalJson(() => 1), "a function at the root");
});

test("two values that used to collide now cannot both be recorded", () => {
  // `NaN`, `Infinity` and `null` all printed as `null`, so `{a: NaN}` and
  // `{a: null}` shared one digest: an audit chain that certifies two different
  // decisions as the same event.
  assert.equal(canonicalJson({ a: null }), '{"a":null}');
  expectRefusal(CANONICAL_JSON_CODES.value, () => canonicalJson({ a: NaN }), "NaN");
  expectRefusal(CANONICAL_JSON_CODES.value, () => canonicalJson({ a: Infinity }), "Infinity");
});

test("a Date or a class instance is refused rather than printed as a string or as {}", () => {
  expectRefusal(CANONICAL_JSON_CODES.value, () => canonicalJson({ at: new Date(0) }), "Date");
  class Box {
    constructor() {
      this.filled = true;
    }
  }
  expectRefusal(CANONICAL_JSON_CODES.value, () => canonicalJson({ b: new Box() }), "a class instance");
  expectRefusal(CANONICAL_JSON_CODES.value, () => canonicalJson(new Map([["k", 1]])), "a Map");
});

test("a sparse array is refused because the hole has no JSON token", () => {
  // `[1,,2]` joined to `[1,,2]` with an EMPTY position, which is not JSON: the
  // reader that parses it decides the difference between a hole and a missing
  // element by accident.
  const sparse = [1, , 2];
  assert.equal(Object.hasOwn(sparse, "1"), false);
  expectRefusal(CANONICAL_JSON_CODES.value, () => canonicalJson(sparse), "sparse array");
  expectRefusal(CANONICAL_JSON_CODES.value, () => canonicalJson({ list: sparse }), "sparse array as a field");
  // Named because `write()` would also catch the hole one level down, as an
  // `undefined` — the hole is a different mistake, and the remedy the caller gets
  // ("fill it with null or drop it") only makes sense if it says so.
  for (const value of [sparse, { list: sparse }]) {
    assert.throws(() => canonicalJson(value), (error) => {
      assert.match(error.message, /index 1 is a hole/, error.message);
      return true;
    });
  }
  assert.equal(canonicalJson([1, null, 2]), "[1,null,2]", "an explicit null hole is a value and stays");
});

test("nesting beyond the stated bound is a coded refusal, not a stack overflow", () => {
  let deep = { end: 1 };
  for (let i = 0; i < CANONICAL_JSON_MAX_DEPTH + 8; i += 1) {
    deep = { nested: deep };
  }
  expectRefusal(CANONICAL_JSON_CODES.depth, () => canonicalJson(deep), "over the depth bound");

  let ok = { end: 1 };
  for (let i = 0; i < CANONICAL_JSON_MAX_DEPTH - 8; i += 1) {
    ok = { nested: ok };
  }
  assert.equal(canonicalJson(ok).startsWith("{"), true, "a document inside the bound still canonicalises");
});

test("an object graph that points back at itself is refused by the depth rule", () => {
  // Producers assemble these in memory; a cycle is not a malformed document, it is
  // a shape the runtime can hold and the canonical form cannot name. Without the
  // bound this is a `RangeError` out of the call stack — a crash, not a refusal.
  const cycle = { name: "root" };
  cycle.self = cycle;
  expectRefusal(CANONICAL_JSON_CODES.depth, () => canonicalJson(cycle), "a self-referencing record");
  expectRefusal(CANONICAL_JSON_CODES.depth, () => canonicalJson([cycle]), "a cycle behind an array");
});

test("an object with a null prototype is a plain record and canonicalises", () => {
  const record = Object.create(null);
  record.b = 1;
  record.a = 2;
  assert.equal(canonicalJson(record), '{"a":2,"b":1}');
});

test("the shipped form still agrees with the independent implementation on JSON values", () => {
  const samples = [
    { b: 1, a: [3, { z: null, y: "é\\/" }], " ": true },
    { "key with \"quotes\"": "line\nbreak", 数组: [1, 2, 3] },
    [null, [], {}, 0, -0, 1e21, 0.023, "a\u2028b"],
    { nested: { deeper: { deepest: [] } } }
  ];
  for (const sample of samples) {
    assert.equal(canonicalJson(sample), helperCanonical(sample), `diverged on ${JSON.stringify(sample)}`);
  }
  // Numbers keep the host's shortest roundtrip form; `-0` is not a JSON value
  // distinct from `0`, and both runtimes print it as `0`.
  assert.equal(canonicalJson({ n: 12 }), '{"n":12}');
  assert.equal(canonicalJson({ n: 0.023 }), '{"n":0.023}');
  assert.equal(canonicalJson({ n: -0 }), '{"n":0}');
});

/**
 * `Array.sort` orders keys by UTF-16 code unit; the Python half of this contract
 * (`canonical_json.py`) orders by code point and REFUSES any key with a character
 * above U+FFFF (`CANONICAL_JSON_E_KEY_ORDER`) because the two orders diverge there.
 * This side must refuse the same key, or a Python producer's digest is one this
 * verifier cannot reproduce — the exact silent divergence the form exists to prevent.
 * The guard mirrors the Python refusal rather than inventing a third behaviour.
 */
test("a key with a character above the BMP is refused, matching the Python half", () => {
  // Both orderings place these two keys differently: code-unit order puts the
  // surrogate pair (0xD83D…) first, code-point order puts U+E000 first.
  expectRefusal(
    CANONICAL_JSON_CODES.keyOrder,
    () => canonicalJson({ "\u{1F600}": 1, "\uE000": 2 }),
    "an emoji key and a private-use key together"
  );
  // A single non-BMP key is refused too: the divergence is about ordering against
  // a co-key, but the Python side refuses it outright, so this side does as well.
  expectRefusal(
    CANONICAL_JSON_CODES.keyOrder,
    () => canonicalJson({ "\u{1F600}": 1 }),
    "a lone emoji key"
  );
  // Astral characters in VALUES are fine — only keys are ordered. This must not refuse.
  assert.equal(canonicalJson({ note: "\u{1F600}" }), '{"note":"😀"}');
  // BMP keys with characters near the top of the BMP still sort and canonicalise.
  // `JSON.stringify` leaves U+FFFF raw (it is not a control character), so the top
  // BMP key prints as the literal character, sorted after `"\u0000"`.
  assert.equal(canonicalJson({ "\uFFFF": 1, "\u0000": 2 }), '{"\\u0000":2,"\uFFFF":1}');
});

/**
 * An unpaired surrogate has no UTF-8 representation. `JSON.stringify` escapes it and
 * the bytes hashed here are the ASCII of that escape, but a Python producer of the same
 * string raises `UnicodeEncodeError` — so no digest over it is shareable. Refused in the
 * same "no token for it" class as `NaN`/`Infinity`, in keys and in values alike.
 */
test("a string with an unpaired surrogate is refused, in a value and in a key", () => {
  expectRefusal(CANONICAL_JSON_CODES.value, () => canonicalJson({ note: "\uD83D" }), "lone high surrogate in a value");
  expectRefusal(CANONICAL_JSON_CODES.value, () => canonicalJson({ "\uD83D": 1 }), "lone high surrogate in a key");
  expectRefusal(CANONICAL_JSON_CODES.value, () => canonicalJson({ note: "\uDC00" }), "lone low surrogate in a value");
  // A properly-paired surrogate (a real non-BMP character) in a value stays legal.
  assert.equal(canonicalJson({ note: "\uD83D\uDE00" }), '{"note":"😀"}');
});
