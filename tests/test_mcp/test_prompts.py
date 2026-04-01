"""Tests for MCP prompt registrations."""

from __future__ import annotations

import asyncio

import pytest

from cruxible_core.mcp.server import create_server


@pytest.fixture
def server():
    return create_server()


class TestPromptRegistration:
    def test_prompts_registered(self, server):
        prompts = asyncio.run(server.list_prompts())
        names = {p.name for p in prompts}
        assert names == {
            "prepare_data",
            "onboard_domain",
            "review_graph",
            "common_workflows",
            "analyze_feedback",
            "analyze_outcomes",
            "user_review",
        }

    def test_onboard_domain_has_description(self, server):
        prompts = asyncio.run(server.list_prompts())
        by_name = {p.name: p for p in prompts}
        assert "raw data" in by_name["onboard_domain"].description.lower()

    def test_review_graph_has_description(self, server):
        prompts = asyncio.run(server.list_prompts())
        by_name = {p.name: p for p in prompts}
        assert "quality" in by_name["review_graph"].description.lower()


class TestOnboardDomain:
    def test_renders_with_domain(self, server):
        result = asyncio.run(
            server.get_prompt("onboard_domain", {"domain": "car parts compatibility"})
        )
        text = result.messages[0].content.text
        assert "car parts compatibility" in text

    def test_contains_workflow_steps(self, server):
        result = asyncio.run(server.get_prompt("onboard_domain", {"domain": "test domain"}))
        text = result.messages[0].content.text
        assert "Prepare Data" in text
        assert "Cross-Dataset Relationships" in text
        assert "prepare_data" in text
        assert "YAML Config" in text
        assert "Validate and Initialize" in text
        assert "Load Source Data" in text
        assert "Validate Graph Quality" in text
        assert "even if evaluate is clean" in text
        assert "Sample Queries" in text
        assert "Provide Feedback" in text
        assert "Your feedback compounds" in text

    def test_handoff_uses_user_facing_language(self, server):
        result = asyncio.run(server.get_prompt("onboard_domain", {"domain": "test domain"}))
        text = result.messages[0].content.text
        handoff_start = text.index("What You Can Do Next")
        handoff = text[handoff_start:]
        assert "cruxible_" not in handoff

    def test_contains_config_schema_reference(self, server):
        result = asyncio.run(server.get_prompt("onboard_domain", {"domain": "test domain"}))
        text = result.messages[0].content.text
        assert "entity_types" in text
        assert "relationships" in text
        assert "named_queries" in text
        assert "constraints" in text
        assert "ingestion" in text

    def test_contains_discovery_step(self, server):
        result = asyncio.run(server.get_prompt("onboard_domain", {"domain": "test domain"}))
        text = result.messages[0].content.text
        assert "Discover the Domain" in text
        assert "Locate data files" in text
        assert "Propose a domain model" in text
        assert "Wait for user confirmation" in text

    def test_contains_primary_key_example(self, server):
        result = asyncio.run(server.get_prompt("onboard_domain", {"domain": "test domain"}))
        text = result.messages[0].content.text
        assert "primary_key: true" in text


class TestReviewGraph:
    def test_renders_with_instance_id(self, server):
        result = asyncio.run(server.get_prompt("review_graph", {"instance_id": "/tmp/my-project"}))
        text = result.messages[0].content.text
        assert "/tmp/my-project" in text

    def test_contains_review_steps(self, server):
        result = asyncio.run(server.get_prompt("review_graph", {"instance_id": "inst-1"}))
        text = result.messages[0].content.text
        assert "Run Evaluation" in text
        assert "Orphan" in text
        assert "Coverage gaps" in text
        assert "Feedback" in text
        assert "cruxible_find_candidates" in text
        assert "Iterate" in text

    def test_discovery_playbook_behavioral_guardrails(self, server):
        result = asyncio.run(server.get_prompt("review_graph", {"instance_id": "inst-1"}))
        text = result.messages[0].content.text
        assert "Don't stop after one failure" in text
        assert ">100 or >10%" in text
        assert "cruxible_add_constraint" in text
        assert "plateaued" in text
        assert "cruxible_sample" in text
        assert "Intelligence pass" in text
        assert "custom scripts" in text

    def test_step2_autonomous_first_with_escalation(self, server):
        result = asyncio.run(server.get_prompt("review_graph", {"instance_id": "inst-1"}))
        text = result.messages[0].content.text
        assert 'source="ai_review"' in text
        assert 'source="human"' in text
        assert "correct" in text
        assert "escalate" in text.lower()
        assert "recurring pattern" in text.lower() or "ambiguous" in text.lower()
        assert "receipt_id" in text


