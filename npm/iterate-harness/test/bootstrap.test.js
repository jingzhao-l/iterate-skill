/* Unit tests for the pure helpers of lib/bootstrap.js (node --test). */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");

const {
  HOME_ENV_VAR,
  INSTALL_URL_ENV_VAR,
  PYTHON_ENV_VAR,
  installUrl,
  isSupportedPython,
  needsBootstrap,
  parsePythonVersion,
  pythonCandidates,
  releaseTarballUrl,
  venvExecutablePaths,
} = require("../lib/bootstrap");

test("parsePythonVersion extracts major/minor/patch from mixed output", () => {
  assert.deepEqual(parsePythonVersion("Python 3.12.4"), {
    major: 3,
    minor: 12,
    patch: 4,
  });
  assert.deepEqual(parsePythonVersion("py: some warning\nPython 3.10.0rc1\n"), {
    major: 3,
    minor: 10,
    patch: 0,
  });
});

test("parsePythonVersion returns null for non-python output", () => {
  assert.equal(parsePythonVersion("node v20.11.0"), null);
  assert.equal(parsePythonVersion(""), null);
  assert.equal(parsePythonVersion(undefined), null);
});

test("isSupportedPython enforces the 3.10 floor", () => {
  assert.equal(isSupportedPython({ major: 3, minor: 10, patch: 0 }), true);
  assert.equal(isSupportedPython({ major: 3, minor: 12, patch: 4 }), true);
  assert.equal(isSupportedPython({ major: 4, minor: 0, patch: 0 }), true);
  assert.equal(isSupportedPython({ major: 3, minor: 9, patch: 9 }), false);
  assert.equal(isSupportedPython(null), false);
});

test("pythonCandidates puts the env override first on every platform", () => {
  const env = { [PYTHON_ENV_VAR]: "/opt/python3.12/bin/python3" };
  for (const platform of ["win32", "linux", "darwin"]) {
    const candidates = pythonCandidates(platform, env);
    assert.equal(candidates[0].command, "/opt/python3.12/bin/python3");
    assert.deepEqual(candidates[0].preArgs, []);
  }
});

test("pythonCandidates uses py -3 first on windows, python3 first elsewhere", () => {
  const windows = pythonCandidates("win32", {});
  assert.equal(windows[0].command, "py");
  assert.deepEqual(windows[0].preArgs, ["-3"]);

  const linux = pythonCandidates("linux", {});
  assert.equal(linux[0].command, "python3");
  assert.deepEqual(linux[0].preArgs, []);
});

test("venvExecutablePaths resolves platform-specific venv layout", () => {
  const windows = venvExecutablePaths(path.join("home", "venv"), "win32");
  assert.equal(windows.python, path.join("home", "venv", "Scripts", "python.exe"));
  assert.equal(windows.ih, path.join("home", "venv", "Scripts", "ih.exe"));

  const posix = venvExecutablePaths(path.join("home", "venv"), "darwin");
  assert.equal(posix.python, path.join("home", "venv", "bin", "python"));
  assert.equal(posix.ih, path.join("home", "venv", "bin", "ih"));
});

test("releaseTarballUrl pins the tag matching the wrapper version", () => {
  assert.equal(
    releaseTarballUrl("1.6.0"),
    "https://github.com/jingzhao-l/iterate-harness/archive/refs/tags/v1.6.0.tar.gz"
  );
});

test("installUrl prefers the env override over the pinned tarball", () => {
  const override = "git+https://github.com/jingzhao-l/iterate-harness.git@main";
  assert.equal(installUrl("1.6.0", { [INSTALL_URL_ENV_VAR]: override }), override);
  assert.equal(
    installUrl("1.6.0", {}),
    "https://github.com/jingzhao-l/iterate-harness/archive/refs/tags/v1.6.0.tar.gz"
  );
});

test("needsBootstrap ignores surrounding whitespace and requires exact match", () => {
  assert.equal(needsBootstrap("1.6.0\n", "1.6.0"), false);
  assert.equal(needsBootstrap(" 1.6.0 ", "1.6.0"), false);
  assert.equal(needsBootstrap("1.5.0\n", "1.6.0"), true);
  assert.equal(needsBootstrap("", "1.6.0"), true);
  assert.equal(needsBootstrap(undefined, "1.6.0"), true);
});

test("HOME_ENV_VAR name is stable (documented in README)", () => {
  assert.equal(HOME_ENV_VAR, "ITERATE_HARNESS_NPM_HOME");
});
