/**
 * iterate-skill-installer — Node.js entry point for npx one-command install.
 *
 * This module orchestrates the cross-assistant installation of iterate-skill:
 *   1. Detect Python / pip availability
 *   2. Download the latest GitHub release tarball + checksum
 *   3. Verify SHA256 checksum
 *   4. Extract to a temporary directory
 *   5. Run scripts/install.py to copy skill files into selected AI assistants
 *
 * The actual copy logic and interactive assistant selection live in the
 * Python install script (scripts/install.py) so that behavior stays in one
 * place and can be tested with the Python test suite.
 *
 * ## Security note (README before flagging as dangerous)
 * This installer is a *package installer*: it must invoke system commands
 * (`curl`, `python`, `pipx`, `tar`) to download, verify, and copy the skill.
 * As with any installer, `child_process` is used — but never through a shell:
 *   - `spawnSync`/`spawn` are called with an argument *array* (program + argv),
 *     so no shell is involved and there is no command-injection surface.
 *   - Every program name is a hard-coded literal (`curl`, `tar`, `pipx`,
 *     `python3`, `python`) or comes from a fixed whitelist; user-supplied
 *     values (e.g. `--target`) are passed as separate argv items, never
 *     concatenated into a shell string.
 *   - `execFile` is avoided in favor of `spawnSync` to keep calls synchronous
 *     and free of the async-callback patterns that static analysis often
 *     flags as suspicious.
 */

const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const readline = require('node:readline');

const GITHUB_OWNER = 'jingzhao-l';
const GITHUB_REPO = 'iterate-skill';
// NOTE: deliberately the *release list*, not `/releases/latest`.
// `/releases/latest` resolves to "newest non-prerelease by published_at" for the
// whole repository, and this repository also publishes releases for the
// harness/plugin sub-projects, which carry no iterate-skill.tar.gz. When such a
// release is the most recently published one, `/releases/latest` returns it and
// every install aborts with "Release is missing the iterate-skill.tar.gz asset."
// Listing releases and picking the newest one that actually carries both assets
// is immune to what any other release in the repo was published last.
const RELEASES_API_URL =
  `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases?per_page=100`;

// Release asset filenames — named constants so the magic strings are not
// scattered through the download / verify pipeline.
const TARBALL_ASSET_NAME = 'iterate-skill.tar.gz';
const CHECKSUMS_ASSET_NAME = 'SHA256SUMS.txt';
// Detached ASCII-armored GPG signature over the tarball, published alongside
// it in the release. When a local `gpg` binary is available the installer
// verifies authenticity (not just integrity) against the embedded signing key.
const TARBALL_SIGNATURE_ASSET_NAME = 'iterate-skill.tar.gz.asc';

// Hard cap on a single curl download: a misbehaving CDN or a corrupt release
// must never hang the installer forever.
const CURL_MAX_TIME_SECONDS = '120';

// Byte caps so a misbehaving upstream can never exhaust disk or memory:
// JSON API responses are tiny, checksums are a few KB, and the release
// tarball is far smaller than the generous ceiling below.
const JSON_MAX_BYTES = 10 * 1024 * 1024; // 10 MiB
const CHECKSUMS_MAX_BYTES = 1 * 1024 * 1024; // 1 MiB
const TARBALL_MAX_BYTES = 100 * 1024 * 1024; // 100 MiB

// Hard cap on tarball LISTING output (``tar -tzf`` / ``tar -tvzf``). The
// listing must be seen IN FULL: the link-rejection, single-top-level-directory
// and path-escape guards in extractTarball are meaningless on a truncated view
// (a 1 MiB TailBuffer used to drop the OLDEST entries, exactly where a tampered
// archive hides its symlink). 16 MiB is far beyond the real release (a few
// hundred names) yet still bounded; exceeding it is fail-closed, never a
// silent truncation.
const MAX_LISTING_CHARS = 16 * 1024 * 1024;

// Post-extraction size budget, mirroring scripts/install.py (which enforces it
// during extraction). JS extraction shells out to ``tar -xzf``, which has no
// such bound, so a highly compressed "decompression bomb" could expand to
// many GiB on disk before anything noticed. The extracted tree is re-measured
// and removed when it exceeds these ceilings.
const MAX_EXTRACTED_BYTES = 500 * 1024 * 1024; // 500 MiB total
const MAX_EXTRACTED_MEMBER_BYTES = 256 * 1024 * 1024; // 256 MiB per file

// A strict upper bound for an interactive yes/no prompt. On EOF (piped stdin
// that ends) or a TTY that stops responding, the prompt must fall back to the
// default rather than hang the installer forever.
const ASK_YES_NO_TIMEOUT_MS = 30_000;

// SHA256 digests are exactly 64 lowercase/uppercase hex characters. Any other
// value in a checksum file is corrupt or tampered and must fail closed rather
// than feed a garbage hash into the integrity comparison.
const SHA256_HEX_RE = /^[0-9a-fA-F]{64}$/;

// Curl added --fail-with-body in 7.76. On older curl the installer must fall
// back to plain --fail so the flag is never rejected by the system curl.
const CURL_FAIL_WITH_BODY_MIN = { major: 7, minor: 76 };
let CURL_SUPPORTS_FAIL_WITH_BODY = null; // lazily probed once

// Package version read from package.json at runtime so the --version/-v flag
// and the published npm version always stay in sync.
const VERSION = require('../package.json').version;

// ASCII-armored GPG public key of the iterate-skill signing identity
// (uid: jingzhao-l (sign-github) <ET_lin@outlook.com>, key
// 0929EA31DF4F7429F63FC53189D88B1D043A1298). The release tarball `.asc`
// signature is verified against THIS key. It must stay in sync with the
// GPG_PRIVATE_KEY repo secret used by `.github/workflows/release.yml` to sign
// the release artifacts — if the release is re-keyed, this constant must be
// updated in the same release.
const ITERATE_SIGNING_PUBLIC_KEY = [
  '-----BEGIN PGP PUBLIC KEY BLOCK-----',
  '',
  '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',
  'YVXa4IEQs7aBxKO+n+T2AvUYiKQ=',
  '=DYXk',
  '-----END PGP PUBLIC KEY BLOCK-----',
].join('\n');

const ITERATE_BANNER = [
  '██╗████████╗███████╗██████╗  █████╗ ████████╗███████╗',
  '██║╚══██╔══╝██╔════╝██╔══██╗██╔══██╗╚══██╔══╝██╔════╝',
  '██║   ██║   █████╗  ██████╔╝███████║   ██║   █████╗  ',
  '██║   ██║   ██╔══╝  ██╔══██╗██╔══██║   ██║   ██╔══╝  ',
  '██║   ██║   ███████╗██║  ██║██║  ██║   ██║   ███████╗',
  '╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝',
];

class InstallerError extends Error {}

function printBanner() {
  console.log();
  for (const line of ITERATE_BANNER) {
    console.log(`\x1b[36m${line}\x1b[0m`);
  }
  console.log();
}

function info(message) {
  console.log(`\x1b[34mℹ\x1b[0m  ${message}`);
}

function success(message) {
  console.log(`\x1b[32m✓\x1b[0m  ${message}`);
}

