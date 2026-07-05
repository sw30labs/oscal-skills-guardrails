from __future__ import annotations

import json
from pathlib import Path

from deepagent_skill_guardrails.oscal_results import OscalAssessmentSink, control_for_event


def test_control_mapping() -> None:
    assert control_for_event({"kind": "integrity_violation"}) == "sg-2"
    assert control_for_event({"kind": "skill_decision", "matched": ["scan.max_severity"]}) == "sg-1"
    assert control_for_event({"kind": "skill_decision", "matched": ["scan.min_score"]}) == "sg-1"
    assert control_for_event({"kind": "skill_decision", "matched": ["agent.allow_skills"]}) == "sg-3"
    assert (
        control_for_event({"kind": "skill_decision", "matched": ["skill.required_metadata"]})
        == "sg-7"
    )
    assert control_for_event({"kind": "tool_decision", "matched": ["tool.deny_tools"]}) == "sg-4"
    assert (
        control_for_event(
            {"kind": "skill_decision", "matched": ["scan.interrupt_at_severity"], "effect": "interrupt"}
        )
        == "sg-6"
    )
    assert (
        control_for_event(
            {"kind": "skill_decision", "matched": ["skill.effect"], "effect": "interrupt"}
        )
        == "sg-6"
    )


def test_sink_builds_valid_document(tmp_path: Path) -> None:
    sink = OscalAssessmentSink(profile_href="profile.json", run_id="run-1")
    sink(
        {
            "kind": "skill_decision",
            "agent_id": "coding-agent",
            "skill_id": "langgraph-docs",
            "effect": "allow",
            "reason": "skill allowed",
            "matched": ["skill.admission"],
            "obligations": [],
            "digest": "abc123",
            "scan_severity": "none",
            "scan_score": 100,
            "scan_grade": "A",
        }
    )
    sink(
        {
            "kind": "skill_decision",
            "agent_id": "coding-agent",
            "skill_id": "evil-skill",
            "effect": "deny",
            "reason": "scan severity critical exceeds medium",
            "matched": ["scan.max_severity"],
            "obligations": ["review_scan_report"],
        }
    )
    sink(
        {
            "kind": "tool_decision",
            "agent_id": "coding-agent",
            "tool": "execute",
            "effect": "deny",
            "reason": "tool 'execute' explicitly denied",
            "matched": ["tool.deny_tools"],
            "obligations": [],
        }
    )

    assert sink.counts == {"allow": 1, "deny": 2, "interrupt": 0}

    doc = sink.to_document()
    ar = doc["assessment-results"]
    assert ar["metadata"]["oscal-version"] == "1.1.2"
    assert ar["import-ap"]["href"] == "profile.json"
    result = ar["results"][0]
    assert len(result["observations"]) == 3
    assert len(result["findings"]) == 2  # denials only

    included = {
        c["control-id"]
        for c in result["reviewed-controls"]["control-selections"][0]["include-controls"]
    }
    assert {"sg-1", "sg-3", "sg-4"} == included

    finding_targets = {f["target"]["target-id"] for f in result["findings"]}
    assert finding_targets == {"sg-1_smt", "sg-4_smt"}
    for f in result["findings"]:
        assert f["target"]["status"]["state"] == "not-satisfied"
        assert f["related-observations"]

    out = sink.write(tmp_path / "ar.json")
    reparsed = json.loads(out.read_text())
    assert "assessment-results" in reparsed


def test_observation_props_carry_evidence() -> None:
    sink = OscalAssessmentSink()
    sink(
        {
            "kind": "integrity_violation",
            "agent_id": "runtime",
            "skill_id": "alpha",
            "effect": "deny",
            "reason": "digest changed",
            "matched": ["skill.digest_mismatch"],
            "expected_digest": "aaa",
            "actual_digest": "bbb",
        }
    )
    doc = sink.to_document()
    obs = doc["assessment-results"]["results"][0]["observations"][0]
    props = {p["name"]: p["value"] for p in obs["props"]}
    assert props["osg:control"] == "sg-2"
    assert props["osg:expected-digest"] == "aaa"
    assert props["osg:actual-digest"] == "bbb"
    finding = doc["assessment-results"]["results"][0]["findings"][0]
    assert finding["target"]["target-id"] == "sg-2_smt"
