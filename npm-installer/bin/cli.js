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
 *
 * The installer downloads the latest GitHub release, verifies its SHA256
 * checksum, then delegates file copying and assistant selection to the
 * Python install script bundled in the release.
 */

const { main } = require('../lib/installer');

function parseArgs(argv) {
  const options = {
    global: true,
    ai: null,
    target: null,
    force: false,
    token: process.env.GITHUB_TOKEN || null,
  };

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    const next = argv[i + 1];

    switch (arg) {
      case '--ai':
        if (!next) {
          console.error('Error: --ai requires a value');
          process.exit(1);
        }
        options.ai = next;
        i++;
        break;
      case '--target':
        if (!next) {
          console.error('Error: --target requires a value');
          process.exit(1);
        }
        options.target = next;
        options.global = false;
        i++;
        break;
      case '--global':
        options.global = true;
        options.target = null;
        break;
      case '--force':
        options.force = true;
        break;
      case '--token':
        if (!next) {
          console.error('Error: --token requires a value');
          process.exit(1);
        }
        options.token = next;
        i++;
        break;
      case '-h':
      case '--help':
        printHelp();
        process.exit(0);
        break;
      case '-v':
      case '--version':
        console.log(require('../package.json').version);
        process.exit(0);
        break;
      default:
        if (arg.startsWith('-')) {
          console.error(`Error: unknown option ${arg}`);
          process.exit(1);
        }
        break;
    }
  }

  return options;
}

function printHelp() {
  console.log(`
Usage: npx iterate-skill-installer [options]

Options:
  --ai <assistant>    Install only to the specified assistant (e.g. trae, claude, cursor).
  --target <path>     Install into a project directory instead of the global home dir.
  --global            Install into the user's home directory (default).
  --force             Overwrite existing skill files.
  --token <token>     GitHub token for higher API rate limits.
  -h, --help          Show this help message.
  -v, --version       Show version.

Examples:
  npx iterate-skill-installer
  npx iterate-skill-installer --ai trae
  npx iterate-skill-installer --target ./my-project
`);
}

async function run() {
  const options = parseArgs(process.argv.slice(2));
  try {
    const code = await main(options);
    process.exit(code);
  } catch (err) {
    console.error(`\nUnexpected error: ${err.message}`);
    process.exit(1);
  }
}

run();
