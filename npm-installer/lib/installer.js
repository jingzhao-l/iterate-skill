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
 */

const { spawn, execFile } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');

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
    const found = await commandExists(bin);
    if (found) return bin;
  }
  return null;
}

function commandExists(bin) {
  return new Promise((resolve) => {
    execFile(bin, ['--version'], (err) => {
      resolve(!err);
    });
  });
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
      ...options,
    });
    child.on('close', (code) => {
      if (code === 0) {
        resolve(code);
      } else {
        reject(new InstallerError(`Python install exited with code ${code}`));
      }
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
  const { global: globalInstall = true, ai = null, token = null, target = null, force = false } = options;

  printBanner();

  step('Checking environment');
  const pythonBin = await findPython();
  if (!pythonBin) {
    error('Python is required but was not found on PATH.');
    hint('Install Python 3.9+ and ensure "python3" or "python" is available.');
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
    await runPythonInstall(venvPython, installScript, installArgs, { cwd: sourceDir });
    success('iterate-skill installation finished.');
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
};
