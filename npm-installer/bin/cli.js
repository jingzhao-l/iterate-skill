#!/usr/bin/env node

/**
 * iterate-skill-installer CLI
 *
 * One-command installer for iterate-skill across AI coding assistants.
 *
 * Usage:
 *   npx iterate-skill-installer
 *   npx iterate-skill-installer --ai trae
 *   npx iterate-skill-installer --target /path/to/project
 *   npx iterate-skill-installer --global
 *   npx iterate-skill-installer --no-cli
 *
 * The installer downloads the latest GitHub release, verifies its SHA256
 * checksum, then delegates file copying and assistant selection to the
 * Python install script bundled in the release.
 */

const { main, parseArgs, VERSION } = require('../lib/installer');

function printHelp() {
  console.log(`
Usage: npx iterate-skill-installer [options]

Options:
  --ai <assistant>    Install only to the specified assistant (e.g. trae, claude, cursor).
  --target <path>     Install into a project directory instead of the global home dir.
  --global            Install into the user's home directory (default).
  --force             Overwrite existing skill files.
  --no-cli            Skip installing the iterate CLI (skill-only install).
  --token <token>     GitHub token for higher API rate limits.
  -h, --help          Show this help message.
  -v, --version       Show version.

Examples:
  npx iterate-skill-installer
  npx iterate-skill-installer --ai trae
  npx iterate-skill-installer --target ./my-project
  npx iterate-skill-installer --no-cli
`);
}

async function run() {
  const options = parseArgs(process.argv.slice(2));

  if (options.mode === 'help') {
    printHelp();
    process.exit(0);
  }

  if (options.mode === 'version') {
    console.log(`iterate-skill-installer ${VERSION}`);
    process.exit(0);
  }

  try {
    const code = await main(options);
    process.exit(code);
  } catch (err) {
    console.error(`\nUnexpected error: ${err.message}`);
    process.exit(1);
  }
}

run();
