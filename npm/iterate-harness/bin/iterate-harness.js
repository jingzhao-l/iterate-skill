#!/usr/bin/env node
/* `iterate-harness` — long-form entry point of the npm wrapper (same as `ih`). */

"use strict";

const { BootstrapError, runHarness } = require("../lib/bootstrap");

try {
  runHarness(process.argv.slice(2));
} catch (error) {
  const message = error instanceof BootstrapError ? error.message : (error && error.stack) || error;
  process.stderr.write(`[iterate-harness] ${message}\n`);
  process.exit(1);
}