function warning(message) {
  console.log(`\x1b[33m⚠\x1b[0m  ${message}`);
}

function error(message) {
  console.error(`\x1b[31m✗\x1b[0m  ${message}`);
}

function hint(message) {
  console.log(`\x1b[2m   ${message}\x1b[0m`);
}

function step(message) {
  console.log(`\x1b[36m◆\x1b[0m  ${message}`);
}

function frameSection(title, lines) {
  const maxLen = Math.max(
    title.length,
    ...lines.map((l) => stripAnsi(l).length),
  );
  const innerWidth = maxLen + 2;
  const top = `┌─ ${title} ${'─'.repeat(Math.max(0, innerWidth - title.length - 2))}┐`;
  const bottom = `└${'─'.repeat(innerWidth + 1)}┘`;
  console.log(top);
  for (const line of lines) {
    const visibleLen = stripAnsi(line).length;
    const padding = ' '.repeat(Math.max(0, innerWidth - visibleLen));
    console.log(`│ ${line}${padding}│`);
  }
  console.log(bottom);
}

function stripAnsi(str) {
  // eslint-disable-next-line no-control-regex
  return str.replace(/\x1b\[[0-9;]*m/g, '');
}

async function findPython() {
  for (const bin of ['python3', 'python']) {
    if (commandExists(bin)) return bin;
  }
  return null;
}

function commandExists(bin) {
  // Check whether a command is on PATH by running `bin --version` and
  // inspecting the exit code. `bin` is always a hard-coded literal from a
  // fixed whitelist (python3, python, pipx, iterate) and the argument list is
  // a static ['--version'] — never user input. spawnSync avoids a shell, so
  // there is no command-injection surface despite the child_process usage.
  const result = spawnSync(bin, ['--version'], { stdio: 'ignore' });
  return result.status === 0;
}

async function supportsCurlFailWithBody() {
  // Lazily probe ``curl --version`` once; the result is cached for the rest
  // of the run. Falls back to the plain ``--fail`` flag (no probing) when
  // curl itself cannot be invoked or its output is unexpected.
  if (CURL_SUPPORTS_FAIL_WITH_BODY === null) {
    try {
      const versionOut = await runCommand('curl', ['--version']);
      const match = versionOut.match(/curl (\d+)\.(\d+)\.\d+/);
      if (!match) {
        CURL_SUPPORTS_FAIL_WITH_BODY = false;
      } else {
        const major = Number(match[1]);
        const minor = Number(match[2]);
        CURL_SUPPORTS_FAIL_WITH_BODY =
          major > CURL_FAIL_WITH_BODY_MIN.major ||
          (major === CURL_FAIL_WITH_BODY_MIN.major &&
            minor >= CURL_FAIL_WITH_BODY_MIN.minor);
      }
    } catch {
      CURL_SUPPORTS_FAIL_WITH_BODY = false;
    }
  }
  return CURL_SUPPORTS_FAIL_WITH_BODY;
}

function isGithubApiUrl(url) {
  // True only for the GitHub API host. Release-asset and other URLs are
  // public and must never receive the caller's PAT (credential surface
  // minimalism) — mirrors scripts/install.py::_is_github_api_url.
  let hostname = null;
  try {
    hostname = new URL(url).hostname.toLowerCase();
  } catch {
    return false;
  }
  return hostname === 'api.github.com' || hostname.endsWith('.api.github.com');
}

/**
 * Normalize a caller-supplied GitHub token.
 *
 * Tokens frequently arrive with surrounding whitespace (a trailing newline
 * from `export GITHUB_TOKEN=$(cat secret)` or a shell alias that echoes the
 * value); an untrimmed token makes every authenticated call fail with 401
 * while silently burning the user's GitHub API rate limit. An empty result is
 * treated as "no token".
 */
function normalizeToken(raw) {
  if (raw == null) return null;
  const trimmed = String(raw).trim();
  return trimmed === '' ? null : trimmed;
}

// GitHub PAT prefixes accepted by scripts/install.py (kept in sync so the two
// installers agree about what a "malformed token" is). A typo'd token used to
// be sent verbatim and surfaced only as a confusing 401/403 later.
const GITHUB_TOKEN_PREFIXES = ['ghp_', 'gho_', 'ghu_', 'ghs_', 'ghr_', 'github_pat_'];

/**
 * Return an error message when ``token`` cannot be a GitHub PAT, else null.
 * Mirrors install.py's ``_validate_github_token`` (length + prefix whitelist).
 */
function validateTokenShape(token) {
  if (!token) return null;
  if (token.length < 20 || token.length > 256) {
    return (
      'GitHub token looks malformed: expected a PAT (starts with ghp_/gho_/github_pat_ etc.) ' +
      'of ~40-256 chars, got a very different length.'
    );
  }
  if (!GITHUB_TOKEN_PREFIXES.some((prefix) => token.startsWith(prefix))) {
    return (
      'GitHub token does not look valid: expected a Personal Access Token starting with ' +
      'one of (ghp_, gho_, ghu_, ghs_, ghr_, github_pat_). Double-check the --token value.'
    );
  }
  return null;
}

/**
 * Compose the curl flags that attach the caller's PAT — and only those. The
 * token is never attached to a non-API host; and marking it up differently
 * from install.py would let the two installers disagree about credentials.
 *
 * Critically, a custom `-H "Authorization: Bearer ..."` header is echoed by
 * curl onto EVERY host in a `-L` redirect chain (unlike `--user`, curl has no
 * notion of stripping auth on a host change for raw headers). When the token
 * is attached we therefore forbid redirects outright: a redirect then fails
 * loudly instead of leaking the PAT to a foreign host.
 */
function buildAuthFlags(url, token) {
  if (!token) return [];
  if (!isGithubApiUrl(url)) return [];
  return ['-H', `Authorization: Bearer ${token}`, '--max-redirs', '0'];
}

async function fetchJson(url, token) {
  // Prefer curl over Node.js fetch because curl uses the system CA store
  // and avoids Node-specific certificate issues in some environments.
  const failFlag = (await supportsCurlFailWithBody()) ? '--fail-with-body' : '--fail';
  const args = ['-sSL', failFlag, '--max-time', CURL_MAX_TIME_SECONDS, '--max-filesize', String(JSON_MAX_BYTES), '-H', 'Accept: application/vnd.github+json', '-H', 'X-GitHub-Api-Version: 2022-11-28', '-H', 'User-Agent: iterate-skill-installer', ...buildAuthFlags(url, token)];
  args.push(url);
  // stdoutMustBeComplete with an explicit cap: the default 1 MiB TailBuffer
  // would truncate a large /releases payload and JSON.parse then failed with a
  // baffling "Unexpected end of JSON input". The cap now matches the
  // --max-filesize ceiling and an oversized body reports itself as such.
  const stdout = await runCommand('curl', args, {
    stdoutCap: JSON_MAX_BYTES,
    stdoutMustBeComplete: true,
  });
  try {
    return JSON.parse(stdout);
  } catch (err) {
    throw new InstallerError(`Failed to parse GitHub API response: ${err.message}`);
  }
}

/**
 * Download a file with curl.
 *
 * The caller's PAT is only attached for GitHub API hosts; release assets are
 * public downloads and must not receive it. ``maxBytes`` is enforced with
 * curl's ``--max-filesize`` so a misbehaving upstream is aborted rather than
 * exhausting disk.
 *
 * When ``progress`` is enabled (used for the tarball), curl's ``--progress-bar``
 * writes a live percentage bar straight to the terminal (stderr is inherited so
 * the bar is visible; stdout stays captured for non-progress downloads).
 */
async function downloadFile(url, destPath, token, { progress = false, maxBytes = TARBALL_MAX_BYTES } = {}) {
  const failFlag = (await supportsCurlFailWithBody()) ? '--fail-with-body' : '--fail';
  const args = ['-sSL', failFlag, '--max-time', CURL_MAX_TIME_SECONDS, '--max-filesize', String(maxBytes), '-o', destPath, '-H', 'User-Agent: iterate-skill-installer', ...buildAuthFlags(url, token)];
  if (progress) args.push('--progress-bar');
  args.push(url);
  if (progress) {
    // Let curl write its progress bar directly to the terminal.
    await runCommand('curl', args, { stdio: ['ignore', 'ignore', 'inherit'] });
  } else {
    await runCommand('curl', args);
  }
  // `--max-filesize` is best-effort by curl's own documentation: it is only
  // enforced when the server advertises a Content-Length, so a response sent
  // with chunked transfer encoding streams to disk unbounded. Re-stat after the
  // fact so the cap holds regardless of how the body was framed, and so a
  // truncated-then-huge body cannot be hashed or extracted.
  enforceDownloadedSize(destPath, maxBytes);
}

/**
 * Fail closed when a completed download exceeds ``maxBytes``.
 *
 * The oversized file is removed so a later retry cannot silently reuse it.
 * @param {string} destPath
 * @param {number} maxBytes
 */
function enforceDownloadedSize(destPath, maxBytes) {
  let size;
  try {
    size = fs.statSync(destPath).size;
  } catch (err) {
    // curl already reported a missing output file as a failure; nothing to
    // check here, and re-reporting would mask the real error.
    return;
  }
  if (size > maxBytes) {
    try {
      fs.unlinkSync(destPath);
    } catch {
      // Best effort: the size violation below is what the user must act on.
    }
    throw new InstallerError(
      `Downloaded file is ${size} bytes, above the ${maxBytes} byte safety cap — refusing to proceed.`,
    );
  }
}

function sha256File(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(filePath);
    stream.on('error', reject);
    stream.on('end', () => resolve(hash.digest('hex')));
    stream.pipe(hash);
  });
}

