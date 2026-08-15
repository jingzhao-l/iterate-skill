/*
 * Node-side bootstrap for the iterate-harness npm distribution wrapper.
 *
 * The harness itself is a Python package (the `ih` CLI). This module never
 * re-implements harness logic — it only prepares a managed virtualenv and
 * delegates every invocation to the real `ih` executable inside it:
 *
 * 1. Resolve a Python interpreter >= 3.10 (env override first).
 * 2. Create/reuse the venv at ~/.iterate-harness-npm/venv.
 * 3. pip-install the harness release tarball pinned to THIS npm package's
 *    version (lockstep: npm 1.6.0 installs harness v1.6.0).
 * 4. Stamp the installed version; a mismatch (npm upgrade) triggers a
 *    re-install on the next run.
 * 5. Spawn the venv's `ih` with argv/stdio/signals forwarded and the exit
 *    code passed through.
 *
 * Failures print an actionable message and exit 1 — never a raw stack trace.
 */

"use strict";

const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

// ---------------------------------------------------------------------------
// Constants (no magic strings below — everything is named here)
// ---------------------------------------------------------------------------

const RUNTIME_DIR_NAME = ".iterate-harness-npm";
const VENV_DIR_NAME = "venv";
const STAMP_FILE_NAME = "version.stamp";

const PYTHON_ENV_VAR = "ITERATE_HARNESS_PYTHON";
const HOME_ENV_VAR = "ITERATE_HARNESS_NPM_HOME";
const INSTALL_URL_ENV_VAR = "ITERATE_HARNESS_INSTALL_URL";
const SKIP_INSTALL_ENV_VAR = "ITERATE_HARNESS_SKIP_INSTALL";

const HARNESS_REPO_ARCHIVE_URL = "https://github.com/jingzhao-l/iterate-harness/archive/refs/tags";

const MIN_PYTHON_MAJOR = 3;
const MIN_PYTHON_MINOR = 10;

const PYTHON_VERSION_PATTERN = /Python\s+(\d+)\.(\d+)\.(\d+)/;
const IS_WINDOWS = process.platform === "win32";

class BootstrapError extends Error {}

// ---------------------------------------------------------------------------
// Pure helpers (unit-tested in test/bootstrap.test.js)
// ---------------------------------------------------------------------------

function releaseTarballUrl(version) {
  return `${HARNESS_REPO_ARCHIVE_URL}/v${version}.tar.gz`;
}

function parsePythonVersion(output) {
  const match = PYTHON_VERSION_PATTERN.exec(String(output));
  if (!match) {
    return null;
  }
  return {
    major: Number.parseInt(match[1], 10),
    minor: Number.parseInt(match[2], 10),
    patch: Number.parseInt(match[3], 10),
  };
}

function isSupportedPython(version) {
  if (!version) {
    return false;
  }
  return (
    version.major > MIN_PYTHON_MAJOR ||
    (version.major === MIN_PYTHON_MAJOR && version.minor >= MIN_PYTHON_MINOR)
  );
}

function pythonCandidates(platform, env) {
  const override = env ? env[PYTHON_ENV_VAR] : undefined;
  const candidates = [];
  if (override) {
    candidates.push({ command: override, preArgs: [] });
  }
  if (platform === "win32") {
    candidates.push({ command: "py", preArgs: ["-3"] });
    candidates.push({ command: "python", preArgs: [] });
  } else {
    candidates.push({ command: "python3", preArgs: [] });
    candidates.push({ command: "python", preArgs: [] });
  }
  return candidates;
}

function venvExecutablePaths(venvDir, platform) {
  if (platform === "win32") {
    return {
      python: path.join(venvDir, "Scripts", "python.exe"),
      ih: path.join(venvDir, "Scripts", "ih.exe"),
    };
  }
  return {
    python: path.join(venvDir, "bin", "python"),
    ih: path.join(venvDir, "bin", "ih"),
  };
}

function needsBootstrap(stampContent, expectedVersion) {
  return String(stampContent || "").trim() !== String(expectedVersion || "").trim();
}

// ---------------------------------------------------------------------------
// Runtime resolution
// ---------------------------------------------------------------------------

function packageVersion() {
  const manifestPath = path.resolve(__dirname, "..", "package.json");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  return manifest.version;
}

function runtimeHomeDir(env) {
  const override = env ? env[HOME_ENV_VAR] : undefined;
  if (override) {
    return override;
  }
  return path.join(os.homedir(), RUNTIME_DIR_NAME);
}

function detectPython(env) {
  const errors = [];
  for (const candidate of pythonCandidates(process.platform, env || process.env)) {
    const probe = spawnSync(candidate.command, [...candidate.preArgs, "--version"], {
      encoding: "utf8",
      windowsHide: true,
    });
    if (probe.error) {
      errors.push(`${candidate.command}: not found`);
      continue;
    }
    const stdout = `${probe.stdout || ""}${probe.stderr || ""}`;
    const version = parsePythonVersion(stdout);
    if (!version) {
      errors.push(`${candidate.command}: unreadable version output`);
      continue;
    }
    if (!isSupportedPython(version)) {
      errors.push(
        `${candidate.command}: ${version.major}.${version.minor}.${version.patch} is older than 3.10`
      );
      continue;
    }
    return { ...candidate, version };
  }
  throw new BootstrapError(
    [
      "Python >= 3.10 not found (tried: " + errors.join("; ") + ").",
      "",
      "Install Python 3.10+ or point the wrapper at an existing interpreter:",
      `  ${PYTHON_ENV_VAR}=/path/to/python3.12 npx iterate-harness --version`,
    ].join("\n")
  );
}

