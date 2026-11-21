import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const kernelRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * The tarball, not the working tree, is what a consumer gets. This test packs
 * locally (`--dry-run` writes nothing and reaches no network) and checks the
 * artifact against the directory the contract actually lives in.
 */
function packedPaths() {
  const raw = execFileSync("npm", ["pack", "--dry-run", "--json"], {
    cwd: kernelRoot,
    encoding: "utf8"
  });
  // npm <= 10 returns a top-level array of manifests; npm 11+ returns an object
  // keyed by package name. Accept both so the gate runs on whichever npm the
  // developer or CI happens to have.
  const parsed = JSON.parse(raw);
  const manifest = Array.isArray(parsed) ? parsed[0] : parsed[Object.keys(parsed)[0]];
  return new Set(manifest.files.map((entry) => entry.path));
}

function filesIn(directory) {
  return readdirSync(join(kernelRoot, directory), { withFileTypes: true })
    .filter((entry) => entry.isFile())
    .map((entry) => `${directory}/${entry.name}`)
    .sort();
}

const manifest = JSON.parse(readFileSync(join(kernelRoot, "package.json"), "utf8"));
const packed = packedPaths();

test("the fixture corpus ships with the package — it is the cross-language contract", () => {
  // Why this gate exists: the fixtures are the only thing a second implementation
  // in another language can be coded from (each carries its rules in `comment`).
  // iterate-harness points KERNEL_FIXTURES_DIR at the installed package; if the
  // corpus is not packed, that gate silently skips and "both sides agree" stops
  // being checked. A fixture that never installs is worse than no fixture.
  const fixtures = filesIn("fixtures");
  assert.ok(fixtures.length > 0, "no fixtures found in fixtures/");
  const missing = fixtures.filter((path) => !packed.has(path));
  assert.deepEqual(missing, [], `fixtures not in the tarball: ${missing.join(", ")}`);
  assert.ok(manifest.files.includes("fixtures"), 'package.json "files" must list "fixtures"');
});

test("the JSON Schemas ship with the package", () => {
  const schemas = filesIn("schemas");
  assert.ok(schemas.length > 0, "no schemas found in schemas/");
  const missing = schemas.filter((path) => !packed.has(path));
  assert.deepEqual(missing, [], `schemas not in the tarball: ${missing.join(", ")}`);
});

test("every src module is reachable as a subpath export", () => {
  // Consumers import per module and never through the barrel: the barrel pulls
  // `schemas`, which reads schema files next to the package at load time — a trap
  // for anything bundled to a single file. A module with no subpath is therefore
  // unreachable for the one consumer shape that works in a binary.
  const modules = readdirSync(join(kernelRoot, "src"))
    .filter((name) => name.endsWith(".ts"))
    .map((name) => name.replace(/\.ts$/, ""))
    .sort();
  const exportSpecifiers = Object.keys(manifest.exports).filter((key) => key !== ".");
  const missing = modules.filter((name) => !exportSpecifiers.includes(`./${name}`));
  assert.deepEqual(missing, [], `src modules without a subpath export: ${missing.join(", ")}`);
  for (const name of modules) {
    assert.ok(existsSync(join(kernelRoot, "dist", `${name}.js`)), `dist/${name}.js is not built`);
    assert.ok(packed.has(`dist/${name}.js`), `dist/${name}.js is not packed`);
  }
});

test("the summary length bound is the SUMMARY_MAX_LENGTH constant, not a hardcoded literal", () => {
  // `decision-log-transcribe` (the refusal path) and `evidence-decision` (the clamp)
  // both enforce the schema's summary bound. Both used to spell the number out as a
  // bare `2048` / `2045`, so if the constant in decision-log-entry ever moved, these
  // two would silently drift from the schema the digest is taken over. A drift here
  // would mean the TS refusal/clamp and the zod `.max()` disagree — and only one of
  // them would be wrong in a way no fixture catches. The guard is a source scan
  // because the bound is enforced at build-time constants, not through a value that
  // a behavioural test can pin across both call sites.
  const offenders = [];
  for (const file of ["decision-log-transcribe.ts", "evidence-decision.ts"]) {
    const text = readFileSync(join(kernelRoot, "src", file), "utf8");
    if (!text.includes("SUMMARY_MAX_LENGTH")) {
      offenders.push(`${file} never references SUMMARY_MAX_LENGTH`);
    }
    // Any bare spelling of the bound (or the ellipsis-shortened slice) re-introduces
    // the drift this guard exists to stop. Match a `20`/`2045`-class literal that is
    // not part of another number and not the schema's own definition.
    const literal = text.match(/(?<![0-9.])204[0-9](?![0-9])/);
    if (literal) {
      offenders.push(`${file} hardcodes the bound literal ${literal[0]} instead of SUMMARY_MAX_LENGTH`);
    }
  }
  assert.deepEqual(offenders, [], `summary bound drifted from the constant: ${offenders.join("; ")}`);
});
