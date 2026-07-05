from __future__ import annotations

import json
from pathlib import Path

from deepagent_skill_guardrails.models import (
    AgentContext,
    ScanFinding,
    ScanReport,
    SkillManifest,
    SkillRecord,
)
from deepagent_skill_guardrails.oscal_loader import compile_profile, load_skills_policy_profile

PROFILE_PATH = Path(__file__).parent.parent / "data" / "oscal-policies" / "skills-policy-profile.json"


def record(
    skill_id: str,
    severity: str = "none",
    *,
    raw: dict | None = None,
    metadata: dict | None = None,
) -> SkillRecord:
    findings = ()
    if severity != "none":
        findings = (
            ScanFinding(rule_id="X", severity=severity, category="test", message="test finding"),  # type: ignore[arg-type]
        )
    return SkillRecord(
        manifest=SkillManifest(
            name=skill_id,
            description="test skill",
            path=Path(f"/tmp/skills/{skill_id}"),
            metadata=metadata or {},
        ),
        digest="abc",
        scan=ScanReport(scanner="test", target=skill_id, findings=findings, raw=raw or {}),
    )


def test_profile_compiles_to_expected_sections() -> None:
    policy = load_skills_policy_profile(PROFILE_PATH)
    assert policy.raw["defaults"]["max_scan_severity"] == "medium"
    assert "mcp__dangerous__*" in policy.raw["defaults"]["deny_tools"]
    assert policy.raw["agents"]["coding-agent"]["min_grade"] == "B"
    assert policy.raw["subagents"]["researcher"]["allow_tools"] == [
        "web_search",
        "fetch_url",
        "read_file",
    ]
    assert policy.raw["skills"]["oscal-authoring"]["required_metadata"] == {"owner": "governance"}
    assert policy.raw["skills"]["oscal-authoring"]["min_score"] == 90
    assert len(policy.raw["filesystem_permissions"]) == 2
    assert policy.raw["filesystem_permissions"][0]["mode"] == "deny"
    assert policy.raw["_oscal"]["title"] == "Agent Skills Usage Policy Profile"


def test_wildcard_agent_and_severity_gate() -> None:
    policy = load_skills_policy_profile(PROFILE_PATH)
    ctx = AgentContext(agent_id="coding-agent")
    ok = record("langgraph-docs", "low", raw={"score": 95, "grade": "A"})
    assert policy.check_skill(ctx, ok).allowed
    bad = record("langgraph-docs", "critical", raw={"score": 10, "grade": "F"})
    decision = policy.check_skill(ctx, bad)
    assert decision.effect == "deny"
    assert "exceeds" in decision.reason


def test_min_grade_denies_and_fails_closed() -> None:
    policy = load_skills_policy_profile(PROFILE_PATH)
    ctx = AgentContext(agent_id="coding-agent")  # min_grade B
    low_grade = record("code-review", "low", raw={"score": 70, "grade": "C"})
    assert policy.check_skill(ctx, low_grade).effect == "deny"
    no_grade = record("code-review", "low", raw={"score": 70})
    decision = policy.check_skill(ctx, no_grade)
    assert decision.effect == "deny"
    assert "no grade" in decision.reason


def test_min_score_per_skill() -> None:
    policy = load_skills_policy_profile(PROFILE_PATH)
    ctx = AgentContext(agent_id="supervisor")
    ok = record(
        "oscal-authoring",
        "low",
        raw={"score": 95, "grade": "A"},
        metadata={"owner": "governance"},
    )
    # supervisor has interrupt_at_severity=medium; low severity passes to allow
    assert policy.check_skill(ctx, ok).allowed
    low_score = record(
        "oscal-authoring",
        "low",
        raw={"score": 80, "grade": "B"},
        metadata={"owner": "governance"},
    )
    decision = policy.check_skill(ctx, low_score)
    assert decision.effect == "deny"
    assert "below minimum" in decision.reason


def test_effect_override() -> None:
    policy_dict = compile_profile(
        {
            "profile": {
                "metadata": {"title": "t", "version": "0"},
                "modify": {
                    "controls": [
                        {
                            "control-id": "sg-agt-wildcard",
                            "props": [
                                {"name": "osg:target-type", "value": "agent"},
                                {"name": "osg:target-id", "value": "*"},
                                {"name": "osg:allow-skill", "value": "*"},
                            ],
                        },
                        {
                            "control-id": "sg-skl-banned",
                            "props": [
                                {"name": "osg:target-type", "value": "skill"},
                                {"name": "osg:target-id", "value": "banned"},
                                {"name": "osg:effect", "value": "deny"},
                                {"name": "osg:reason", "value": "known bad"},
                            ],
                        },
                        {
                            "control-id": "sg-skl-review-me",
                            "props": [
                                {"name": "osg:target-type", "value": "skill"},
                                {"name": "osg:target-id", "value": "review-me"},
                                {"name": "osg:effect", "value": "interrupt"},
                            ],
                        },
                    ]
                },
            }
        }
    )
    from deepagent_skill_guardrails.policy import GuardrailPolicy

    policy = GuardrailPolicy(policy_dict)
    ctx = AgentContext(agent_id="anything")
    denied = policy.check_skill(ctx, record("banned"))
    assert denied.effect == "deny"
    assert "known bad" in denied.reason
    assert policy.check_skill(ctx, record("review-me")).effect == "interrupt"
    # interrupt override must not bypass the severity gate
    assert policy.check_skill(ctx, record("review-me", "critical")).effect == "deny"


def test_strict_alters_shape_accepted() -> None:
    policy_dict = compile_profile(
        {
            "profile": {
                "metadata": {},
                "modify": {
                    "alters": [
                        {
                            "control-id": "sg-agt-ops",
                            "adds": [
                                {
                                    "props": [
                                        {"name": "osg:allow-skill", "value": "ops-*"},
                                        {"name": "osg:max-scan-severity", "value": "low"},
                                    ]
                                }
                            ],
                        }
                    ]
                },
            }
        }
    )
    assert policy_dict["agents"]["ops"]["allow_skills"] == ["ops-*"]
    assert policy_dict["agents"]["ops"]["max_scan_severity"] == "low"


def test_profile_json_is_valid_json() -> None:
    with PROFILE_PATH.open() as f:
        doc = json.load(f)
    assert doc["profile"]["imports"][0]["href"] == "skill-guardrails-catalog.json"