// ---------------------------------------------------------------------------
// Bootstrap (venv + pip install of the pinned release tarball)
// ---------------------------------------------------------------------------

function runStep(command, args, options) {
  const result = spawnSync(command, args, {
    stdio: ["ignore", "inherit", "inherit"],
    windowsHide: true,
    ...options,
  });
  if (result.error) {
    throw new BootstrapError(`failed to run ${command}: ${result.error.message}`);
  }
  if (result.status !== 0) {
    throw new BootstrapError(`${command} ${args.join(" ")} exited with code ${result.status}`);
  }
}

function installUrl(version, env) {
  const override = env ? env[INSTALL_URL_ENV_VAR] : undefined;
  if (override) {
    return override;
  }
  return releaseTarballUrl(version);
}

function bootstrap(homeDir, version, env) {
  fs.mkdirSync(homeDir, { recursive: true });

  const venvDir = path.join(homeDir, VENV_DIR_NAME);
  const executable = venvExecutablePaths(venvDir, process.platform);
  const activateMarker = IS_WINDOWS
    ? path.join(venvDir, "Scripts", "activate")
    : path.join(venvDir, "bin", "activate");

  const interpreter = detectPython(env);
  const recreateVenv = fs.existsSync(venvDir) && !fs.existsSync(activateMarker);
  if (recreateVenv) {
    fs.rmSync(venvDir, { recursive: true, force: true });
  }
  if (!fs.existsSync(activateMarker)) {
    process.stderr.write(`[iterate-harness] creating virtualenv at ${venvDir} ...\n`);
    runStep(interpreter.command, [...interpreter.preArgs, "-m", "venv", venvDir]);
  }

  const url = installUrl(version, env);
  process.stderr.write(`[iterate-harness] pip installing iterate-harness ${version} ...\n`);
  runStep(executable.python, [
    "-m",
    "pip",
    "install",
    "--upgrade",
    "--force-reinstall",
    url,
  ]);

  const stampPath = path.join(homeDir, STAMP_FILE_NAME);
  fs.writeFileSync(stampPath, `${version}\n`, "utf8");
}

function ensureRuntime(env) {
  const environment = env || process.env;
  const version = packageVersion();
  const homeDir = runtimeHomeDir(environment);
  const venvDir = path.join(homeDir, VENV_DIR_NAME);
  const executable = venvExecutablePaths(venvDir, process.platform);
  const stampPath = path.join(homeDir, STAMP_FILE_NAME);

  const skipInstall = environment[SKIP_INSTALL_ENV_VAR] === "1";
  const stampContent = fs.existsSync(stampPath)
    ? fs.readFileSync(stampPath, "utf8")
    : "";

  if (!skipInstall && needsBootstrap(stampContent, version)) {
    bootstrap(homeDir, version, environment);
  }

  if (!fs.existsSync(executable.ih)) {
    throw new BootstrapError(
      [
        `ih is not installed yet at ${executable.ih}.`,
        skipInstall
          ? `Bootstrap was skipped (${SKIP_INSTALL_ENV_VAR}=1) — unset it and retry.`
          : "The installation may have failed; remove the runtime dir and retry:",
        `  rm -rf ${homeDir}`,
      ].join("\n")
    );
  }
  return executable.ih;
}

// ---------------------------------------------------------------------------
// Delegation to the real ih executable
// ---------------------------------------------------------------------------

function runHarness(args, env) {
  const target = ensureRuntime(env);
  const child = spawn(target, args, {
    stdio: "inherit",
    windowsHide: false,
    env: env || process.env,
  });

  const forwardSignal = (signal) => {
    if (!child.killed) {
      child.kill(signal);
    }
  };
  process.on("SIGINT", () => forwardSignal("SIGINT"));
  process.on("SIGTERM", () => forwardSignal("SIGTERM"));

  child.on("error", (error) => {
    process.stderr.write(`[iterate-harness] failed to launch ih: ${error.message}\n`);
    process.exit(1);
  });
  child.on("close", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code === null ? 1 : code);
  });
}

module.exports = {
  BootstrapError,
  MIN_PYTHON_MAJOR,
  MIN_PYTHON_MINOR,
  PYTHON_ENV_VAR,
  HOME_ENV_VAR,
  INSTALL_URL_ENV_VAR,
  SKIP_INSTALL_ENV_VAR,
  detectPython,
  ensureRuntime,
  installUrl,
  isSupportedPython,
  needsBootstrap,
  packageVersion,
  parsePythonVersion,
  pythonCandidates,
  releaseTarballUrl,
  runHarness,
  venvExecutablePaths,
};
