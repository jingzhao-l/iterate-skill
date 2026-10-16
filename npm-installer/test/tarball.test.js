/**
 * Tarball safety-hardening tests for the npx installer.
 *
 * Covers the guards in extractTarball()/rejectLinkEntries():
 *   - symbolic / hard link entries are refused outright;
 *   - the single-top-level-directory contract required by --strip-components=1;
 *   - the FAIL-CLOSED listing cap (regression for the TailBuffer bypass, where
 *     a >cap listing silently dropped the OLDEST entries — hiding exactly the
 *     symlink the guard exists to catch — while tar still extracted it);
 *   - the post-extraction decompression-bomb budget.
 *
 * Requires the system `tar` (macOS/Linux); skipped on Windows where the
 * installer falls back to a different extraction path.
 */

const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const {
  extractTarball,
  rejectLinkEntries,
  enforceExtractedSize,
  measureTree,
  FullBuffer,
  MAX_LISTING_CHARS,
  InstallerError,
} = require('../lib/installer');

const isWindows = process.platform === 'win32';

function tmpDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function runTar(args, cwd) {
  const res = spawnSync('tar', args, { cwd, encoding: 'utf8' });
  assert.strictEqual(res.status, 0, `tar ${args.join(' ')} failed: ${res.stderr}`);
}

/**
 * Build a release-shaped tarball (single top-level `iterate/` directory).
 *
 * @param {object} opts
 * @param {'sym'|'hard'|null} opts.link  optional link entry to smuggle in
 * @param {number} opts.filler           number of long-named filler files
 * @param {boolean} opts.extraTopLevel   add a second top-level directory
 */
function buildTarball({ link = null, filler = 0, extraTopLevel = false } = {}) {
  const stage = tmpDir('iterate-tar-');
  const root = path.join(stage, 'iterate');
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(path.join(root, 'SKILL.md'), '---\nname: iterate\nversion: 0.0.0\n---\n');
  if (link === 'sym') {
    fs.symlinkSync('/etc', path.join(root, 'sneaky-link'));
  } else if (link === 'hard') {
    fs.linkSync(path.join(root, 'SKILL.md'), path.join(root, 'sneaky-hard'));
  }
  for (let i = 0; i < filler; i += 1) {
    const name = `filler-${String(i).padStart(6, '0')}-${'x'.repeat(180)}`;
    fs.writeFileSync(path.join(root, name), 'x');
  }
  if (extraTopLevel) {
    const other = path.join(stage, 'z-pwn');
    fs.mkdirSync(other, { recursive: true });
    fs.writeFileSync(path.join(other, 'evil.md'), 'evil');
  }
  const tarball = path.join(stage, 'iterate-skill.tar.gz');
  runTar(['-czf', tarball, ...(extraTopLevel ? ['iterate', 'z-pwn'] : ['iterate'])], stage);
  return { tarball, stage };
}

async function expectInstallerError(promise, needle) {
  try {
    await promise;
  } catch (err) {
    assert.ok(err instanceof InstallerError, `expected InstallerError, got ${err}`);
    assert.ok(
      String(err.message).includes(needle),
      `error message ${JSON.stringify(err.message)} must mention ${JSON.stringify(needle)}`,
    );
    return err;
  }
  throw new Error(`expected a failure mentioning ${JSON.stringify(needle)}, but it succeeded`);
}

async function testFullBuffer() {
  const buf = new FullBuffer(10);
  buf.push('12345');
  assert.strictEqual(buf.toString(), '12345');
  assert.strictEqual(buf.overflowed, false);
  buf.push('67890ABCDEF');
  assert.strictEqual(buf.overflowed, true, 'overflow must be recorded');
  assert.strictEqual(buf.toString(), '1234567890', 'head is retained, not the tail');
  // Once overflowed, further pushes are ignored (bounded memory).
  buf.push('more');
  assert.strictEqual(buf.toString(), '1234567890');
}