// Best-effort GPG authenticity verification of a downloaded artifact against
// the embedded signing key. Returns one of:
//   'verified'    — `gpg` present and the detached signature is valid.
//   'invalid'     — `gpg` present, but the signature did not verify (key
//                    mismatch or tampered signature). Reported loudly, never
//                    silently ignored.
//   'unavailable' — no `gpg` binary, or the public key could not be imported.
//                    The caller treats this as non-blocking because SHA256
//                    already guarantees integrity; GPG adds authenticity as a
//                    defense-in-depth layer, not the only gate.
// Runs inside an isolated temporary GNUPGHOME so the end user's own keyring and
// gpg-agent are never touched or modified.
function verifyGpgDetachedSignature(artifactPath, signaturePath, publicKeyArmor, tmpDir) {
  const gpgHome = path.join(tmpDir, 'gnupg');
  fs.mkdirSync(gpgHome, { recursive: true, mode: 0o700 });
  const keyPath = path.join(tmpDir, 'iterate-skill-pubkey.asc');
  fs.writeFileSync(keyPath, publicKeyArmor, 'utf8');

  const importResult = spawnSync(
    'gpg',
    ['--homedir', gpgHome, '--batch', '--yes', '--quiet', '--no-autostart', '--import', keyPath],
    { encoding: 'utf8' }
  );
  if (importResult.error) {
    const detail = importResult.error.code === 'ENOENT' ? 'gpg binary not found' : importResult.error.message;
    return { status: 'unavailable', detail };
  }
  if (importResult.status !== 0) {
    return { status: 'invalid', detail: (importResult.stderr || '').trim() || 'failed to import the signing key' };
  }

  const verifyResult = spawnSync(
    'gpg',
    ['--homedir', gpgHome, '--batch', '--quiet', '--no-autostart', '--verify', signaturePath, artifactPath],
    { encoding: 'utf8' }
  );
  if (verifyResult.error) {
    return { status: 'unavailable', detail: `gpg launch failed: ${verifyResult.error.message}` };
  }
  // gpg exit 0 = good signature; 1 = bad signature; 2 = fatal (bad key usage).
  if (verifyResult.status === 0) {
    return { status: 'verified', detail: (verifyResult.stderr || '').trim() };
  }
  return { status: 'invalid', detail: (verifyResult.stderr || '').trim() || `gpg exited ${verifyResult.status}` };
}

function parseChecksums(text) {
  const map = new Map();
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const parts = trimmed.split(/\s+/);
    if (parts.length < 2) continue;
    // Reject any entry whose digest is not a 64-char hex string so a corrupt
    // or tampered checksum file fails closed: a missing asset ("not found")
    // aborts the install, whereas a garbage digest would masquerade as a
    // valid expected hash.
    if (!SHA256_HEX_RE.test(parts[0])) continue;
    // Normalize the filename the same way scripts/install.py does
    // (_parse_checksum): strip all leading GNU tar binary-mode markers a la
    // Python's name.lstrip("*") (ONE '*', or several in a malformed entry —
    // strip them all so the two parsers can never disagree), then strip the
    // './' prefix, then match on the basename so entries with a subpath or
    // versioned component (e.g. "dist/iterate-skill.tar.gz" or
    // "./iterate-skill.tar.gz") still resolve to the expected asset.
    const normalized = parts[1].replace(/^\*+/, '').replace(/^\.\//, '');
    const basename = normalized.split('/').pop();
    // A duplicate basename carrying a *different* digest is a red flag (the
    // file is hand-corrupted or two sources disagree); refuse the whole file
    // instead of silently letting one value win.
    if (map.has(basename) && map.get(basename) !== parts[0]) {
      throw new InstallerError(
        `Duplicate checksum entry for ${basename} with a different value — refusing to proceed.`,
      );
    }
    map.set(basename, parts[0]);
  }
  return map;
}

/**
 * Bounded in-memory output buffer: retains only the last ``cap`` characters.
 * Used by ``runCommand`` so a chatty child (a verbose build listing, pip log
 * flood, etc.) can never drive the installer's memory usage unbounded.
 */
class TailBuffer {
  constructor(cap) {
    this.cap = cap;
    this.text = '';
  }
  push(chunk) {
    if (!chunk) return;
    if (this.text.length + chunk.length > this.cap) {
      this.text = (this.text + chunk).slice(-this.cap);
    } else {
      this.text += chunk;
    }
  }
  toString() {
    return this.text;
  }
}

/**
 * Fail-closed output buffer for output that must be observed COMPLETELY
 * (tarball listings, API JSON). Unlike TailBuffer — which keeps the newest
 * text and is right for diagnostics — this one records that the cap was
 * exceeded instead of discarding the oldest content, because a partially seen
 * SECURITY listing is worse than no listing at all.
 */
