"""Six-source dimension-system consistency lock (skill ↔ harness).

The iterate dimension ids are defined in SIX places across the two
repositories. Any of them can drift during a rename/add/remove. This
test locks them together so a change in one source fails CI until every
other source is updated:

1. ``config/dimensions.yaml``            — canonical definitions (skill)
2. ``config/config.schema.json``         — ``$defs.dimension.enum``
3. ``iterate_cli/wizard.py``             — ``ALL_DIMENSIONS`` + ``DIMENSION_LABELS``
4. ``harness/.../personalize_cmd.py``    — ``ALL_DIMENSIONS`` + ``DIMENSION_LABELS``
5. ``harness/.../types.py``              — ``IterateConfig`` default dimensions
6. ``harness/.../data/dimensions.yaml``  — bundled copy (byte-identical)

Extraction uses ast/json/regex only — zero third-party dependencies.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CANONICAL_YAML = ROOT / "config" / "dimensions.yaml"
SCHEMA_JSON = ROOT / "config" / "config.schema.json"
WIZARD_PY = ROOT / "iterate_cli" / "wizard.py"

HARNESS_ITERATE = ROOT / "harness" / "iterate-harness" / "src" / "iterate_harness" / "iterate"
HARNESS_PERSONALIZE = HARNESS_ITERATE / "personalize_cmd.py"
HARNESS_TYPES = HARNESS_ITERATE / "types.py"
HARNESS_INIT_WIZARD = HARNESS_ITERATE / "init_wizard.py"
HARNESS_BUNDLED_YAML = HARNESS_ITERATE / "data" / "dimensions.yaml"

#: Top-level mapping keys in a dimensions.yaml (unindented, no inline value).
_TOP_LEVEL_KEY = re.compile(r"^([A-Za-z0-9_-]+):\s*$", re.MULTILINE)


def yaml_dimension_keys(text: str) -> list[str]:
    """Dimension ids as declared at the top level of a dimensions.yaml."""
    return _TOP_LEVEL_KEY.findall(text)


def _module_assignments(tree: ast.Module):
    """Yield ``(target_name, value)`` for plain and annotated module-level assigns."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    yield target.id, node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            yield node.target.id, node.value


def extract_assigned_list(source: str, name: str) -> list[str]:
    """Extract one module-level ``NAME = ["a", "b", ...]`` via AST.

    Raises AssertionError when the assignment is missing or not a plain
    list of string literals — the lock must never silently pass because
    it failed to find a source.
    """
    for target, value in _module_assignments(ast.parse(source)):
        if target != name:
            continue
        assert isinstance(value, (ast.List, ast.Tuple)), f"{name} must be a list literal"
        return [
            elt.value
            for elt in value.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        ]
    raise AssertionError(f"module-level assignment {name!r} not found")