async function testListingCapFailClosed() {
  // REGRESSION: a listing that exceeds the cap must ABORT, never be silently
  // truncated. With a 1 MiB tail buffer, the archive below (whose listing
  // exceeds the injected cap) had its OLDEST entries dropped from the scan —
  // including the symlink — and extraction then proceeded.
  const { tarball, stage } = buildTarball({ link: 'sym', filler: 40 });
  try {
    const dest = path.join(stage, 'out');
    await expectInstallerError(
      extractTarball(tarball, dest, { listingCap: 50 }),
      'truncated result',
    );
    // The refused archive must not have produced the symlink on disk.
    assert.ok(
      !fs.existsSync(path.join(dest, 'sneaky-link')),
      'a truncated listing must never reach extraction',
    );
  } finally {
    fs.rmSync(stage, { recursive: true, force: true });
  }
}

async function testLinkRejection() {
  for (const [kind, needle] of [
    ['sym', 'symbolic link'],
    ['hard', 'hard link'],
  ]) {
    const { tarball, stage } = buildTarball({ link: kind });
    try {
      await expectInstallerError(rejectLinkEntries(tarball), needle);
      const dest = path.join(stage, 'out');
      await expectInstallerError(extractTarball(tarball, dest), needle);
      assert.ok(!fs.existsSync(dest) || !fs.existsSync(path.join(dest, 'sneaky-link')));
    } finally {
      fs.rmSync(stage, { recursive: true, force: true });
    }
  }
}

async function testCleanArchiveExtracts() {
  const { tarball, stage } = buildTarball({ filler: 3 });
  try {
    // A clean archive must NOT be refused by the complete-listing check...
    await rejectLinkEntries(tarball);
    const dest = path.join(stage, 'out');
    await extractTarball(tarball, dest);
    assert.ok(fs.existsSync(path.join(dest, 'SKILL.md')), 'clean archive extracts');
    assert.strictEqual(measureTree(dest).total > 0, true);
  } finally {
    fs.rmSync(stage, { recursive: true, force: true });
  }
}

async function testMultiTopLevelRejected() {
  const { tarball, stage } = buildTarball({ extraTopLevel: true });
  try {
    await expectInstallerError(
      extractTarball(tarball, path.join(stage, 'out')),
      'exactly one top-level directory',
    );
  } finally {
    fs.rmSync(stage, { recursive: true, force: true });
  }
}

async function testExtractedSizeBudget() {
  const { tarball, stage } = buildTarball({ filler: 5 });
  try {
    const dest = path.join(stage, 'out');
    await extractTarball(tarball, dest);
    const measured = measureTree(dest);
    assert.ok(measured.total > 0 && measured.largest > 0);
    // Simulate a bomb: a budget far below what was extracted must refuse and
    // remove the tree.
    await expectInstallerError(
      Promise.resolve().then(() => enforceExtractedSize(dest, { maxTotal: 10, maxMember: 10 })),
      'exceeds the safety budget',
    );
    assert.ok(!fs.existsSync(dest), 'the over-budget tree is removed');
  } finally {
    fs.rmSync(stage, { recursive: true, force: true });
  }
}

function testListingCapIsGenerous() {
  assert.ok(
    MAX_LISTING_CHARS >= 4 * 1024 * 1024,
    'the complete-listing cap must leave ample headroom over a real release listing',
  );
}

async function run() {
  await testFullBuffer();
  console.log('tarball.test.js: FullBuffer tests passed');
  if (isWindows) {
    console.log('tarball.test.js: skipping tar-backed tests on Windows');
    return;
  }
  await testListingCapFailClosed();
  await testLinkRejection();
  await testCleanArchiveExtracts();
  await testMultiTopLevelRejected();
  await testExtractedSizeBudget();
  testListingCapIsGenerous();
  console.log('tarball.test.js: all tarball hardening tests passed');
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