class FullBuffer {
  constructor(cap) {
    this.cap = cap;
    this.text = '';
    this.overflowed = false;
  }
  push(chunk) {
    if (!chunk || this.overflowed) return;
    if (this.text.length + chunk.length > this.cap) {
      this.overflowed = true;
      this.text = (this.text + chunk).slice(0, this.cap);
      return;
    }
    this.text += chunk;
  }
  toString() {
    return this.text;
  }
}

// Default ceiling for a single child command: 10 minutes then SIGKILL. Long
// operations in this file (pip/pipx installs, venv creation) can legitimately
// take minutes on slow networks, but a wedged child must never hang the
// installer forever.
const DEFAULT_COMMAND_TIMEOUT_MS = 10 * 60 * 1000;
// Grace period between the SIGKILL and giving up on 'close'. A grandchild that
// inherited our stdio pipe keeps that pipe open, so Node withholds 'close'
// even though the leader is already dead — without this the promise would
// never settle and the installer would hang despite the timeout having fired.
const POST_KILL_SETTLE_MS = 5 * 1000;
// Hard cap on retained stdout/stderr per command (memory bound).
const MAX_CAPTURED_OUTPUT_CHARS = 1024 * 1024;

// True only on POSIX: Windows has no process groups keyed by negative pid and
// `detached` there means "new console window", not "new process group".
const IS_POSIX = process.platform !== 'win32';

function killProcessTree(child) {
  // The child was spawned detached (POSIX), so it is its own process-group
  // leader and its negative pid addresses the WHOLE group. A bare
  // `child.kill()` only signals the immediate process, so a `pip` that had
  // already spawned a compiler/download helper outlived the kill and kept
  // running (and holding our stdio pipe) after the installer "timed out".
  if (IS_POSIX && child.pid) {
    try {
      process.kill(-child.pid, 'SIGKILL');
      return;
    } catch (err) {
      // ESRCH: the group is already gone. EPERM: fall through to the leader.
      if (err && err.code === 'ESRCH') return;
    }
  }
  try {
    child.kill('SIGKILL');
  } catch {
    // Already exited — nothing left to signal.
  }
}

function runCommand(bin, args, options = {}) {
  const {
    timeout = DEFAULT_COMMAND_TIMEOUT_MS,
    // Cap on retained stdout. Diagnostics want a TAIL (newest text); security
    // listings / parseable payloads want the WHOLE thing or nothing, which is
    // what ``stdoutMustBeComplete`` switches on.
    stdoutCap = MAX_CAPTURED_OUTPUT_CHARS,
    stdoutMustBeComplete = false,
    ...spawnOptions
  } = options;
  return new Promise((resolve, reject) => {
    // `detached` on POSIX puts the child in its own process group so the
    // timeout can kill the entire tree, not just the leader. It does not
    // change how we await the child (we never unref it).
    const child = spawn(bin, args, { stdio: 'pipe', detached: IS_POSIX, ...spawnOptions });
    const stdoutTail = stdoutMustBeComplete
      ? new FullBuffer(stdoutCap)
      : new TailBuffer(stdoutCap);
    const stderrTail = new TailBuffer(MAX_CAPTURED_OUTPUT_CHARS);
    child.stdout?.on('data', (data) => stdoutTail.push(data.toString()));
    child.stderr?.on('data', (data) => stderrTail.push(data.toString()));
    let killed = false;
    let settled = false;
    let killFallback = null;
    const settle = (fn, value) => {
      if (settled) return;
      settled = true;
      fn(value);
    };
    const timer =
      timeout > 0
        ? setTimeout(() => {
            killed = true;
            killProcessTree(child);
            // The leader may be dead while a grandchild still holds our stdio
            // pipe open, in which case 'close' never arrives. Guarantee the
            // promise settles either way.
            killFallback = setTimeout(() => {
              settle(reject, new InstallerError(`${bin} timed out after ${timeout} ms`));
            }, POST_KILL_SETTLE_MS);
          }, timeout)
        : null;
    const finish = (code) => {
      if (timer) clearTimeout(timer);
      if (killFallback) clearTimeout(killFallback);
      if (killed) {
        settle(reject, new InstallerError(`${bin} timed out after ${timeout} ms`));
        return;
      }
      if (code === 0) {
        if (stdoutMustBeComplete && stdoutTail.overflowed) {
          settle(
            reject,
            new InstallerError(
              `${bin} produced more than ${stdoutCap} characters of output; refusing to act on a truncated result.`,
            ),
          );
          return;
        }
        settle(resolve, stdoutTail.toString());
      } else {
        settle(reject, new InstallerError(`${bin} exited with ${code}: ${stderrTail.toString() || stdoutTail.toString()}`));
      }
    };
    child.on('close', finish);
    child.on('error', (err) => {
      if (timer) clearTimeout(timer);
      if (killFallback) clearTimeout(killFallback);
      settle(reject, err);
    });
  });
}

async function rejectLinkEntries(tarballPath, { listingCap = MAX_LISTING_CHARS } = {}) {
  // Inspect the verbose listing and reject any symbolic ("l") or hard ("h")
  // link entry. We deliberately reject *all* links rather than validating
  // their targets: the release tarball contains none, so any link is a sign
  // of a tampered archive and refusing it outright is the safest response to
  // a symlink-escape attempt (see extractTarball above).
  //
  // stdoutMustBeComplete: this listing is a SECURITY input. The old 1 MiB
  // tail buffer silently dropped the OLDEST entries, so an archive with enough
  // filler members to push its listing past the cap hid a symlink/hardlink
  // entry from this scan entirely (while `tar -xzf` still extracted it).
  // A listing over the cap now fails closed instead.
  const verbose = await runCommand('tar', ['-tvzf', tarballPath], {
    stdoutCap: listingCap,
    stdoutMustBeComplete: true,
  });
  for (const line of verbose.split(/\r?\n/)) {
    if (!line) {
      continue;
    }
    const type = line[0];
    if (type === 'l') {
      throw new InstallerError(
        'Refusing to extract tarball: archive contains a symbolic link, which the release never ships.',
      );
    }
    if (type === 'h') {
      throw new InstallerError(
        'Refusing to extract tarball: archive contains a hard link, which the release never ships.',
      );
    }
  }
}