def extract_assigned_dict_keys(source: str, name: str) -> set[str]:
    """Extract the string keys of a module-level ``NAME = {...}`` via AST."""
    for target, value in _module_assignments(ast.parse(source)):
        if target != name:
            continue
        assert isinstance(value, ast.Dict), f"{name} must be a dict literal"
        return {
            key.value
            for key in value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
    raise AssertionError(f"module-level assignment {name!r} not found")


def extract_assigned_dict(source: str, name: str) -> dict[str, str]:
    """Extract one module-level ``NAME = {"k": "v", ...}`` via AST.

    Values are kept as their literal string form. Raises AssertionError when
    the assignment is missing or not a plain dict of string literals so the
    lock never silently passes because it failed to find a source.
    """
    for target, value in _module_assignments(ast.parse(source)):
        if target != name:
            continue
        assert isinstance(value, ast.Dict), f"{name} must be a dict literal"
        result: dict[str, str] = {}
        for key, val in zip(value.keys, value.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    result[key.value] = val.value
                else:
                    result[key.value] = "<non-literal>"
        return result
    raise AssertionError(f"module-level assignment {name!r} not found")


def yaml_dimension_priorities(text: str) -> dict[str, str]:
    """Dimension id -> priority as declared in a dimensions.yaml.

    Splits the document into top-level blocks (``NAME:`` at column 0) and
    reads the ``priority:`` key inside each block, so a block's priority is
    never confused with another block's.
    """
    # Split into (name, body) by top-level keys at column 0.
    blocks: list[tuple[str, str]] = []
    current_name: str | None = None
    current_body: list[str] = []
    for raw in text.splitlines():
        if raw and not raw[0].isspace():
            if current_name is not None:
                blocks.append((current_name, "\n".join(current_body)))
            current_name = raw.split(":", 1)[0].strip()
            current_body = []
        else:
            current_body.append(raw)
    if current_name is not None:
        blocks.append((current_name, "\n".join(current_body)))

    result: dict[str, str] = {}
    for name, body in blocks:
        if name.startswith("#"):
            continue
        match = re.search(r"^\s*priority:\s*(\S+)\s*$", body, re.MULTILINE)
        if match:
            result[name] = match.group(1)
    return result


def extract_class_field_lambda_list(source: str, class_name: str, field_name: str) -> list[str]:
    """Extract ``field`` default_factory lambda list (types.py defaults)."""
    for node in ast.parse(source).body:
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        for stmt in ast.walk(node):
            if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                continue
            if stmt.target.id != field_name:
                continue
            call = stmt.value
            assert isinstance(call, ast.Call), f"{class_name}.{field_name} must call field()"
            for keyword in call.keywords:
                if keyword.arg != "default_factory":
                    continue
                lam = keyword.value
                assert isinstance(lam, ast.Lambda), "default_factory must be a lambda"
                assert isinstance(lam.body, ast.List), "lambda body must be a list literal"
                return [
                    elt.value
                    for elt in lam.body.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                ]
    raise AssertionError(f"{class_name}.{field_name} default list not found")


def canonical_keys() -> list[str]:
    return yaml_dimension_keys(CANONICAL_YAML.read_text(encoding="utf-8"))


# ---- source 1: canonical yaml ---------------------------------------------


def test_canonical_yaml_declares_nine_dimensions():
    keys = canonical_keys()
    assert keys == [
        "correctness",
        "security",
        "performance",
        "architecture",
        "style-tests",
        "tech-debt",
        "spec-compliance",
        "frontend-backend",
        "ui-ux",
    ]


# ---- source 2: JSON-schema enum -------------------------------------------


def test_schema_enum_matches_canonical():
    schema = json.loads(SCHEMA_JSON.read_text(encoding="utf-8"))
    enum = schema["$defs"]["dimension"]["enum"]
    assert enum == canonical_keys(), "config.schema.json $defs.dimension.enum drifted"


# ---- source 3: skill wizard ------------------------------------------------


def test_wizard_all_dimensions_matches_canonical_order():
    source = WIZARD_PY.read_text(encoding="utf-8")
    assert extract_assigned_list(source, "ALL_DIMENSIONS") == canonical_keys()


def test_wizard_dimension_labels_cover_canonical():
    source = WIZARD_PY.read_text(encoding="utf-8")
    assert extract_assigned_dict_keys(source, "DIMENSION_LABELS") == set(canonical_keys())


# ---- source 4: harness personalize constants -------------------------------


def test_harness_all_dimensions_matches_canonical_order():
    source = HARNESS_PERSONALIZE.read_text(encoding="utf-8")
    assert extract_assigned_list(source, "ALL_DIMENSIONS") == canonical_keys()


def test_harness_dimension_labels_cover_canonical():
    source = HARNESS_PERSONALIZE.read_text(encoding="utf-8")
    assert extract_assigned_dict_keys(source, "DIMENSION_LABELS") == set(canonical_keys())


# ---- source 5: harness default config --------------------------------------


def test_harness_default_dimensions_match_canonical():
    source = HARNESS_TYPES.read_text(encoding="utf-8")
    defaults = extract_class_field_lambda_list(source, "IterateConfig", "dimensions")
    assert sorted(defaults) == sorted(canonical_keys())


def test_harness_base_dimensions_are_subset():
    source = HARNESS_INIT_WIZARD.read_text(encoding="utf-8")
    base = extract_assigned_list(source, "BASE_DIMENSIONS")
    assert set(base) <= set(canonical_keys())


# ---- source 7: generator priority_map vs canonical yaml priorities -------


GENERATOR_PY = ROOT / "iterate_cli" / "generator.py"


def test_generator_priority_map_matches_canonical_priorities():
    """The ``priority_map`` hardcoded in generator.py must mirror the
    priorities declared in config/dimensions.yaml.

    generator.py deliberately avoids a runtime dependency on the yaml files,
    so the map is duplicated by design — this test locks it so a priority
    change in the canonical yaml fails CI until the map is updated.
    """
    generator_src = GENERATOR_PY.read_text(encoding="utf-8")
    priorities = yaml_dimension_priorities(CANONICAL_YAML.read_text(encoding="utf-8"))
    assert set(priorities) == set(canonical_keys())

    # Extract the function-local priority_map literal via AST: find
    # _render_dimensions and pull .values[?] where the dict is assigned.
    tree = ast.parse(generator_src)
    fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_render_dimensions"
        ),
        None,
    )
    assert fn is not None, "_render_dimensions not found in generator.py"

    # Walk the function body for the ``priority_map = {...}`` assignment.
    priority_map: dict[str, str] | None = None
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)):
            continue
        if node.targets[0].id != "priority_map":
            continue
        value = node.value
        assert isinstance(value, ast.Dict), "priority_map must be a dict literal"
        priority_map = {}
        for key, val in zip(value.keys, value.values):
            if isinstance(key, ast.Constant) and isinstance(val, ast.Constant):
                priority_map[key.value] = val.value
        break
    assert priority_map is not None, "priority_map assignment not found in _render_dimensions"

    assert priority_map == priorities, (
        "generator.py priority_map drifted from config/dimensions.yaml priorities"
    )


# ---- source 6: bundled yaml ------------------------------------------------


def test_harness_bundled_yaml_byte_identical_to_skill():
    skill_bytes = CANONICAL_YAML.read_bytes()
    harness_bytes = HARNESS_BUNDLED_YAML.read_bytes()
    assert harness_bytes == skill_bytes, (
        "harness data/dimensions.yaml must stay byte-identical to skill "
        "config/dimensions.yaml — copy the file after editing the skill one"
    )
