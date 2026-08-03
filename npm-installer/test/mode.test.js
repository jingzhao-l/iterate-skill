/**
 * Unit tests for resolveInstallMode() — the global vs project install-mode
 * decision in the npx installer. Uses node:assert so no extra test runner is
 * required; run via `npm test`.
 */

const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { resolveInstallMode } = require('../lib/installer');

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
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});