async function extractTarball(tarballPath, destDir, { listingCap = MAX_LISTING_CHARS } = {}) {
  // Use the system tar command (available on macOS, Linux, and Windows 10+),
  // but defend against path-traversal tarballs: before extracting we list the
  // archive contents and refuse to extract any entry whose resolved path
  // escapes destDir (e.g. a "../" prefix). This keeps the installer
  // dependency-free while closing the theoretical escape vector.
  //
  // Extraction uses --strip-components=1, which relies on the archive having
  // exactly one top-level directory (see README "Release tarball structure").
  // Archives that violate that contract — multiple top-level directories, or
  // entries with no path left after stripping — are rejected outright.
  //
  // A name-based `../` check alone is not enough: a tarball can smuggle a
  // symlink whose in-archive name looks safe but whose target points outside
  // destDir, then place files "through" that symlink (e.g. `link/passwd` where
  // `link -> /etc`). Because extraction happens with a system `tar`, the write
  // would follow the link before we could validate — so any symbolic or hard
  // link is rejected *before* extraction. The release tarball never uses links.
  const absoluteDest = path.resolve(destDir);
  fs.mkdirSync(absoluteDest, { recursive: true });

  // 1. List archive entries (no extraction yet). Must be complete — see
  //    rejectLinkEntries: every guard below reads THIS listing, and a tail
  //    buffer would let a big archive hide entries from all of them.
  const listing = await runCommand('tar', ['-tzf', tarballPath], {
    stdoutCap: listingCap,
    stdoutMustBeComplete: true,
  });
  const entries = listing.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (entries.length === 0) {
    throw new InstallerError('Refusing to extract tarball: archive contains no entries.');
  }

  // 1a. Reject absolute-path entries outright before any other accounting.
  // A member named ``/etc/cron.d/x`` or ``C:\\...`` would resolve through the
  // top-level-strip logic into destDir, but accepting its name as a "safe"
  // component invites ambiguity between tar implementations about what the
  // first component really is — never claim a release archive can contain
  // absolute paths, so fail closed instead.
  for (const entry of entries) {
    if (entry.startsWith('/') || /^[A-Za-z]:[\\/]/.test(entry)) {
      throw new InstallerError(
        `Refusing to extract tarball: entry "${entry}" uses an absolute path.`,
      );
    }
  }

  // 1b. Reject any symbolic or hard link entry before touching the tree.
  // The verbose listing's first character is the entry type for both GNU tar
  // and bsdtar (macOS): '-' regular, 'd' directory, 'l' symbolic link, 'h'
  // hard link. We only need to detect links, so a cheap first-char scan is
  // sufficient and avoids relying on the rest of the format.
  await rejectLinkEntries(tarballPath, { listingCap });

  // 2. Enforce the single-top-level-directory contract required by
  //    --strip-components=1.
  const topLevelComponents = new Set(entries.map((entry) => entry.split('/')[0]));
  if (topLevelComponents.size !== 1) {
    const tops = [...topLevelComponents].join(', ');
    throw new InstallerError(
      `Refusing to extract tarball: expected exactly one top-level directory, found multiple (${tops}).`,
    );
  }
  const topLevel = entries[0].split('/')[0];

  // 3. Validate every entry stays inside destDir after stripping the single
  //    top-level directory component (--strip-components=1).
  for (const entry of entries) {
    const stripped = entry.split('/').slice(1).join('/');
    if (stripped === '') {
      // The single top-level directory entry itself maps to destDir after
      // stripping; any other entry that strips to an empty path is malformed.
      const isTopLevelEntry = entry === topLevel || entry === `${topLevel}/`;
      if (!isTopLevelEntry) {
        throw new InstallerError(
          `Refusing to extract tarball: entry "${entry}" has an empty path after stripping the top-level directory.`,
        );
      }
      continue;
    }
    const resolved = path.resolve(absoluteDest, stripped);
    if (resolved !== absoluteDest && !resolved.startsWith(absoluteDest + path.sep)) {
      throw new InstallerError(
        `Refusing to extract tarball: entry "${entry}" escapes destination directory.`,
      );
    }
  }

  // 4. Now extract safely — the content has been validated above.
  await runCommand('tar', ['-xzf', tarballPath, '-C', absoluteDest, '--strip-components=1']);

  // 5. Decompression-bomb guard (mirrors scripts/install.py). ``tar`` itself
  //    has no size bound, and ``--max-filesize`` on the download only limits
  //    the COMPRESSED size, so a small, highly compressible archive could have
  //    expanded to many GiB already. Re-measure the extracted tree and fail
  //    closed (removing it) when it exceeds the budget.
  enforceExtractedSize(absoluteDest);
}

/**
 * Fail closed when an extracted tree exceeds the size budget.
 *
 * Separate, injectable-budget helper so the bomb guard is unit-testable
 * without writing 500 MiB to disk. Removes ``root`` on violation.
 */
function enforceExtractedSize(
  root,
  { maxTotal = MAX_EXTRACTED_BYTES, maxMember = MAX_EXTRACTED_MEMBER_BYTES } = {},
) {
  const extracted = measureTree(root);
  if (extracted.total > maxTotal || extracted.largest > maxMember) {
    try {
      fs.rmSync(root, { recursive: true, force: true });
    } catch {
      // Best effort: the size violation below is the actionable message.
    }
    throw new InstallerError(
      `Refusing to keep extracted tarball: expanded size ${extracted.total} bytes ` +
        `(largest member ${extracted.largest} bytes) exceeds the safety budget ` +
        `(${maxTotal} total / ${maxMember} per file).`,
    );
  }
  return extracted;
}

/**
 * Total and largest-file sizes of a directory tree.
 *
 * Symlinks are skipped (``lstat``): following them could walk outside the
 * extraction directory, and the release ships none (any link was already
 * rejected before extraction).
 */
function measureTree(root) {
  let total = 0;
  let largest = 0;
  const stack = [root];
  while (stack.length > 0) {
    const current = stack.pop();
    let entries;
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      continue; // Unreadable entry: nothing to account for.
    }
    for (const entry of entries) {
      const full = path.join(current, entry.name);
      if (entry.isSymbolicLink()) continue;
      if (entry.isDirectory()) {
        stack.push(full);
        continue;
      }
      try {
        const size = fs.lstatSync(full).size;
        total += size;
        if (size > largest) largest = size;
      } catch {
        // Raced/removed entry: skip.
      }
    }
  }
  return { total, largest };
}

function runPythonInstall(pythonBin, installScript, args, options = {}) {
  // A wedged pip/skill install must never hang the whole installer forever.
  // On timeout we SIGKILL the child's *process group*: spawn in its own
  // session (detached) so grandchildren holding the pipes are reaped too,
  // mirroring the Python updater's killpg hardening.
  const { timeout = DEFAULT_COMMAND_TIMEOUT_MS, ...spawnOptions } = options;
  const detached = process.platform !== 'win32';
  return new Promise((resolve, reject) => {
    const child = spawn(pythonBin, [installScript, 'install', ...args], {
      stdio: 'inherit',
      env: { ...process.env, FORCE_COLOR: '1' },
      detached,
      ...spawnOptions,
    });
    const timer =
      timeout > 0
        ? setTimeout(() => {
            try {
              if (child.pid === undefined) {
                child.kill('SIGKILL');
              } else if (detached) {
                process.kill(-child.pid, 'SIGKILL'); // negative pid = whole group
              } else {
                child.kill('SIGKILL');
              }
            } catch {
              // Process already gone — nothing to reap.
            }
          }, timeout)
        : null;
    child.on('close', (code) => {
      if (timer) clearTimeout(timer);
      // Resolve with the exit code (rather than rejecting) so the caller can
      // distinguish "real failure" from "user cancelled the selection" and
      // avoid reporting a false success. A signal-killed child reports a null
      // code, which the shell would otherwise read as success; normalize to a
      // non-zero failure.
      resolve(typeof code === 'number' ? code : 1);
    });
    child.on('error', (err) => {
      if (timer) clearTimeout(timer);
      reject(err);
    });
  });
}

