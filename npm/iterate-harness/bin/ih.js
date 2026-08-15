#!/usr/bin/env node
/* `ih` — global entry point of the iterate-harness npm wrapper. */

"use strict";

const { BootstrapError, runHarness } = require("../lib/bootstrap");

try {
  runHarness(process.argv.slice(2));
} catch (error) {
  const message = error instanceof BootstrapError ? error.message : (error && error.stack) || error;
  process.stderr.write(`[iterate-harness] ${message}\n`);
  process.exit(1);
}
