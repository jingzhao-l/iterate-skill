import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { chmodSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { after, test } from "node:test";
import Ajv2020 from "ajv/dist/2020.js";

import {
  DECISION_LOG_ENTRY_JSON_SCHEMA,
  KernelDecisionLogError,
  appendDecisionLogEntry,
  buildDecisionLogEntry,
  canonicalJson,
  decisionLogEntryHash,
  decisionLogHead,
  newDecisionEntryId,
  readDecisionLog,
  serializeDecisionLogEntry,
  verifyDecisionLogText
} from "../dist/index.js";
import { canonical as helperCanonical, readFixture } from "./helpers.mjs";

/**
 * The decision log chain — kernel/src/decision-log.ts.
 *
 * Anything that could pass merely by being self-consistent is checked against a
 * second implementation on purpose: the fixture hashes are recomputed with
 * `openssl` (not with this package), and the canonical form is compared against
 * the repository's other TypeScript canonicaliser.
 */

const fixture = readFixture("decision-log-chain.ok-01.json");
const ajv = new Ajv2020({ allErrors: true });
const validateAjv = ajv.compile(DECISION_LOG_ENTRY_JSON_SCHEMA);

const sha256hex = (buffer) => createHash("sha256").update(buffer).digest("hex");

function opensslSha256(buffer) {
  const run = spawnSync("openssl", ["dgst", "-sha256", "-r"], { input: buffer });
  assert.equal(run.status, 0, `openssl is the independent implementation in this test: ${run.stderr}`);
  const match = /[0-9a-f]{64}/.exec(run.stdout.toString());
  assert.ok(match, `cannot parse openssl output: ${run.stdout}`);
  return match[0];
}

const scratchRoot = join(tmpdir(), "gp-kernel-decision-log");
rmSync(scratchRoot, { recursive: true, force: true });
mkdirSync(scratchRoot, { recursive: true, mode: 0o700 });
after(() => rmSync(scratchRoot, { recursive: true, force: true }));

let counter = 0;
function ledgerPath() {
  const dir = join(scratchRoot, `case-${(counter += 1)}`);
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  return join(dir, "decisions.jsonl");
}

function draft(overrides = {}) {
  counter += 1;
  return {
    entryId: newDecisionEntryId(),
    summary: "attach matched the window the action targeted",
    outcome: "pass",
    createdAt: new Date(Date.parse("2026-09-25T04:00:00.000Z") + counter * 1000).toISOString().replace(/\d{3}Z$/, "000Z"),
    ...overrides
  };
}

function expectRefusal(code, run) {
  assert.throws(run, (error) => {
    assert.ok(error instanceof KernelDecisionLogError, `expected KernelDecisionLogError, got ${error}`);
    assert.equal(error.code, code, `expected ${code}, got ${error.code}: ${error.message}`);
    assert.ok(error.remedy.length > 0, "every refusal must carry a remedy an agent can act on");
    return true;
  });
}

function assertAbsent(path) {
  assert.throws(() => statSync(path), (error) => error.code === "ENOENT", "a refused write must leave nothing behind");
}

// ------------------------------------------------------------------ the anchor

test("fixture chain verifies, and openssl (not this package) reproduces every link", () => {
  const verified = verifyDecisionLogText(fixture.lines.join("\n") + "\n");
  assert.equal(verified.ok, true, verified.reason);
  assert.equal(verified.entries.length, 3);
  fixture.lines.forEach((line, index) => {
    assert.equal(canonicalJson(JSON.parse(line)), line, `line ${index + 1} is canonical JSON`);
    assert.equal(fixture.hashes[index], opensslSha256(Buffer.from(line, "utf8")), `line ${index + 1} hash matches openssl`);
    assert.equal(fixture.hashes[index], sha256hex(Buffer.from(line, "utf8")), `line ${index + 1} hash matches node:crypto`);
    assert.equal(JSON.parse(line).prevEntryHash, index === 0 ? "" : fixture.hashes[index - 1]);
  });
});

test("a one-word edit to line 1 breaks the chain at line 2", () => {
  const tampered = [...fixture.lines];
  tampered[0] = tampered[0].replace('"outcome":"pass"', '"outcome":"fail"');
  const verified = verifyDecisionLogText(tampered.join("\n") + "\n");
  assert.equal(verified.ok, false);
  assert.equal(verified.firstBrokenLine, 2);
  assert.equal(verified.brokenKind, "chain");
  assert.match(verified.reason, /hashes to/);
});

test("the kernel's canonicaliser agrees with the repo's other TypeScript one", () => {
  const samples = [
    readFixture("decision-log-entry.ok-01.json"),
    ...fixture.lines.map((line) => JSON.parse(line)),
    { b: 1, a: [3, { z: null, y: "é\\/" }], " ": true }
  ];
  for (const sample of samples) {
    assert.equal(canonicalJson(sample), helperCanonical(sample), `divergent canonical form for ${JSON.stringify(sample)}`);
  }
});

// ------------------------------------------------------------------ the writer

test("genesis append: empty prevEntryHash, sequence 0, file mode 0600, one line", () => {
  const path = ledgerPath();
  const result = appendDecisionLogEntry(path, draft());
  assert.equal(result.entry.sequence, 0);
  assert.equal(result.entry.prevEntryHash, "");
  assert.equal(result.line, 1);
  assert.equal(statSync(path).mode & 0o777, 0o600);
  const onDisk = readFileSync(path, "utf8");
  assert.equal(onDisk, `${serializeDecisionLogEntry(result.entry)}\n`);
  assert.equal(result.hash, decisionLogEntryHash(result.entry));
  assert.equal(result.bytesWritten, Buffer.byteLength(onDisk, "utf8"));
});

test("three appends produce a chain whose links openssl can recompute", () => {
  const path = ledgerPath();
  const first = appendDecisionLogEntry(path, draft({ outcome: "pass" }));
  const second = appendDecisionLogEntry(path, draft({ outcome: "fail", summary: "act refused: element not focusable" }));
  const third = appendDecisionLogEntry(path, draft({ outcome: "blocked" }));
  const lines = readFileSync(path, "utf8").trimEnd().split("\n");
  assert.equal(lines.length, 3);
  assert.equal(second.entry.prevEntryHash, first.hash);
  assert.equal(third.entry.prevEntryHash, second.hash);
  assert.equal(opensslSha256(Buffer.from(lines[1], "utf8")), third.entry.prevEntryHash);
  const verified = readDecisionLog(path);
  assert.equal(verified.ok, true, verified.reason);
  assert.deepEqual(verified.entries.map((entry) => entry.outcome), ["pass", "fail", "blocked"]);
});

test("a caller cannot send chain fields at all — forging is refused, not overridden", () => {
  const path = ledgerPath();
  const first = appendDecisionLogEntry(path, draft());
  expectRefusal("KERNEL_E_DECISION_LOG_DRAFT", () =>
    appendDecisionLogEntry(path, { ...draft(), sequence: 99, prevEntryHash: "f".repeat(64) })
  );
  const verified = readDecisionLog(path);
  assert.equal(verified.entries.length, 1, "the refused attempt added nothing");
  assert.equal(verified.entries[0].entryId, first.entry.entryId);
  // and the honest path still works: the ledger supplies the chain fields.
  const second = appendDecisionLogEntry(path, draft());
  assert.equal(second.entry.sequence, 1);
  assert.equal(second.entry.prevEntryHash, first.hash);
});

test("an extra field on the draft is refused before anything is written", () => {
  const path = ledgerPath();
  expectRefusal("KERNEL_E_DECISION_LOG_DRAFT", () => appendDecisionLogEntry(path, { ...draft(), extra: "smuggled" }));
  assertAbsent(path);
});

test("an invalid entryId is refused before anything is written", () => {
  const path = ledgerPath();
  expectRefusal("KERNEL_E_DECISION_LOG_DRAFT", () => appendDecisionLogEntry(path, draft({ entryId: "dl_nope" })));
  assertAbsent(path);
});

// ------------------------------------------------- refusals must not mutate

test("corrupt tail: refuse, name the line, and leave the bytes exactly as found", () => {
  const path = ledgerPath();
  appendDecisionLogEntry(path, draft());
  appendDecisionLogEntry(path, draft());
  writeFileSync(path, Buffer.concat([readFileSync(path), Buffer.from("not json at all\n", "utf8")]));
  const before = sha256hex(readFileSync(path));
  expectRefusal("KERNEL_E_DECISION_LOG_CORRUPT", () => appendDecisionLogEntry(path, draft()));
  assert.equal(sha256hex(readFileSync(path)), before, "a refused append must not mutate the ledger");
  const verified = readDecisionLog(path);
  assert.equal(verified.firstBrokenLine, 3);
  assert.equal(verified.brokenKind, "corrupt");
});

test("a valid entry stored in non-canonical form is caught, not silently re-hashed", () => {
  const path = ledgerPath();
  const appended = appendDecisionLogEntry(path, draft());
  writeFileSync(path, `${JSON.stringify(appended.entry, null, 2).replace(/\s+/g, " ")}\n`);
  const verified = readDecisionLog(path);
  assert.equal(verified.ok, false);
  assert.equal(verified.firstBrokenLine, 1);
  assert.match(verified.reason, /canonical JSON form/);
  expectRefusal("KERNEL_E_DECISION_LOG_CORRUPT", () => appendDecisionLogEntry(path, draft()));
});

test("replacing the tail with a valid-but-unlinked entry is reported as a chain break", () => {
  const path = ledgerPath();
  appendDecisionLogEntry(path, draft());
  const forged = buildDecisionLogEntry(draft(), { sequence: 1, prevEntryHash: "0".repeat(64) });
  writeFileSync(path, `${readFileSync(path, "utf8")}${serializeDecisionLogEntry(forged)}\n`);
  const verified = readDecisionLog(path);
  assert.equal(verified.ok, false);
  assert.equal(verified.brokenKind, "chain");
  assert.equal(verified.firstBrokenLine, 2);
  expectRefusal("KERNEL_E_DECISION_LOG_CHAIN", () => appendDecisionLogEntry(path, draft()));
});

test("dropping the tail keeps a valid prefix — which is why the append returns its hash", () => {
  const path = ledgerPath();
  appendDecisionLogEntry(path, draft());
  const second = appendDecisionLogEntry(path, draft());
  const third = appendDecisionLogEntry(path, draft());
  const lines = readFileSync(path, "utf8").trimEnd().split("\n");
  writeFileSync(path, `${lines.slice(0, 2).join("\n")}\n`);
  const verified = readDecisionLog(path);
  assert.equal(verified.ok, true, "the chain is internally consistent up to the cut");
  assert.equal(verified.entries.length, 2);
  assert.equal(third.entry.prevEntryHash, second.hash, "an out-of-band record of the hash is what proves the cut");
});

test("relative paths, empty paths and a missing directory are refused with a remedy", () => {
  expectRefusal("KERNEL_E_DECISION_LOG_PATH", () => appendDecisionLogEntry("decisions.jsonl", draft()));
  expectRefusal("KERNEL_E_DECISION_LOG_PATH", () => appendDecisionLogEntry("", draft()));
  expectRefusal("KERNEL_E_DECISION_LOG_LOCATION", () =>
    appendDecisionLogEntry(join(scratchRoot, "no-such-dir", "decisions.jsonl"), draft())
  );
  assert.equal(readDecisionLog(join(scratchRoot, "nothing-here.jsonl")).entries.length, 0, "a missing ledger reads as an empty chain");
});

test("a group/other-writable directory is refused: the chain could be swapped out", () => {
  const path = ledgerPath();
  chmodSync(dirname(path), 0o777);
  try {
    expectRefusal("KERNEL_E_DECISION_LOG_LOCATION", () => appendDecisionLogEntry(path, draft()));
    assertAbsent(path);
  } finally {
    chmodSync(dirname(path), 0o700);
  }
  appendDecisionLogEntry(path, draft());
});

test("an existing ledger that loosened is re-isolated on append", () => {
  const path = ledgerPath();
  appendDecisionLogEntry(path, draft());
  chmodSync(path, 0o644);
  appendDecisionLogEntry(path, draft());
  assert.equal(statSync(path).mode & 0o777, 0o600);
});

// ------------------------------------------------------------------- helpers

test("entry ids match the schema's Crockford ULID, sort by time, and do not repeat", () => {
  const ids = [newDecisionEntryId(0), newDecisionEntryId(1_700_000_000_000)];
  for (let i = 0; i < 400; i += 1) ids.push(newDecisionEntryId());
  for (const id of ids) assert.match(id, /^dl_[0-9A-HJKMNP-TV-Z]{26}$/);
  assert.equal(new Set(ids).size, ids.length, "400 ids in the same millisecond must not collide");
  assert.ok(ids[0].slice(3, 13) < ids[1].slice(3, 13), "the 10-char time prefix sorts");
  assert.throws(() => newDecisionEntryId(1.5), RangeError);
  assert.throws(() => newDecisionEntryId(2 ** 48), RangeError);
  assert.equal(validateAjv({ ...draft(), sequence: 0, prevEntryHash: "" }), true, "generated ids satisfy the JSON Schema too");
});

test("buildDecisionLogEntry omits operationId rather than writing null", () => {
  const without = buildDecisionLogEntry(draft(), { sequence: 0, prevEntryHash: "" });
  assert.equal(Object.prototype.hasOwnProperty.call(without, "operationId"), false);
  assert.equal(serializeDecisionLogEntry(without).includes("operationId"), false);
  const withOp = buildDecisionLogEntry(
    { ...draft(), operationId: `op_${without.entryId.slice(3)}` },
    { sequence: 0, prevEntryHash: "" }
  );
  assert.match(withOp.operationId, /^op_[0-9A-HJKMNP-TV-Z]{26}$/);
  assert.equal(serializeDecisionLogEntry(withOp).includes('"operationId"'), true);
});

test("decisionLogHead returns exactly the fields the next append will use", () => {
  const path = ledgerPath();
  const first = appendDecisionLogEntry(path, draft());
  const head = decisionLogHead(path);
  assert.deepEqual(head, { sequence: 1, prevEntryHash: first.hash });
  const second = appendDecisionLogEntry(path, draft());
  assert.equal(second.entry.sequence, head.sequence);
  assert.equal(second.entry.prevEntryHash, head.prevEntryHash);
});

test("canonical bytes do not depend on key insertion order", () => {
  const path = ledgerPath();
  const appended = appendDecisionLogEntry(path, draft());
  const scrambled = {};
  for (const key of Object.keys(appended.entry).reverse()) scrambled[key] = appended.entry[key];
  assert.equal(canonicalJson(scrambled), serializeDecisionLogEntry(appended.entry));
  assert.equal(decisionLogEntryHash(scrambled), appended.hash, "hash is over the canonical form, not the object literal");
});