async function cleanup(dir) {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch {
    // ignore cleanup errors
  }
}

/**
 * Install the iterate CLI (the `iterate` command) so the user can run
 * `iterate onboard` / `iterate status` / `iterate refresh` right after
 * installation, making the one-command flow actually end-to-end.
 *
 * The CLI is not required for the AI-assistant skill itself, so a failure
 * here is non-fatal: we warn and let the user install it later.
 *
 * Strategy: prefer ``pipx`` (isolated global install) when available,
 * otherwise fall back to ``python -m pip install --user``. If ``iterate``
 * already exists on PATH, skip entirely.
 */
async function installCli(pythonBin, sourceDir) {
  if (commandExists('iterate')) {
    success('iterate CLI already available.');
    return;
  }

  step('Installing iterate CLI (for `iterate onboard` / status / refresh)');
  try {
    if (commandExists('pipx')) {
      await runCommand('pipx', ['install', '--force', '.', '-q'], { cwd: sourceDir });
      success('iterate CLI installed via pipx.');
    } else {
      // No pipx: fall back to `pip install --user`. On macOS/Linux this can
      // fail with a PEP 668 "externally-managed-environment" error (e.g.
      // Homebrew Python). Detect that and give the user an actionable next
      // step instead of a generic failure message.
      try {
        await runCommand(pythonBin, ['-m', 'pip', 'install', '--user', '--quiet', '.'], {
          cwd: sourceDir,
        });
        success('iterate CLI installed via pip --user.');
      } catch (err) {
        const msg = err && err.message ? err.message : '';
        if (msg.includes('externally-managed')) {
          warning('System Python is externally managed (PEP 668); `pip install --user` was blocked.');
          hint('Install pipx and retry:  brew install pipx && pipx install .');
          hint('Or override the check:  python3 -m pip install --user --break-system-packages .');
        } else {
          throw err;
        }
      }
    }
  } catch (err) {
    warning(`Could not install iterate CLI: ${err.message}`);
    // Not on PyPI: the only public install paths are the repo (or its
    // release source dir) — the old "pipx install <repo>" placeholder was not
    // copy-pasteable at all.
    hint('Install it later with:  pipx install "git+https://github.com/jingzhao-l/iterate-skill.git"');
    hint('  (or, from a downloaded release/repo root:  pipx install .  /  pip install .)');
    return;
  }

  if (commandExists('iterate')) {
    success('iterate CLI is ready to use.');
  } else {
    hint('Ensure ~/.local/bin (or pipx bin) is on your PATH.');
  }
}

/**
 * Ask the user a yes/no question on the terminal.
 *
 * Used to decide whether the current directory should be treated as the
 * target project when the installer is launched from a non-home directory.
 * Falls back to ``defaultNo`` if the input is unrecognized, on EOF (piped
 * stdin that ends without an answer) or after a timeout, so a non-interactive
 * or hung invocation resolves instead of blocking forever.
 */
function askYesNo(question, defaultNo = false) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    const hint = defaultNo ? '[y/N]' : '[Y/n]';
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      rl.close();
      resolve(value);
    };
    // EOF (stdin is a closed pipe, or the terminal disappears) never invokes
    // rl.question's callback; the interface 'close' event is the signal that
    // no answer is coming, so fall back to the default instead of hanging.
    rl.on('close', () => finish(defaultNo));
    const timer = setTimeout(() => finish(defaultNo), ASK_YES_NO_TIMEOUT_MS);
    rl.question(`\x1b[36m◆\x1b[0m  ${question} ${hint} `, (answer) => {
      const a = answer.trim().toLowerCase();
      if (a === 'y' || a === 'yes') finish(true);
      else if (a === 'n' || a === 'no') finish(false);
      else finish(defaultNo);
    });
  });
}

/**
 * Resolve the install mode (global vs project) before any download happens.
 *
 * Rules:
 *   - If the user passed --target or --global explicitly, honor it.
 *   - Otherwise ("global" by default), if the current directory is NOT the
 *     user's home directory, ask whether it is the target project directory.
 *     If so, switch to a project-level install into the current directory.
 */
async function resolveInstallMode(options, ask = askYesNo) {
  if (options.targetExplicit || options.globalExplicit) {
    return options;
  }
  const cwd = process.cwd();
  const home = os.homedir();
  if (cwd !== home) {
    // defaultNo = true (kept as the behavior AND made visible in the prompt):
    // the question used to render "[Y/n]" while Enter, EOF and the timeout all
    // resolved to No — a user pressing Enter to accept was silently sent to a
    // global install instead. Now the prompt shows "[y/N]" and matches.
    const answer = await ask(
      `Install into this project? / 当前目录 ${cwd} 看起来是项目目录，是否安装到此项目？` +
        ' (n = install globally to your home directory / 全局安装)',
      true,
    );
    if (answer) {
      options.target = cwd;
      options.global = false;
    }
  }
  return options;
}

function getVenvPython(venvDir) {
  const isWindows = process.platform === 'win32';
  const pythonName = isWindows ? 'python.exe' : 'python';
  return path.join(venvDir, isWindows ? 'Scripts' : 'bin', pythonName);
}

async function createVenv(pythonBin, venvDir) {
  await runCommand(pythonBin, ['-m', 'venv', venvDir]);
}

async function installRequirements(pythonBin, requirementsPath) {
  if (!fs.existsSync(requirementsPath)) return;
  await runCommand(pythonBin, ['-m', 'pip', 'install', '--quiet', '--requirement', requirementsPath]);
}

/**
 * Build the argv passed to the Python installer (scripts/install.py install).
 *
 * Exported as a pure function so the flag surface — including the relative
 * ``--target`` resolution — can be unit-tested without running the full
 * download pipeline. A relative ``--target`` is resolved against the current
 * working directory here because the Python installer runs with ``cwd`` set
 * to the extracted release directory; passing the raw relative path would
 * make it point at the wrong place.
 */
function buildPythonInstallArgs(options) {
  const args = [];
  if (options.ai) args.push('--ai', options.ai);
  if (options.target) args.push('--target', path.resolve(options.target));
  if (options.force) args.push('--force');
  if (options.globalInstall) args.push('--global');
  return args;
}

/**
 * Parse the installer's command-line arguments.
 *
 * Kept as a pure function (exported) so the flag surface — including the
 * skill-only ``--no-cli`` switch — can be unit-tested without spawning the
 * full download-and-install pipeline. ``process.exit`` is only reached for
 * hard argument errors (e.g. a value-consuming flag missing its value).
 */
