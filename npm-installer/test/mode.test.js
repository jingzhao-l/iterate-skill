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
const { resolveInstallMode, parseChecksums, parseArgs, buildPythonInstallArgs, isGithubApiUrl, normalizeToken, buildAuthFlags, InstallerError, runCommand, runPythonInstall } = require('../lib/installer');

// 64-char lowercase hex digest, as sha256 actually produces.
const H = 'a'.repeat(64);
const I = 'b'.repeat(64);
const J = 'c'.repeat(64);
const K = 'd'.repeat(64);

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
  const plain = parseChecksums(`${H}  iterate-skill.tar.gz\n`);
  assert.strictEqual(plain.get('iterate-skill.tar.gz'), H, 'plain format should parse');

  const starred = parseChecksums(`${I} *iterate-skill.tar.gz\n`);
  assert.strictEqual(starred.get('iterate-skill.tar.gz'), I, 'starred format should strip the * marker');

  const crlf = parseChecksums(`${J}  iterate-skill.tar.gz\r\n`);
  assert.strictEqual(crlf.get('iterate-skill.tar.gz'), J, 'CRLF line endings should parse');

  const multi = parseChecksums(`${H}  a.txt\n${I}  b.txt\n`);
  assert.strictEqual(multi.get('a.txt'), H);
  assert.strictEqual(multi.get('b.txt'), I);

  // './' prefix and subpath/basename matching must resolve like the Python
  // side (scripts/install.py _parse_checksum), which matches on basename.
  const dotSlash = parseChecksums(`${H}  ./iterate-skill.tar.gz\n`);
  assert.strictEqual(dotSlash.get('iterate-skill.tar.gz'), H, './ prefix should parse');

  const subpath = parseChecksums(`${H}  dist/iterate-skill.tar.gz\n`);
  assert.strictEqual(subpath.get('iterate-skill.tar.gz'), H, 'subpath entries should match by basename');

  const starredSubpath = parseChecksums(`${H}  *./release/iterate-skill-1.2.3.tar.gz\n`);
  assert.strictEqual(starredSubpath.get('iterate-skill-1.2.3.tar.gz'), H, '*./ and versioned subpath should match by basename');

  // Multiple leading '*' markers must be stripped like Python's lstrip("*")
  // (a malformed entry must never leave a leading '*' in the basename).
  const multiStar = parseChecksums(`${H}  **iterate-skill.tar.gz\n`);
  assert.strictEqual(multiStar.get('iterate-skill.tar.gz'), H, 'all leading * markers should strip (lstrip matching)');

  // Comment lines ('#') must be ignored like the Python side.
  const withComment = parseChecksums(`# generated by CI\n${H}  iterate-skill.tar.gz\n`);
  assert.strictEqual(withComment.get('iterate-skill.tar.gz'), H, 'comment lines should be ignored');
  assert.strictEqual(withComment.size, 1, 'comment lines must not create entries');

  // A non-hex digest in any line must be skipped (fail-closed: the missing
  // asset aborts install later) instead of being parsed as an expected hash.
  const garbage = parseChecksums(`${H}  iterate-skill.tar.gz\nnot-a-hash  other.bin\n`);
  assert.strictEqual(garbage.get('iterate-skill.tar.gz'), H, 'valid line still parses');
  assert.strictEqual(garbage.has('other.bin'), false, 'non-hex digest must be dropped');
  assert.strictEqual(garbage.size, 1, 'garbage lines must not create entries');

  // A duplicate basename with a *different* digest must refuse the whole file
  // (tampered or hand-corrupted checksum) rather than silently pick a winner.
  assert.throws(
    () => parseChecksums(`${H}  x.tar.gz\n${I}  x.tar.gz\n`),
    InstallerError,
    'conflicting duplicate must throw',
  );

  // The same digest repeated is harmless (idempotent/regenerated file).
  const dedup = parseChecksums(`${H}  x.tar.gz\n${H}  x.tar.gz\n`);
  assert.strictEqual(dedup.size, 1, 'identical duplicate should dedupe');
  assert.strictEqual(dedup.get('x.tar.gz'), H);

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

  // parseArgs: default token comes from $GITHUB_TOKEN through normalizeToken
  // (trimmed), and an absent/unset variable resolves to null — the object may
  // only ever carry the normalized value.
  const savedToken = process.env.GITHUB_TOKEN;
  try {
    delete process.env.GITHUB_TOKEN;
    assert.strictEqual(parseArgs([]).token, null, 'no env token should default to null');
    process.env.GITHUB_TOKEN = '  gh_default_token_1  ';
    assert.strictEqual(parseArgs([]).token, 'gh_default_token_1', 'env token should be normalized into the default');
    assert.strictEqual(parseArgs(['--token', 'gh_explicit_2']).token, 'gh_explicit_2', '--token should override the env default');
  } finally {
    if (savedToken === undefined) delete process.env.GITHUB_TOKEN;
    else process.env.GITHUB_TOKEN = savedToken;
  }

  // parseArgs: -h/--help and -v/--version must short-circuit parsing — later
  // malformed flags (unknown options or value-consuming flags missing values
  // or swallowing the next flag) must NOT turn help/version into an error.
  const shortCircuit = [
    ['--help', '--bogus'],
    ['--help', '--ai'],
    ['-h', '--target'],
    ['--version', '--bogus'],
    ['--version', '--token'],
    ['-v', '--ai', '--force'],
  ];
  for (const argv of shortCircuit) {
    const opts = parseArgs(argv);
    assert.ok(
      opts.mode === 'help' || opts.mode === 'version',
      `${argv.join(' ')} should short-circuit to mode, got ${opts.mode}`,
    );
  }
  assert.strictEqual(parseArgs(['--help', '--ai', 'trae']).mode, 'help', 'help wins over a valid later flag');
  assert.strictEqual(parseArgs(['--force', '--help']).mode, 'help', 'help after a normal flag still sets mode');
  assert.strictEqual(parseArgs(['--ai', 'trae', '--version']).mode, 'version', 'version after a normal flag still sets mode');

  // parseArgs: value-consuming flags must reject a following flag as their
  // value instead of silently swallowing it (regression: `--ai --force`
  // previously set ai='--force' and misled the Python side with an invalid
  // choice). process.exit is stubbed so the error path is assertable.
  const origExit = process.exit;
  process.exit = (code) => {
    throw new Error(`exit(${code})`);
  };
  try {
    assert.throws(() => parseArgs(['--ai', '--force']), /exit\(1\)/, '--ai must reject a flag as its value');
    assert.throws(() => parseArgs(['--target', '--global']), /exit\(1\)/, '--target must reject a flag as its value');
    assert.throws(() => parseArgs(['--token', '--yes']), /exit\(1\)/, '--token must reject a flag as its value');
    assert.throws(() => parseArgs(['--ai']), /exit\(1\)/, '--ai without a value must error');
    assert.throws(() => parseArgs(['--token']), /exit\(1\)/, '--token without a value must error');
  } finally {
    process.exit = origExit;
  }

  // parseArgs: a bare positional argument must produce a warning instead of
  // being silently ignored (fix: typos like "npx iterate-skill-installer trae").
  const origLog = console.log;
  const warnings = [];
  console.log = (msg) => { warnings.push(msg); };
  try {
    const opts = parseArgs(['trae', '--force']);
    assert.strictEqual(opts.force, true, 'known flags still parse alongside positionals');
    assert.ok(
      warnings.some((w) => w.includes('Ignoring unexpected positional argument: trae')),
      `positional arg should warn, got: ${JSON.stringify(warnings)}`,
    );
  } finally {
    console.log = origLog;
  }

  // parseArgs: --global + --target together must warn that the later flag wins.
  const conflictLogs = [];
  console.log = (msg) => { conflictLogs.push(msg); };
  try {
    const targetThenGlobal = parseArgs(['--target', '/proj', '--global']);
    assert.strictEqual(targetThenGlobal.global, true, 'later --global wins');
    assert.strictEqual(targetThenGlobal.target, null, 'later --global clears the target');
    assert.ok(
      conflictLogs.some((w) => w.includes('--global overrides --target')),
      `conflict should warn, got: ${JSON.stringify(conflictLogs)}`,
    );
    const globalThenTarget = parseArgs(['--global', '--target', '/proj']);
    assert.strictEqual(globalThenTarget.global, false, 'later --target wins');
    assert.strictEqual(globalThenTarget.target, '/proj', 'later --target is kept');
    assert.ok(
      conflictLogs.some((w) => w.includes('--target overrides --global')),
      `conflict should warn, got: ${JSON.stringify(conflictLogs)}`,
    );
  } finally {
    console.log = origLog;
  }

  console.log('mode.test.js: all parseArgs tests passed');

  // buildPythonInstallArgs: a relative --target must be resolved against the
  // current working directory (the Python installer runs with a different
  // cwd, so the raw relative path would point at the wrong place).
  const resolved = buildPythonInstallArgs({ ai: 'trae', target: 'rel/sub', force: true, globalInstall: false });
  assert.deepStrictEqual(
    resolved,
    ['--ai', 'trae', '--target', path.resolve('rel/sub'), '--force'],
    'relative --target should be resolved against cwd',
  );
  const globalArgs = buildPythonInstallArgs({ ai: null, target: null, force: false, globalInstall: true });
  assert.deepStrictEqual(globalArgs, ['--global'], 'global flag should be forwarded');
  assert.deepStrictEqual(
    buildPythonInstallArgs({ ai: null, target: '/abs/target', force: false, globalInstall: false }),
    ['--target', '/abs/target'],
    'absolute --target is passed through unchanged',
  );
  assert.deepStrictEqual(buildPythonInstallArgs({ ai: null, target: null, force: false, globalInstall: false }), [], 'no flags -> empty argv');

  console.log('mode.test.js: all buildPythonInstallArgs tests passed');

  // isGithubApiUrl: the caller's PAT must only ever be attached to the
  // api.github.com host — never to public release-asset / other URLs
  // (credential surface minimalism, mirroring scripts/install.py).
  assert.strictEqual(isGithubApiUrl('https://api.github.com/repos/jingzhao-l/iterate-skill/releases/latest'), true, 'api host should match');
  assert.strictEqual(isGithubApiUrl('https://api.github.com.evil.com/x'), false, 'lookalike host must not match');
  assert.strictEqual(isGithubApiUrl('https://release-assets.githubusercontent.com/foo.tar.gz'), false, 'asset host must not receive the token');
  assert.strictEqual(isGithubApiUrl('https://github.com/x'), false, 'github.com is not the API host');
  assert.strictEqual(isGithubApiUrl('not a url'), false, 'malformed url must not match');

  console.log('mode.test.js: all isGithubApiUrl tests passed');

  // normalizeToken: a token smuggled in with whitespace (e.g. a trailing
  // newline from `$(cat secret)`) must be trimmed; an all-whitespace or empty
  // value is treated as "no token" instead of a 401-baiting credential.
  assert.strictEqual(normalizeToken('  gh_abc  '), 'gh_abc', 'token should be trimmed');
  assert.strictEqual(normalizeToken('gh_abc\n'), 'gh_abc', 'trailing newline should be trimmed');
  assert.strictEqual(normalizeToken('   '), null, 'blank token should become null');
  assert.strictEqual(normalizeToken(''), null, 'empty token should become null');
  assert.strictEqual(normalizeToken(null), null, 'null token should stay null');
  assert.strictEqual(normalizeToken(undefined), null, 'undefined token should become null');
  assert.strictEqual(parseArgs(['--token', '  gh_xyz ']).token, 'gh_xyz', '--token value should be trimmed');

  console.log('mode.test.js: all normalizeToken tests passed');

  // buildAuthFlags: the PAT must only ride on api.github.com requests, and
  // even there redirects must be forbidden so the raw -H Authorization header
  // cannot be echoed onto a foreign host in a -L redirect chain.
  const api = 'https://api.github.com/repos/jingzhao-l/iterate-skill/releases/latest';
  assert.deepStrictEqual(
    buildAuthFlags(api, 'tok'),
    ['-H', 'Authorization: Bearer tok', '--max-redirs', '0'],
    'api request with a token must attach auth and forbid redirects',
  );
  assert.deepStrictEqual(buildAuthFlags('https://release-assets.githubusercontent.com/x', 'tok'), [], 'asset URL must never carry the token');
  assert.deepStrictEqual(buildAuthFlags(api, null), [], 'no token means no auth flags');
  assert.deepStrictEqual(buildAuthFlags(api, ''), [], 'blank token means no auth flags');

  console.log('mode.test.js: all buildAuthFlags tests passed');

  // runCommand: a wedged child must be SIGKILLed after the timeout instead of
  // hanging the installer forever, and the rejection must make the failure
  // classable (InstallerError).
  const timedOut = await runCommand('sleep', ['30'], { timeout: 300 }).then(
    () => ({ timedOut: false }),
    (err) => ({ timedOut: err instanceof InstallerError && /timed out after 300 ms/.test(err.message) }),
  );
  assert.ok(timedOut.timedOut, 'runCommand must reject with a "timed out" InstallerError on timeout');

  // runCommand: stdout retention must be bounded (no unbounded memory growth
  // for a chatty producer) while still returning the tail of the output.
  const script = "for (let i = 0; i < 200000; i++) console.log('line-' + i);";
  const tail = await runCommand(process.execPath, ['-e', script]);
  assert.ok(tail.includes('line-199999'), 'chatty output must keep its tail');
  assert.ok(tail.length <= 1024 * 1024, 'retained output must be bounded (1 MiB cap)');

  // runPythonInstall: a signal-killed child reports a null exit code which
  // Node surfaces as closer code null; the shell would read that as success,
  // so the promise must normalize it to a non-zero failure. Using a tiny
  // SIGKILL-itself script stands in for a wedged python subprocess.
  const killSelf = path.join(os.tmpdir(), `iterate-kill-self-${process.pid}.js`);
  fs.writeFileSync(killSelf, 'process.kill(process.pid, "SIGKILL");\n');
  try {
    const code = await runPythonInstall(process.execPath, killSelf, []);
    assert.strictEqual(code, 1, 'null (signal-killed) close code must normalize to exit 1');
  } finally {
    fs.rmSync(killSelf, { force: true });
  }

  console.log('mode.test.js: all runCommand/runPythonInstall hardening tests passed');
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});