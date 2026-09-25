// Generate fixtures/decision-log-chain.ok-01.json from the built kernel, then
// verify the hashes independently in the shell (shasum) before committing.
import { writeFileSync } from "node:fs";
import { canonicalJson, decisionLogEntryHash, serializeDecisionLogEntry, verifyDecisionLogText } from "../dist/index.js";

const base = {
  createdAt: "2026-09-25T04:00:00.000Z",
  outcome: "pass",
  prevEntryHash: "",
  sequence: 0,
  entryId: "dl_01K2ABCDEFGHJKMNPQRSTVWXZ0",
  summary: "attach Finder; window matched the attached pid",
};
const entries = [];
let prev = "";
for (const [index, patch] of [
  {},
  { sequence: 1, outcome: "fail", createdAt: "2026-09-25T04:00:01.000Z", entryId: "dl_01K2ABCDEFGHJKMNPQRSTVWXZ1", summary: "act set-value refused: element not focusable" },
  { sequence: 2, outcome: "inconclusive", createdAt: "2026-09-25T04:00:02.000Z", entryId: "dl_01K2ABCDEFGHJKMNPQRSTVWXZ2", summary: "observe timed out while the app was modal" },
].entries()) {
  const entry = { ...base, ...patch, prevEntryHash: prev };
  if (index === 1) entry.operationId = "op_01K2ABCDEFGHJKMNPQRSTVWXZ9";
  entries.push(entry);
  prev = decisionLogEntryHash(entry);
}

const lines = entries.map((entry) => serializeDecisionLogEntry(entry));
const hashes = entries.map((entry) => decisionLogEntryHash(entry));
const verified = verifyDecisionLogText(lines.join("\n") + "\n");

const fixture = {
  comment:
    "Cross-implementation anchor for the decision log chain (kernel/src/decision-log.ts). A line's bytes ARE canonicalJson(entry) — keys sorted by UTF-16 code unit, no insignificant whitespace — so prevEntryHash of line i+1 equals sha256_hex of line i, and genesis carries an empty prevEntryHash. Any language that can sort keys and sha256 can verify this file; the kernel test recomputes the hashes with an external tool (shasum/openssl), so a TypeScript-only chain cannot pass silently.",
  lines,
  hashes,
};
writeFileSync(new URL("../fixtures/decision-log-chain.ok-01.json", import.meta.url), JSON.stringify(fixture, null, 2) + "\n");
console.log("verified.ok =", verified.ok, "entries =", verified.entries.length);
console.log(lines.map((l, i) => `line ${i + 1} sha256 = ${hashes[i]}`).join("\n"));