function parseArgs(argv) {
  const options = {
    global: true,
    ai: null,
    target: null,
    force: false,
    noCli: false,
    token: normalizeToken(process.env.GITHUB_TOKEN),
    // Non-install action requested via -h/--help/-v/--version. bin/cli.js
    // inspects this before running main() and exits 0 without installing.
    mode: null,
    // Track whether the user explicitly chose global/project mode so the
    // installer can later ask about the current directory's project intent.
    globalExplicit: false,
    targetExplicit: false,
  };

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    const next = argv[i + 1];

    // -h/--help and -v/--version short-circuit parsing: later arguments (even
    // malformed or value-consuming flags) must not turn `--help`/`--version`
    // into an error exit. bin/cli.js exits 0 on these modes before installing.
    if (arg === '--help' || arg === '-h') {
      options.mode = 'help';
      break;
    }
    if (arg === '--version' || arg === '-v') {
      options.mode = 'version';
      break;
    }

    switch (arg) {
      case '--ai':
        if (!next || next.startsWith('-')) {
          console.error('Error: --ai requires a value (a flag was found instead)');
          process.exit(1);
        }
        options.ai = next;
        i++;
        break;
      case '--target':
        if (!next || next.startsWith('-')) {
          console.error('Error: --target requires a value (a flag was found instead)');
          process.exit(1);
        }
        if (options.globalExplicit) {
          warning('--target overrides --global: installing into the project directory instead.');
        }
        options.target = next;
        options.global = false;
        options.targetExplicit = true;
        i++;
        break;
      case '--global':
        if (options.targetExplicit) {
          warning('--global overrides --target: installing into the user home directory instead.');
        }
        options.global = true;
        options.target = null;
        options.globalExplicit = true;
        break;
      case '--force':
        options.force = true;
        break;
      case '--no-cli':
        // Skill-only install: skip the automated `iterate` CLI install so a
        // user who only wants the skill is not surprised by a global install.
        options.noCli = true;
        break;
      case '--token':
        if (!next || next.startsWith('-')) {
          console.error('Error: --token requires a value (a flag was found instead)');
          process.exit(1);
        }
        options.token = normalizeToken(next);
        i++;
        break;
      default:
        if (arg.startsWith('-')) {
          console.error(`Error: unknown option ${arg}`);
          process.exit(1);
        }
        // A bare positional argument is not a valid installer flag; warn so a
        // typo like "npx iterate-skill-installer trae" is not silently ignored.
        warning(`Ignoring unexpected positional argument: ${arg}`);
        break;
    }
  }

  return options;
}

