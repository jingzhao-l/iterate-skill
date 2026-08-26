"""Project scanner for onboarding.

Detects tech stack, directory structure, and key project features
to populate onboarding suggestions and the ITERATE.md knowledge base.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

# Mapping from manifest file name to (language, package_manager).
MANIFEST_TO_LANG: dict[str, tuple[str, str]] = {
    "package.json": ("JavaScript/TypeScript", "npm"),
    "pyproject.toml": ("Python", "pip/poetry"),
    "setup.py": ("Python", "pip"),
    "requirements.txt": ("Python", "pip"),
    "Package.swift": ("Swift", "SwiftPM"),
    "go.mod": ("Go", "Go modules"),
    "Cargo.toml": ("Rust", "cargo"),
    "pom.xml": ("Java", "Maven"),
    "build.gradle": ("Java/Kotlin", "Gradle"),
    "build.gradle.kts": ("Kotlin", "Gradle"),
    "Gemfile": ("Ruby", "bundler"),
    "composer.json": ("PHP", "composer"),
    "mix.exs": ("Elixir", "mix"),
    "pubspec.yaml": ("Dart/Flutter", "pub"),
    "tsconfig.json": ("TypeScript", "npm"),
}

# Directories that indicate a frontend UI layer.
FRONTEND_DIR_INDICATORS: tuple[str, ...] = (
    "src/pages", "src/components", "src/views",
    "app/pages", "app/components",
    "components", "views", "pages",
)

# Directories to skip when building the top-level directory listing.
SKIP_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", "venv", ".venv", "env", ".tox",
    "dist", "build", ".next", ".nuxt", "target",
    "coverage", "htmlcov", ".idea", ".vscode",
    "Pods", "DerivedData", ".build", ".cache",
})

# Spec directory candidates (checked relative to project root).
SPEC_DIR_CANDIDATES: tuple[str, ...] = ("specs", "spec", "docs/specs", "docs/spec")

# Test directory candidates.
TEST_DIR_CANDIDATES: tuple[str, ...] = ("tests", "test", "__tests__", "spec")

# CI config paths to check.
CI_PATHS: tuple[str, ...] = (
    ".github/workflows",
    ".gitlab-ci.yml",
    "Jenkinsfile",
    ".circleci",
    "azure-pipelines.yml",
)

# Directory names that indicate an API layer (used by suggest_dimensions).
API_LAYER_INDICATORS: frozenset[str] = frozenset({
    "api", "routes", "controllers", "handlers", "endpoints", "server",
})


@dataclass
class ScanResult:
    """Result of scanning a project directory for onboarding."""

    manifests: list[str] = field(default_factory=list)
    top_level_dirs: list[str] = field(default_factory=list)
    detected_languages: list[str] = field(default_factory=list)
    detected_package_managers: list[str] = field(default_factory=list)
    has_specs: bool = False
    has_tests: bool = False
    has_ci: bool = False
    has_frontend: bool = False


def scan_project(project_root: Path) -> ScanResult:
    """Scan a project directory and return structured findings.

    This is a read-only operation. It never reads file contents — only
    checks existence and lists directories. It is safe to run on any project.

    Args:
        project_root: The project root directory to scan.

    Returns:
        ScanResult with detected manifests, languages, directories, and features.
    """
    result = ScanResult()

    _scan_manifests(project_root, result)
    _scan_top_level_dirs(project_root, result)
    _scan_features(project_root, result)

    return result


def _scan_manifests(project_root: Path, result: ScanResult) -> None:
    """Detect manifest files and derive languages / package managers."""
    from iterate_cli.fingerprint import MANIFEST_FILES

    for name in MANIFEST_FILES:
        if (project_root / name).is_file():
            result.manifests.append(name)
            mapping = MANIFEST_TO_LANG.get(name)
            if mapping is not None:
                lang, pm = mapping
                if lang not in result.detected_languages:
                    result.detected_languages.append(lang)
                if pm not in result.detected_package_managers:
                    result.detected_package_managers.append(pm)


def _scan_top_level_dirs(project_root: Path, result: ScanResult) -> None:
    """List top-level directories, skipping common non-source dirs."""
    try:
        for entry in sorted(project_root.iterdir(), key=lambda e: e.name):
            if entry.is_dir() and entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                result.top_level_dirs.append(entry.name)
    except OSError as exc:
        # 目录列表失败（如权限不足、目录在扫描过程中被删除、挂载点出错）
        # 不阻断扫描，但记录到 stderr 以便排查。
        print(f"scan: warning: cannot list directories in {project_root}: {exc}", file=sys.stderr)


def _scan_features(project_root: Path, result: ScanResult) -> None:
    """Detect specs, tests, CI, context files, and frontend indicators."""
    for candidate in SPEC_DIR_CANDIDATES:
        if (project_root / candidate).is_dir():
            result.has_specs = True
            break

    for candidate in TEST_DIR_CANDIDATES:
        if (project_root / candidate).is_dir():
            result.has_tests = True
            break

    for ci_path in CI_PATHS:
        if (project_root / ci_path).exists():
            result.has_ci = True
            break

    for indicator in FRONTEND_DIR_INDICATORS:
        if (project_root / indicator).is_dir():
            result.has_frontend = True
            break


def suggest_dimensions(scan: ScanResult) -> list[str]:
    """Suggest review dimensions based on scan results.

    Returns a list of dimension keys suitable for iterate.config.yaml.
    The caller should let the user confirm or adjust the selection.

    Args:
        scan: The ScanResult from scan_project().

    Returns:
        List of recommended dimension keys.
    """
    # Base dimensions always recommended.
    dims: list[str] = [
        "correctness",
        "security",
        "performance",
        "architecture",
        "style-tests",
        "tech-debt",
    ]

    if scan.has_specs:
        dims.append("spec-compliance")
    if scan.has_frontend:
        dims.append("frontend-backend")
        dims.append("ui-ux")
    elif _has_api_layer(scan):
        dims.append("frontend-backend")

    return dims


def _has_api_layer(scan: ScanResult) -> bool:
    """Heuristic: check if the project likely has an API layer.

    Looks for common API-related directory names in the top-level listing.
    """
    return any(d in API_LAYER_INDICATORS for d in scan.top_level_dirs)


def suggest_validation_commands(scan: ScanResult) -> dict[str, list[str]]:
    """Suggest validation commands based on detected languages.

    Returns a dict mapping module keys to command lists, mirroring the
    ``validation.commands`` structure in iterate.config.yaml.
    These are starting points — the user must confirm they match the project.

    Args:
        scan: The ScanResult from scan_project().

    Returns:
        Dict of module → list of command strings.
    """
    commands: dict[str, list[str]] = {}

    # Java tooling spans up to three detected-language entries ("Java",
    # "Java/Kotlin", "Kotlin") that all map to the same "java" module; process
    # it once so a project with both pom.xml and build.gradle(.kts) does not
    # execute the branch twice and overwrite the build-tool choice.
    java_handled = False
    for lang in scan.detected_languages:
        if lang == "Python":
            commands["python"] = [
                "ruff check src/",
                "mypy src/ --ignore-missing-imports",
                "pytest tests/ -x -q --timeout=60",
            ]
        elif lang in ("JavaScript/TypeScript", "TypeScript"):
            commands["typescript"] = [
                "npm run lint",
                "npm run build",
                "npm test",
            ]
        elif lang == "Swift":
            commands["swift"] = ["swift build -c debug"]
        elif lang == "Go":
            commands["go"] = ["go vet ./...", "go test ./..."]
        elif lang == "Rust":
            commands["rust"] = ["cargo clippy", "cargo test"]
        elif lang in ("Java", "Java/Kotlin", "Kotlin"):
            if java_handled:
                continue
            java_handled = True
            # Prefer Maven when pom.xml exists; otherwise Gradle (from either
            # build.gradle or build.gradle.kts). Decided once, so a project
            # with both manifests never has the Gradle suggestion overwritten
            # by the Maven one (or vice-versa).
            build_tool = "mvn" if "pom.xml" in scan.manifests else "gradle"
            commands["java"] = [f"{build_tool} compile", f"{build_tool} test"]
        elif lang == "Dart/Flutter":
            commands["dart"] = ["dart analyze", "dart test"]
        elif lang == "Elixir":
            commands["elixir"] = ["mix test", "mix format --check-formatted"]
        elif lang == "Ruby":
            commands["ruby"] = ["bundle exec rubocop", "bundle exec rspec"]

    return commands


def suggest_command_whitelist(scan: ScanResult) -> list[str]:
    """Suggest a command whitelist based on detected languages.

    Args:
        scan: The ScanResult from scan_project().

    Returns:
        List of command prefix strings.
    """
    base: list[str] = ["python", "python3"]
    for lang in scan.detected_languages:
        if lang == "Python":
            base.extend(["ruff", "mypy", "pytest"])
        elif lang in ("JavaScript/TypeScript", "TypeScript"):
            # ``npm test`` is not a prefix of ``npm run``; include the bare
            # ``npm`` prefix so both ``npm run X`` and ``npm test`` match.
            base.extend(["npm", "npm run", "yarn", "pnpm", "npx"])
        elif lang == "Swift":
            base.append("swift")
        elif lang == "Go":
            # "go" (not "go test") so `go vet ./...` is covered as well:
            # _command_is_whitelisted only matches prefix + space, so the
            # narrower "go test" would leave "go vet ./..." un-whitelisted
            # and doctor would flag it.
            base.append("go")
        elif lang == "Rust":
            base.append("cargo")
        elif lang in ("Java", "Java/Kotlin", "Kotlin"):
            base.extend(["mvn", "gradle"])
        elif lang == "Dart/Flutter":
            base.append("dart")
        elif lang == "Elixir":
            base.append("mix")
        elif lang == "Ruby":
            base.append("bundle")
    # Deduplicate while preserving order.
    seen: set[str] = set()
    result: list[str] = []
    for item in base:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
