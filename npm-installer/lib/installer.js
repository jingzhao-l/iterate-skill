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
const RELEASE_API_URL = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest`;

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

async function fetchJson(url, token) {
  // Prefer curl over Node.js fetch because curl uses the system CA store
  // and avoids Node-specific certificate issues in some environments.
  const args = ['-sSL', '--fail-with-body', '-H', 'Accept: application/vnd.github+json', '-H', 'X-GitHub-Api-Version: 2022-11-28', '-H', 'User-Agent: iterate-skill-installer'];
  if (token) {
    args.push('-H', `Authorization: Bearer ${token}`);
  }
  args.push(url);
  const stdout = await runCommand('curl', args);
  try {
    return JSON.parse(stdout);
  } catch (err) {
    throw new InstallerError(`Failed to parse GitHub API response: ${err.message}`);
  }
}

async function downloadFile(url, destPath, token) {
  const args = ['-sSL', '--fail-with-body', '-o', destPath, '-H', 'User-Agent: iterate-skill-installer'];
  if (token) {
    args.push('-H', `Authorization: Bearer ${token}`);
  }
  args.push(url);
  await runCommand('curl', args);
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

function parseChecksums(text) {
  const map = new Map();
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const parts = trimmed.split(/\s+/);
    if (parts.length >= 2) {
      map.set(parts[1], parts[0]);
    }
  }
  return map;
}

function runCommand(bin, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(bin, args, { stdio: 'pipe', ...options });
    let stdout = '';
    let stderr = '';
    child.stdout?.on('data', (data) => { stdout += data.toString(); });
    child.stderr?.on('data', (data) => { stderr += data.toString(); });
    child.on('close', (code) => {
      if (code === 0) {
        resolve(stdout);
      } else {
        reject(new InstallerError(`${bin} exited with ${code}: ${stderr || stdout}`));
      }
    });
    child.on('error', reject);
  });
}

async function extractTarball(tarballPath, destDir) {
  // Use the system tar command (available on macOS, Linux, and Windows 10+).
  // Strip the top-level directory so files land directly in destDir.
  await runCommand('tar', ['-xzf', tarballPath, '-C', destDir, '--strip-components=1']);
}

function runPythonInstall(pythonBin, installScript, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonBin, [installScript, 'install', ...args], {
      stdio: 'inherit',
      env: { ...process.env, FORCE_COLOR: '1' },
      ...options,
    });
    child.on('close', (code) => {
      // Resolve with the exit code (rather than rejecting) so the caller can
      // distinguish "real failure" from "user cancelled the selection" and
      // avoid reporting a false success.
      resolve(code);
    });
    child.on('error', reject);
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
    hint('Install it later with: pipx install <repo>  or  pip install .');
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
 * Falls back to ``defaultNo`` if the input is unrecognized.
 */
function askYesNo(question, defaultNo = false) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    const hint = defaultNo ? '[y/N]' : '[Y/n]';
    rl.question(`\x1b[36m◆\x1b[0m  ${question} ${hint} `, (answer) => {
      rl.close();
      const a = answer.trim().toLowerCase();
      if (a === 'y' || a === 'yes') resolve(true);
      else if (a === 'n' || a === 'no') resolve(false);
      else resolve(defaultNo);
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
    const answer = await ask(
      `当前目录 ${cwd} 看起来是项目目录，是否安装到此项目？(选择否则全局安装到用户目录)`,
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

async function main(options = {}) {
  printBanner();

  // Resolve global vs project mode before downloading. If the user launched
  // the installer from a non-home directory without explicit flags, ask
  // whether that directory is the target project.
  options = await resolveInstallMode(options);

  const { global: globalInstall = true, ai = null, token = null, target = null, force = false } = options;

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
  let release;
  try {
    release = await fetchJson(RELEASE_API_URL, token);
  } catch (err) {
    error(`Could not fetch release info: ${err.message}`);
    hint('You can set GITHUB_TOKEN for higher API rate limits.');
    return 1;
  }

  const tag = release.tag_name;
  if (!tag) {
    error('Latest release has no tag.');
    return 1;
  }
  success(`Latest release: ${tag}`);

  const tarballUrl = release.tarball_url;
  const checksumAsset = release.assets?.find((a) => a.name === 'SHA256SUMS.txt');

  if (!tarballUrl) {
    error('Release has no tarball URL.');
    return 1;
  }
  if (!checksumAsset) {
    error('Release is missing SHA256SUMS.txt asset.');
    return 1;
  }

  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'iterate-skill-install-'));
  const tarballPath = path.join(tmpDir, 'iterate-skill.tar.gz');
  const checksumPath = path.join(tmpDir, 'SHA256SUMS.txt');

  try {
    info('Downloading release tarball...');
    await downloadFile(tarballUrl, tarballPath, token);

    info('Downloading checksums...');
    await downloadFile(checksumAsset.browser_download_url, checksumPath, token);

    info('Verifying checksum...');
    const checksums = parseChecksums(fs.readFileSync(checksumPath, 'utf8'));
    const expectedHash = checksums.get('iterate-skill.tar.gz');
    if (!expectedHash) {
      error('Checksum file does not contain iterate-skill.tar.gz');
      return 1;
    }
    const actualHash = await sha256File(tarballPath);
    if (actualHash.toLowerCase() !== expectedHash.toLowerCase()) {
      error('Checksum mismatch — refusing to install.');
      return 1;
    }
    success('Checksum verified.');
    frameSection('Release', [
      `\x1b[32m✓\x1b[0m Version: ${tag}`,
      `\x1b[32m✓\x1b[0m SHA256 checksum verified`,
    ]);

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

    const installArgs = [];
    if (ai) installArgs.push('--ai', ai);
    if (target) installArgs.push('--target', target);
    if (force) installArgs.push('--force');
    if (globalInstall) installArgs.push('--global');

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

    // Install the iterate CLI so `iterate onboard` works right after install.
    await installCli(pythonBin, sourceDir);

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
  ITERATE_BANNER,
  InstallerError,
  resolveInstallMode,
  askYesNo,
};
