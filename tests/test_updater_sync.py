"""Cross-source consistency locks between ``iterate_cli/updater`` and ``scripts/install.py``.

``scripts/install.py`` is NOT part of the pip-installable ``iterate_cli``
wheel; the installer wheel omits ``scripts/``. But when installed as an
assistant skill directory, both files live together and MUST share the same
well-known lists. A drift here silently breaks either the installer or the
self-update flow. These tests parse the authoritative source
(``scripts/install.py``) with ``ast`` and lock the two copies together.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL_PY = ROOT / "scripts" / "install.py"
UPDATER_PY = ROOT / "iterate_cli" / "updater.py"


# ---------------------------------------------------------------------------
# AST / regex helpers (zero third-party dependencies)
# ---------------------------------------------------------------------------


def _extract_dict_literal(source: Path, var_name: str) -> dict[str, str]:
    """Parse a single-assigned ``VAR: dict[str,str] = {...}`` from *source*."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            matched = isinstance(target, ast.Name) and target.id == var_name
            if matched and isinstance(node.value, ast.Dict):
                keys = [
                    str(k.value) if isinstance(k, ast.Constant) else ""
                    for k in node.value.keys
                ]
                values = [
                    str(v.value) if isinstance(v, ast.Constant) else ""
                    for v in node.value.values
                ]
                if len(keys) == len(values):
                    return dict(zip(keys, values))
    raise AssertionError(f"{var_name!r} not found in {source.name}")


def _extract_list_literal(source: Path, var_name: str) -> list[str]:
    """Parse a single-assigned ``VAR: list[str] = [...]`` from *source*."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            matched = isinstance(target, ast.Name) and target.id == var_name
            if matched and isinstance(node.value, ast.List):
                return [
                    str(elt.value)
                    for elt in node.value.elts
                    if isinstance(elt, ast.Constant)
                ]
    raise AssertionError(f"{var_name!r} not found in {source.name}")


def _extract_dict_from_regex(source: Path, var_name: str) -> dict[str, str]:
    """Fallback regex extractor for the same variable pattern."""
    text = source.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^{var_name}\s*[=:][^{{]*\{{([^}}]*)\}}",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        raise AssertionError(f"{var_name!r} not found via regex in {source.name}")
    body = match.group(1)
    pairs: dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        raw_key, raw_value = line.split(":", 1)
        key = raw_key.strip().strip('"').strip("'")
        value = raw_value.strip().strip('"').strip("'")
        if key and value:
            pairs[key] = value
    return pairs


def _extract_list_from_regex(source: Path, var_name: str) -> list[str]:
    """Fallback regex extractor for the same variable pattern."""
    text = source.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^{var_name}\s*[=:][^[]*\[(.*?)\]",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        raise AssertionError(f"{var_name!r} not found via regex in {source.name}")
    body = match.group(1)
    items: list[str] = []
    for line in body.splitlines():
        for stripped in [line.strip().strip(","), ]:
            if stripped.startswith(("'", '"')) and stripped.endswith(("'", '"')):
                items.append(stripped.strip("'\""))
    return items


def _safely_parse_dict(source: Path, var_name: str) -> dict[str, str]:
    try:
        return _extract_dict_literal(source, var_name)
    except AssertionError:
        return _extract_dict_from_regex(source, var_name)


def _safely_parse_list(source: Path, var_name: str) -> list[str]:
    try:
        return _extract_list_literal(source, var_name)
    except AssertionError:
        return _extract_list_from_regex(source, var_name)


# ---------------------------------------------------------------------------
# Locks: updater ↔ install.py maps + file lists
# ---------------------------------------------------------------------------


class TestUpdaterInstallPySync:
    """Two-source lock: updater's public maps must match install.py exactly."""

    def test_assistant_skill_dirs_match_supported_ai(self) -> None:
        install_map = _safely_parse_dict(INSTALL_PY, "SUPPORTED_AI")
        from iterate_cli.updater import ASSISTANT_SKILL_DIRS

        assert ASSISTANT_SKILL_DIRS == install_map

    def test_required_paths_match_required_files(self) -> None:
        install_list = _safely_parse_list(INSTALL_PY, "REQUIRED_FILES")
        from iterate_cli.updater import REQUIRED_RELEASE_PATHS

        assert REQUIRED_RELEASE_PATHS == install_list

    def test_optional_paths_match_optional_files(self) -> None:
        install_list = _safely_parse_list(INSTALL_PY, "OPTIONAL_FILES")
        from iterate_cli.updater import OPTIONAL_RELEASE_PATHS

        assert OPTIONAL_RELEASE_PATHS == install_list
