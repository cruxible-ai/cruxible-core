"""Tests for the shared constraint rule parser."""

from cruxible_core.config.constraint_rules import parse_constraint_rule


class TestParseConstraintRule:
    def test_valid_rule(self):
        result = parse_constraint_rule("replaces.FROM.category == replaces.TO.category")
        assert result == ("replaces", "category", "category")

    def test_valid_rule_different_props(self):
        result = parse_constraint_rule(
            "classified_as.FROM.Category == classified_as.TO.CategoryName"
        )
        assert result == ("classified_as", "Category", "CategoryName")

    def test_valid_rule_with_spaces(self):
        result = parse_constraint_rule("fits.FROM.make  ==  fits.TO.make")
        assert result == ("fits", "make", "make")

    def test_invalid_garbage(self):
        assert parse_constraint_rule("not a valid rule") is None

    def test_invalid_empty_string(self):
        assert parse_constraint_rule("") is None

    def test_invalid_partial_match(self):
        assert parse_constraint_rule("fits.FROM.make") is None

    def test_invalid_mismatched_relationship(self):
        # Backreference requires same relationship on both sides
        assert parse_constraint_rule("fits.FROM.make == replaces.TO.make") is None

    def test_hyphens_in_identifiers(self):
        result = parse_constraint_rule(
            "classified-as.FROM.sub-category == classified-as.TO.sub-category"
        )
        assert result == ("classified-as", "sub-category", "sub-category")

    def test_underscores_in_identifiers(self):
        result = parse_constraint_rule("has_part.FROM.part_type == has_part.TO.part_type")
        assert result == ("has_part", "part_type", "part_type")

    def test_digits_in_identifiers(self):
        result = parse_constraint_rule("rel1.FROM.prop2 == rel1.TO.prop3")
        assert result == ("rel1", "prop2", "prop3")