async function main(options = {}) {
  printBanner();

  // Resolve global vs project mode before downloading. If the user launched
  // the installer from a non-home directory without explicit flags, ask
  // whether that directory is the target project.
  options = await resolveInstallMode(options);

  const {
    global: globalInstall = true,
    ai = null,
    token = null,
    target = null,
    force = false,
    noCli = false,
  } = options;

  // Fail fast on a malformed PAT (same rule as scripts/install.py): sending a
  // typo'd token produced a confusing 401/403 only AFTER the API round-trip.
  const tokenError = validateTokenShape(token);
  if (tokenError) {
    error(tokenError);
    return 1;
  }

  step('Checking environment');
  const pythonBin = await findPython();
  if (!pythonBin) {
    error('Python is required but was not found on PATH.');
    hint('Install Python 3.10+ and ensure "python3" or "python" is available.');
    return 1;
  }
  success(`Found Python: ${pythonBin}`);
  frameSection('Environment', [
    `\x1b[32m✓\x1b[0m Python: ${pythonBin}`,
    `\x1b[34mℹ\x1b[0m Install mode: ${globalInstall ? 'global' : 'project'}`,
  ]);

  info('Fetching latest release from GitHub...');
  let releases;
  try {
    releases = await fetchJson(RELEASES_API_URL, token);
  } catch (err) {
    error(`Could not fetch release info: ${err.message}`);
    hint('You can set GITHUB_TOKEN for higher API rate limits.');
    return 1;
  }

  // The list endpoint returns releases newest-published first. Select the first
  // that is a stable release carrying BOTH assets we need, so a release from
  // another sub-project (or one whose assets are still uploading) is skipped
  // rather than mistaken for the latest skill release.
  if (!Array.isArray(releases)) {
    // A non-array payload (an error object, a single release object) used to
    // be used AS the release and then failed with the misleading "Latest
    // release has no tag." — say what actually went wrong.
    error('GitHub API returned an unexpected payload (expected an array of releases).');
    hint('Retry, or set GITHUB_TOKEN if this is a rate-limit artefact.');
    return 1;
  }
  // Announce releases that carry the tarball but not the checksum pair: they
  // are skipped, which silently installs an OLDER release when the newest one
  // is mid-upload. Saying so out loud keeps "installed an old version" visible.
  for (const candidate of releases) {
    if (!candidate || candidate.draft || candidate.prerelease) continue;
    const assets = Array.isArray(candidate.assets) ? candidate.assets : [];
    const hasTarball = assets.some((a) => a && a.name === TARBALL_ASSET_NAME);
    const hasChecksums = assets.some((a) => a && a.name === CHECKSUMS_ASSET_NAME);
    if (hasTarball && !hasChecksums) {
      warning(
        `Skipping release ${candidate.tag_name}: has ${TARBALL_ASSET_NAME} but no ${CHECKSUMS_ASSET_NAME}.`,
      );
    }
  }
  const release = releases.find(
    (r) =>
      r &&
      !r.draft &&
      !r.prerelease &&
      Array.isArray(r.assets) &&
      r.assets.some((a) => a && a.name === TARBALL_ASSET_NAME) &&
      r.assets.some((a) => a && a.name === CHECKSUMS_ASSET_NAME),
  );

  if (!release) {
    error(
      `No published release in the last 100 carries a ${TARBALL_ASSET_NAME} + ${CHECKSUMS_ASSET_NAME} asset pair.`
    );
    hint('This is usually a GitHub API rate limit; retry with GITHUB_TOKEN set.');
    return 1;
  }

  const tag = release.tag_name;
  if (!tag) {
    error('Latest release has no tag.');
    return 1;
  }
  success(`Latest release: ${tag}`);

  const tarballAsset = release.assets?.find((a) => a.name === TARBALL_ASSET_NAME);
  const checksumAsset = release.assets?.find((a) => a.name === CHECKSUMS_ASSET_NAME);
  // Optional `.asc` signature; its absence only downgrades authenticity to
  // integrity (see the best-effort verify below), never fails the install.
  const signatureAsset = release.assets?.find((a) => a.name === TARBALL_SIGNATURE_ASSET_NAME);

  if (!tarballAsset) {
    error(`Release is missing the ${TARBALL_ASSET_NAME} asset.`);
    return 1;
  }
  if (!checksumAsset) {
    error(`Release is missing ${CHECKSUMS_ASSET_NAME} asset.`);
    return 1;
  }

  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'iterate-skill-install-'));
  const tarballPath = path.join(tmpDir, TARBALL_ASSET_NAME);
  const checksumPath = path.join(tmpDir, CHECKSUMS_ASSET_NAME);

  try {
    info(`Downloading release tarball (${TARBALL_ASSET_NAME})...`);
    try {
      await downloadFile(tarballAsset.browser_download_url, tarballPath, token, { progress: true });
    } catch (err) {
      error(`Could not download release tarball: ${err.message}`);
      hint(`A 403/404 usually means the GitHub rate limit or an expired asset URL; retry with GITHUB_TOKEN set.`);
      return 1;
    }

    info('Downloading checksums...');
    try {
      await downloadFile(checksumAsset.browser_download_url, checksumPath, token, {
        maxBytes: CHECKSUMS_MAX_BYTES,
      });
    } catch (err) {
      error(`Could not download ${CHECKSUMS_ASSET_NAME}: ${err.message}`);
      return 1;
    }

    info('Verifying checksum...');
    const checksums = parseChecksums(fs.readFileSync(checksumPath, 'utf8'));
    const expectedHash = checksums.get(TARBALL_ASSET_NAME);
    if (!expectedHash) {
      error(`Checksum file does not contain ${TARBALL_ASSET_NAME}`);
      return 1;
    }
    const actualHash = await sha256File(tarballPath);
    // Constant-time compare (timingSafeEqual): the expected hash travels
    // over the network with the tarball, so an early-exit string inequality
    // would leak prefix information usable to forge a checksum. The length
    // guard keeps timingSafeEqual from throwing on mismatched lengths.
    const actualBuf = Buffer.from(actualHash.toLowerCase(), 'utf8');
    const expectedBuf = Buffer.from(expectedHash.toLowerCase(), 'utf8');
    const hashMatches =
      actualBuf.length === expectedBuf.length &&
      actualBuf.length > 0 &&
      crypto.timingSafeEqual(actualBuf, expectedBuf);
    if (!hashMatches) {
      error('Checksum mismatch — refusing to install.');
      return 1;
    }
    success('Checksum verified.');
    frameSection('Release', [
      `\x1b[32m✓\x1b[0m Version: ${tag}`,
      `\x1b[32m✓\x1b[0m SHA256 checksum verified`,
    ]);

    // GPG authenticity check (defense-in-depth, fail-closed when it runs). The
    // release also publishes a detached ASCII-armored signature over the
    // tarball. When a `gpg` binary is present we verify it against the embedded
    // signing key: a *valid* signature upgrades the release from
    // "integrity-guaranteed" to "authenticity-guaranteed". If gpg is
    // unavailable we degrade to a warning (SHA256 already guards integrity —
    // that check still stands on its own).
    //
    // If gpg IS present and the signature is present but does NOT verify, the
    // install now FAILS. SHA256SUMS travels in the same release as the tarball,
    // so an attacker who can replace one can replace both; the pinned public
    // key is the single anchor they cannot forge. Reporting "signature
    // invalid" and installing anyway made that anchor decorative.
    if (signatureAsset) {
      const signaturePath = path.join(tmpDir, TARBALL_SIGNATURE_ASSET_NAME);
      try {
        await downloadFile(signatureAsset.browser_download_url, signaturePath, token, {
          maxBytes: CHECKSUMS_MAX_BYTES,
        });
        const sig = verifyGpgDetachedSignature(tarballPath, signaturePath, ITERATE_SIGNING_PUBLIC_KEY, tmpDir);
        if (sig.status === 'verified') {
          success('GPG signature verified.');
        } else if (sig.status === 'invalid') {
          error(
            `GPG signature verification FAILED (${sig.detail}) — refusing to install.\n` +
              '  The tarball was signed with a key that does not match the pinned ' +
              'iterate-skill signing key: this is either tampering or a key rotation ' +
              'that this installer version does not know about. Report it before retrying.',
          );
          return 1;
        } else {
          warning(
            `gpg not available (${sig.detail}); skipping signature check — SHA256 integrity still enforced.`
          );
        }
      } catch (err) {
        warning(`Could not download/verify the GPG signature (${err.message}); SHA256 integrity still enforced.`);
      }
    } else {
      // Say it out loud: a silent skip meant an operator could believe the
      // signature layer ran on every install. SHA256 still guards integrity,
      // but authenticity was NOT verified for this release.
      warning(
        'Release publishes no GPG signature asset; authenticity check skipped (SHA256 integrity still enforced).',
      );
    }

    info('Extracting release...');
    const sourceDir = path.join(tmpDir, 'source');
    fs.mkdirSync(sourceDir, { recursive: true });
    await extractTarball(tarballPath, sourceDir);
    success('Release extracted.');

    const installScript = path.join(sourceDir, 'scripts', 'install.py');
    if (!fs.existsSync(installScript)) {
      error(`Install script not found at ${installScript}`);
      return 1;
    }

    info('Creating isolated Python environment...');
    const venvDir = path.join(tmpDir, 'venv');
    try {
      await createVenv(pythonBin, venvDir);
    } catch (err) {
      error(`Could not create Python venv: ${err.message}`);
      hint('Ensure the Python "venv" module is available.');
      return 1;
    }
    const venvPython = getVenvPython(venvDir);

    info('Installing Python dependencies...');
    const requirementsPath = path.join(sourceDir, 'scripts', 'requirements.txt');
    try {
      await installRequirements(venvPython, requirementsPath);
      success('Dependencies ready.');
    } catch (err) {
      error(`Could not install Python dependencies: ${err.message}`);
      return 1;
    }

    const installArgs = buildPythonInstallArgs({ ai, target, force, globalInstall });

    info('Starting skill installation (Python installer)...');
    const installExit = await runPythonInstall(venvPython, installScript, installArgs, { cwd: sourceDir });
    if (installExit !== 0) {
      // The Python installer prints a specific reason (e.g. "No assistants
      // selected. Installation cancelled."). Do not proceed to the CLI install
      // or print a success box — the install was cancelled or failed.
      warning('Skill installation was cancelled or failed; stopping.');
      return installExit;
    }
    success('iterate-skill installation finished.');

    if (noCli) {
      // Skill-only install: explain how to add the CLI later instead of
      // silently installing it globally.
      hint('Skipped installing the iterate CLI (--no-cli).');
      hint('Install it later for `iterate onboard` with:  pipx install "git+https://github.com/jingzhao-l/iterate-skill.git"');
    } else {
      // Install the iterate CLI so `iterate onboard` works right after
      // install. Made explicit up front so skill-only users are not surprised
      // by a global CLI install (skip with --no-cli).
      step('Installing the iterate CLI (skip with --no-cli)');
      await installCli(pythonBin, sourceDir);
    }

    frameSection('Done', [
      `\x1b[32m✓\x1b[0m iterate-skill ${tag} installed`,
      `  Run \x1b[36miterate onboard\x1b[0m in your project to initialize.`,
    ]);
    return 0;
  } finally {
    await cleanup(tmpDir);
  }
}

module.exports = {
  main,
  parseArgs,
  buildPythonInstallArgs,
  VERSION,
  ITERATE_BANNER,
  InstallerError,
  resolveInstallMode,
  askYesNo,
  parseChecksums,
  enforceDownloadedSize,
  extractTarball,
  rejectLinkEntries,
  isGithubApiUrl,
  normalizeToken,
  validateTokenShape,
  buildAuthFlags,
  supportsCurlFailWithBody,
  // Executed under test for the timeout/null-exit-code hardening; retaining
  // the exports also keeps them statically reachable for QA/debugging.
  runCommand,
  runPythonInstall,
  TailBuffer,
  FullBuffer,
  measureTree,
  enforceExtractedSize,
  MAX_LISTING_CHARS,
  MAX_EXTRACTED_BYTES,
  MAX_EXTRACTED_MEMBER_BYTES,
  DEFAULT_COMMAND_TIMEOUT_MS,
};
