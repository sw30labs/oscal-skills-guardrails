from __future__ import annotations

from pathlib import Path

from deepagent_skill_guardrails.models import AgentContext, ScanFinding, ScanReport, SkillManifest, SkillRecord
from deepagent_skill_guardrails.policy import GuardrailPolicy


def record(skill_id: str, severity: str = "none") -> SkillRecord:
    findings = ()
    if severity != "none":
        findings = (
            ScanFinding(
                rule_id="X",
                severity=severity,  # type: ignore[arg-type]
                category="test",
                message="test finding",
            ),
        )
    return SkillRecord(
        manifest=SkillManifest(
            name=skill_id,
            description="test skill",
            path=Path(f"/tmp/skills/{skill_id}"),
        ),
        digest="abc",
        scan=ScanReport(scanner="test", target=skill_id, findings=findings),
    )


def test_policy_allows_matching_skill_under_severity() -> None:
    policy = GuardrailPolicy(
        {
            "defaults": {"max_scan_severity": "medium"},
            "agents": {"coding-agent": {"allow_skills": ["langgraph-*"], "allow_tools": ["read_file"]}},
        }
    )
    ctx = AgentContext(agent_id="coding-agent")
    decision = policy.check_skill(ctx, record("langgraph-docs", "low"))
    assert decision.allowed


def test_policy_denies_non_matching_skill() -> None:
    policy = GuardrailPolicy({"agents": {"coding-agent": {"allow_skills": ["langgraph-*"]}}})
    ctx = AgentContext(agent_id="coding-agent")
    decision = policy.check_skill(ctx, record("oscal-authoring"))
    assert decision.effect == "deny"


def test_policy_denies_high_severity_skill() -> None:
    policy = GuardrailPolicy(
        {
            "defaults": {"max_scan_severity": "medium"},
            "agents": {"coding-agent": {"allow_skills": ["*"]}},
        }
    )
    ctx = AgentContext(agent_id="coding-agent")
    decision = policy.check_skill(ctx, record("testing", "critical"))
    assert decision.effect == "deny"
    assert "exceeds" in decision.reason


def test_policy_gates_tool_calls() -> None:
    policy = GuardrailPolicy(
        {"agents": {"coding-agent": {"allow_tools": ["read_file"], "deny_tools": ["execute"]}}}
    )
    ctx = AgentContext(agent_id="coding-agent")
    assert policy.check_tool_call(ctx, "read_file").allowed
    assert policy.check_tool_call(ctx, "execute").effect == "deny"
    assert policy.check_tool_call(ctx, "write_file").effect == "deny"
