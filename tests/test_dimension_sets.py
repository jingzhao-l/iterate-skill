"""Tests for iterate_cli.dimension_sets.

Covers the named review-dimension blueprint logic: key/spec normalization,
scan-based suggestion/pruning, and refresh-time merging. These are the
building blocks behind scope-specific dimension routing in Phase 0 of the
skill.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from iterate_cli.dimension_sets import (
    CANONICAL_DIMENSIONS,
    is_valid_set_name,
    merge_dimension_sets,
    normalize_dimension_sets,
    suggest_dimension_sets,
)
from iterate_cli.scan import ScanResult


def _frontend_api_scan() -> ScanResult:
    return ScanResult(
        top_level_dirs=["src", "api"],
        has_frontend=True,
    )


class TestIsValidSetName:
    def test_valid_names_accepted(self) -> None:
        for name in ("frontend", "api-layer", "data_export", "module.a", "A1_b.c-d"):
            assert is_valid_set_name(name) is True

    def test_invalid_names_rejected(self) -> None:
        for name in ("bad name", "sp ace", "semi;colon", "slash/path", "tick`", "", "💥"):
            assert is_valid_set_name(name) is False


class TestNormalizeDimensionSets:
    def test_none_or_non_dict_returns_empty(self) -> None:
        assert normalize_dimension_sets(None) == {}
        assert normalize_dimension_sets("not-a-dict") == {}
        assert normalize_dimension_sets([]) == {}

    def test_empty_dict_returns_empty(self) -> None:
        assert normalize_dimension_sets({}) == {}

    def test_valid_set_preserved(self) -> None:
        raw = {"frontend": {"dimensions": ["ui-ux", "correctness"]}}
        out = normalize_dimension_sets(raw)
        assert out == {"frontend": {"dimensions": ["ui-ux", "correctness"]}}

    def test_invalid_set_name_dropped(self) -> None:
        raw = {"bad name": {"dimensions": ["correctness"]}}
        assert normalize_dimension_sets(raw) == {}

    def test_invalid_spec_dropped(self) -> None:
        raw = {"frontend": "not-a-mapping"}
        assert normalize_dimension_sets(raw) == {}

    def test_unknown_dimensions_filtered(self) -> None:
        raw = {"x": {"dimensions": ["correctness", "not_real"]}}
        out = normalize_dimension_sets(raw)
        assert out == {"x": {"dimensions": ["correctness"]}}

    def test_empty_dimensions_dropped(self) -> None:
        raw = {"x": {"dimensions": []}}
        assert normalize_dimension_sets(raw) == {}

    def test_duplicate_dimensions_deduplicated(self) -> None:
        raw = {"x": {"dimensions": ["correctness", "security", "correctness"]}}
        out = normalize_dimension_sets(raw)
        assert out == {"x": {"dimensions": ["correctness", "security"]}}

    def test_focus_kept_only_for_in_set_dimensions(self) -> None:
        raw = {
            "x": {
                "dimensions": ["correctness", "security"],
                "focus": {
                    "correctness": "check null handling",
                    "performance": "stale override dropped",
                    "security": "  check auth  ",
                },
            }
        }
        out = normalize_dimension_sets(raw)
        assert out == {
            "x": {
                "dimensions": ["correctness", "security"],
                "focus": {"correctness": "check null handling", "security": "check auth"},
            }
        }

    def test_empty_focus_text_dropped(self) -> None:
        raw = {"x": {"dimensions": ["correctness"], "focus": {"correctness": "   "}}}
        out = normalize_dimension_sets(raw)
        assert out == {"x": {"dimensions": ["correctness"]}}


class TestSuggestDimensionSets:
    def test_pure_python_project_offers_cross_cutting_sets(self) -> None:
        scan = ScanResult(top_level_dirs=["src"])
        out = suggest_dimension_sets(scan)
        # Cross-cutting audits always present regardless of stack.
        assert "security" in out
        assert "performance" in out
        assert "style-tests" in out
        # No UI/API layer → both layer-specific sets omitted.
        assert "frontend" not in out
        assert "api" not in out

    def test_frontend_project_includes_frontend_set(self) -> None:
        scan = ScanResult(top_level_dirs=["src"], has_frontend=True)
        out = suggest_dimension_sets(scan)
        assert "frontend" in out
        assert out["frontend"]["dimensions"] == ["ui-ux", "frontend-backend", "performance", "correctness"]

    def test_api_project_includes_api_set(self) -> None:
        scan = ScanResult(top_level_dirs=["api"])
        out = suggest_dimension_sets(scan)
        assert "api" in out

    def test_all_suggested_sets_are_normalized(self) -> None:
        scan = _frontend_api_scan()
        out = suggest_dimension_sets(scan)
        for spec in out.values():
            assert isinstance(spec, dict)
            assert spec["dimensions"]
            for dim in spec["dimensions"]:
                assert dim in CANONICAL_DIMENSIONS


class TestMergeDimensionSets:
    def test_existing_wins_over_suggestion(self) -> None:
        existing = {"frontend": {"dimensions": ["correctness"]}}
        suggested = {"frontend": {"dimensions": ["ui-ux", "correctness"]}}
        out = merge_dimension_sets(existing, suggested)
        assert out == {"frontend": {"dimensions": ["correctness"]}}

    def test_new_suggestions_added(self) -> None:
        existing = {"security": {"dimensions": ["security"]}}
        suggested = {"security": {"dimensions": ["security"]}, "performance": {"dimensions": ["performance"]}}
        out = merge_dimension_sets(existing, suggested)
        assert "security" in out
        assert "performance" in out

    def test_does_not_mutate_inputs(self) -> None:
        existing: dict[str, Any] = {"a": {"dimensions": ["correctness"]}}
        suggested: dict[str, Any] = {"b": {"dimensions": ["security"]}}
        merge_dimension_sets(existing, suggested)
        assert existing == {"a": {"dimensions": ["correctness"]}}
        assert suggested == {"b": {"dimensions": ["security"]}}