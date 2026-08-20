/**
 * Unit tests for resolveInstallMode() — the global vs project install-mode
 * decision — and parseChecksums() — the SHA256SUMS.txt parser — in the npx
 * installer. Uses node:assert so no extra test runner is required; run via
 * `npm test`.
 */

const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { resolveInstallMode, parseChecksums, parseArgs } = require('../lib/installer');

const originalCwd = process.cwd();
const originalHome = os.homedir;

/**
 * Temporarily set the home directory and chdir into a fresh temp directory
 * (the "current working directory"), then run fn(cwd). Always restores state.
 */
function withHomeAndCwd(home, fn) {
  return (async () => {
    const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'iterate-mode-'));
    os.homedir = () => home;
    process.chdir(cwd);
    try {
      return await fn(cwd);
    } finally {
      os.homedir = originalHome;
      process.chdir(originalCwd);
      fs.rmSync(cwd, { recursive: true, force: true });
    }
  })();
}

async function run() {
  // 1) Explicit --target is honored without asking.
  await withHomeAndCwd('/home/u', async () => {
    const opts = { global: true, target: '/x', targetExplicit: true, globalExplicit: false };
    const ask = () => { throw new Error('should not ask'); };
    const out = await resolveInstallMode(opts, ask);
    assert.strictEqual(out.target, '/x', 'target should be preserved');
    assert.strictEqual(out.global, true, 'global should be left untouched for explicit target');
  });

  // 2) Explicit --global is honored without asking.
  await withHomeAndCwd('/home/u', async () => {
    const opts = { global: true, target: null, targetExplicit: false, globalExplicit: true };
    const ask = () => { throw new Error('should not ask'); };
    const out = await resolveInstallMode(opts, ask);
    assert.strictEqual(out.global, true, 'global should be preserved');
    assert.strictEqual(out.target, null, 'target should stay null');
  });

  // 3) cwd === home: no ask, stays global.
  await withHomeAndCwd('/home/u', async () => {
    // Use process.cwd() (the resolved path) so home matches cwd exactly,
    // avoiding macOS /var -> /private/var symlink mismatches.
    os.homedir = () => process.cwd();
    const opts = { global: true, target: null, targetExplicit: false, globalExplicit: false };
    const ask = () => { throw new Error('should not ask when cwd is home'); };
    const out = await resolveInstallMode(opts, ask);
    assert.strictEqual(out.global, true, 'should stay global when cwd is home');
  });

  // 4) cwd !== home and user says yes -> project-level install into cwd.
  await withHomeAndCwd('/home/u', async () => {
    const opts = { global: true, target: null, targetExplicit: false, globalExplicit: false };
    const out = await resolveInstallMode(opts, async () => true);
    assert.strictEqual(out.global, false, 'should switch to project mode');
    assert.strictEqual(out.target, process.cwd(), 'target should be cwd');
  });

  // 5) cwd !== home and user says no -> stays global.
  await withHomeAndCwd('/home/u', async () => {
    const opts = { global: true, target: null, targetExplicit: false, globalExplicit: false };
    const out = await resolveInstallMode(opts, async () => false);
    assert.strictEqual(out.global, true, 'should stay global when user declines');
    assert.strictEqual(out.target, null, 'target should stay null');
  });

  console.log('mode.test.js: all resolveInstallMode tests passed');

  // parseChecksums: must strip the GNU tar binary-mode marker ('*') so both
  // "HASH  name" and "HASH *name" formats resolve, matching the Python side.
  const plain = parseChecksums('abc123  iterate-skill.tar.gz\n');
  assert.strictEqual(plain.get('iterate-skill.tar.gz'), 'abc123', 'plain format should parse');

  const starred = parseChecksums('def456 *iterate-skill.tar.gz\n');
  assert.strictEqual(starred.get('iterate-skill.tar.gz'), 'def456', 'starred format should strip the * marker');

  const crlf = parseChecksums('abc123  iterate-skill.tar.gz\r\n');
  assert.strictEqual(crlf.get('iterate-skill.tar.gz'), 'abc123', 'CRLF line endings should parse');

  const multi = parseChecksums('aa  a.txt\nbb  b.txt\n');
  assert.strictEqual(multi.get('a.txt'), 'aa');
  assert.strictEqual(multi.get('b.txt'), 'bb');

  console.log('mode.test.js: all parseChecksums tests passed');

  // parseArgs: --no-cli must toggle skill-only mode, and default to off.
  assert.strictEqual(parseArgs([]).noCli, false, 'noCli should default to false');
  assert.strictEqual(parseArgs(['--no-cli']).noCli, true, '--no-cli should set noCli');
  assert.strictEqual(parseArgs(['--no-cli', '--force', '--global']).noCli, true, 'noCli persists with other flags');
  assert.strictEqual(parseArgs(['--global']).noCli, false, 'unrelated flags do not set noCli');

  // parseArgs: unrelated flag surface is preserved (target/global/ai/force).
  const combo = parseArgs(['--ai', 'trae', '--target', '/proj', '--force']);
  assert.strictEqual(combo.ai, 'trae', 'ai should parse');
  assert.strictEqual(combo.target, '/proj', 'target should parse');
  assert.strictEqual(combo.force, true, 'force should parse');
  assert.strictEqual(combo.global, false, 'target forces project mode');

  // parseArgs: --version/-v/--help/-h must set the corresponding mode instead
  // of falling through to the unknown-option error.
  assert.strictEqual(parseArgs([]).mode, null, 'mode should default to null');
  assert.strictEqual(parseArgs(['--version']).mode, 'version', '--version should set version mode');
  assert.strictEqual(parseArgs(['-v']).mode, 'version', '-v should set version mode');
  assert.strictEqual(parseArgs(['--help']).mode, 'help', '--help should set help mode');
  assert.strictEqual(parseArgs(['-h']).mode, 'help', '-h should set help mode');

  console.log('mode.test.js: all parseArgs tests passed');
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});