class TestUserReview:
    def test_renders_with_instance_id(self, server):
        result = asyncio.run(server.get_prompt("user_review", {"instance_id": "inst-1"}))
        text = result.messages[0].content.text
        assert "inst-1" in text

    def test_contains_feedback_actions(self, server):
        result = asyncio.run(server.get_prompt("user_review", {"instance_id": "inst-1"}))
        text = result.messages[0].content.text
        assert "approve" in text
        assert "correct" in text
        assert "flag" in text
        assert "reject" in text
        assert 'source="human"' in text

    def test_uses_edge_listing(self, server):
        result = asyncio.run(server.get_prompt("user_review", {"instance_id": "inst-1"}))
        text = result.messages[0].content.text
        assert 'resource_type="edges"' in text

    def test_encourages_correct_over_reject(self, server):
        result = asyncio.run(server.get_prompt("user_review", {"instance_id": "inst-1"}))
        text = result.messages[0].content.text
        assert "corrections" in text


class TestPrepareData:
    def test_renders_with_description(self, server):
        result = asyncio.run(
            server.get_prompt(
                "prepare_data",
                {"data_description": "two CSV files with car parts"},
            )
        )
        text = result.messages[0].content.text
        assert "two CSV files with car parts" in text

    def test_renders_with_empty_description(self, server):
        result = asyncio.run(server.get_prompt("prepare_data", {"data_description": ""}))
        text = result.messages[0].content.text
        assert "Profile Each File" in text
        assert "readiness" in text

    def test_contains_checklist_steps(self, server):
        result = asyncio.run(server.get_prompt("prepare_data", {"data_description": "test"}))
        text = result.messages[0].content.text
        assert "Profile Each File" in text
        assert "Entity Primary Keys" in text
        assert "Relationship Foreign Keys" in text
        assert "Join Keys" in text
        assert "Junk Rows" in text
        assert "Cardinality" in text
        assert "Text Fields" in text
        assert "Against Config" in text
        assert "Report" in text

    def test_requires_structured_output(self, server):
        result = asyncio.run(server.get_prompt("prepare_data", {"data_description": "test"}))
        text = result.messages[0].content.text
        assert "readiness" in text
        assert "blocking_issues" in text
        assert "warnings" in text
        assert "cleaned_files" in text

    def test_states_cleaning_is_external(self, server):
        result = asyncio.run(server.get_prompt("prepare_data", {"data_description": "test"}))
        text = result.messages[0].content.text
        assert "cleaning and transforms are external" in text


class TestAnalyzeFeedback:
    def test_renders_with_parameters(self, server):
        result = asyncio.run(
            server.get_prompt(
                "analyze_feedback",
                {"instance_id": "/tmp/test", "relationship_type": "fits"},
            )
        )
        text = result.messages[0].content.text
        assert "/tmp/test" in text
        assert "fits" in text

    def test_contains_workflow_steps(self, server):
        result = asyncio.run(
            server.get_prompt(
                "analyze_feedback",
                {"instance_id": "inst-1", "relationship_type": "replaces"},
            )
        )
        text = result.messages[0].content.text
        assert "cruxible_get_feedback_profile" in text
        assert "cruxible_analyze_feedback" in text
        assert "cruxible_add_constraint" in text
        assert "cruxible_add_decision_policy" in text


class TestAnalyzeOutcomes:
    def test_renders_with_parameters(self, server):
        result = asyncio.run(
            server.get_prompt(
                "analyze_outcomes",
                {"instance_id": "/tmp/test", "anchor_type": "receipt"},
            )
        )
        text = result.messages[0].content.text
        assert "/tmp/test" in text
        assert "receipt" in text

    def test_contains_workflow_steps(self, server):
        result = asyncio.run(
            server.get_prompt(
                "analyze_outcomes",
                {"instance_id": "inst-1", "anchor_type": "resolution"},
            )
        )
        text = result.messages[0].content.text
        assert "cruxible_get_outcome_profile" in text
        assert "cruxible_analyze_outcomes" in text
        assert "cruxible_update_trust_status" in text
        assert "cruxible_add_decision_policy" in text
        assert "cruxible_evaluate" in text
