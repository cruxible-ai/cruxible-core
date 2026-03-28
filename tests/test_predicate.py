"""Tests for the shared predicate core."""

import pytest

from cruxible_core.predicate import (
    ComparisonOp,
    comparison_symbol,
    evaluate_comparison,
    normalize_comparison_op,
)


class TestNormalizeComparisonOp:
    def test_symbolic_operators(self) -> None:
        assert normalize_comparison_op("==") == "eq"
        assert normalize_comparison_op("!=") == "ne"
        assert normalize_comparison_op(">") == "gt"
        assert normalize_comparison_op(">=") == "gte"
        assert normalize_comparison_op("<") == "lt"
        assert normalize_comparison_op("<=") == "lte"

    def test_semantic_operators(self) -> None:
        assert normalize_comparison_op("eq") == "eq"
        assert normalize_comparison_op("ne") == "ne"
        assert normalize_comparison_op("gt") == "gt"
        assert normalize_comparison_op("gte") == "gte"
        assert normalize_comparison_op("lt") == "lt"
        assert normalize_comparison_op("lte") == "lte"

    def test_unsupported_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported comparison operator"):
            normalize_comparison_op("contains")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported comparison operator"):
            normalize_comparison_op("")


class TestComparisonSymbol:
    def test_roundtrip(self) -> None:
        assert comparison_symbol("eq") == "=="
        assert comparison_symbol("ne") == "!="
        assert comparison_symbol("gt") == ">"
        assert comparison_symbol("gte") == ">="
        assert comparison_symbol("lt") == "<"
        assert comparison_symbol("lte") == "<="

    def test_symbolic_input(self) -> None:
        assert comparison_symbol("==") == "=="
        assert comparison_symbol(">=") == ">="


class TestEvaluateComparison:
    # --- equality / inequality ---

    def test_eq_strings(self) -> None:
        assert evaluate_comparison("a", "eq", "a") is True
        assert evaluate_comparison("a", "eq", "b") is False

    def test_ne_strings(self) -> None:
        assert evaluate_comparison("a", "ne", "b") is True
        assert evaluate_comparison("a", "ne", "a") is False

    def test_eq_ints(self) -> None:
        assert evaluate_comparison(5, "eq", 5) is True
        assert evaluate_comparison(5, "eq", 6) is False

    def test_eq_symbolic(self) -> None:
        assert evaluate_comparison("x", "==", "x") is True
        assert evaluate_comparison("x", "!=", "x") is False

    # --- ordered comparisons ---

    def test_gt_ints(self) -> None:
        assert evaluate_comparison(5, "gt", 3) is True
        assert evaluate_comparison(3, "gt", 5) is False
        assert evaluate_comparison(5, "gt", 5) is False

    def test_gte_ints(self) -> None:
        assert evaluate_comparison(5, "gte", 5) is True
        assert evaluate_comparison(5, "gte", 6) is False

    def test_lt_ints(self) -> None:
        assert evaluate_comparison(3, "lt", 5) is True
        assert evaluate_comparison(5, "lt", 3) is False

    def test_lte_ints(self) -> None:
        assert evaluate_comparison(5, "lte", 5) is True
        assert evaluate_comparison(6, "lte", 5) is False

    def test_ordered_floats(self) -> None:
        assert evaluate_comparison(3.14, ">=", 3.14) is True
        assert evaluate_comparison(2.71, "<", 3.14) is True

    def test_ordered_strings(self) -> None:
        assert evaluate_comparison("apple", "<", "banana") is True
        assert evaluate_comparison("banana", ">", "apple") is True

    # --- incomparable types return False for ordered ops ---

    def test_incomparable_types_ordered(self) -> None:
        assert evaluate_comparison("text", "gt", 5) is False
        assert evaluate_comparison(5, "lt", "text") is False
        assert evaluate_comparison(None, "gte", 5) is False
        assert evaluate_comparison(5, "lte", None) is False

    # --- eq/ne with None ---

    def test_eq_with_none(self) -> None:
        assert evaluate_comparison(None, "eq", None) is True
        assert evaluate_comparison(None, "eq", "a") is False
        assert evaluate_comparison("a", "eq", None) is False

    def test_ne_with_none(self) -> None:
        assert evaluate_comparison(None, "ne", "a") is True
        assert evaluate_comparison("a", "ne", None) is True
        assert evaluate_comparison(None, "ne", None) is False

    # --- mixed numeric types ---

    def test_int_float_comparison(self) -> None:
        assert evaluate_comparison(5, "eq", 5.0) is True
        assert evaluate_comparison(5, "gte", 4.9) is True
        assert evaluate_comparison(5, "lt", 5.1) is True

    # --- unsupported operator ---

    def test_unsupported_op_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported comparison operator"):
            evaluate_comparison(1, "like", 1)
