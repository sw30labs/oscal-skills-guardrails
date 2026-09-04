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


def test_deepagents_permissions_include_delete_deny() -> None:
    """deepagents 0.7 maps delete→write; guardrails always append deny-write on /**."""
    pytest = __import__("pytest")
    pytest.importorskip("deepagents")

    policy = GuardrailPolicy(
        {
            "filesystem_permissions": [
                {"operations": ["write"], "paths": ["/skills/shared/**"], "mode": "deny"},
            ]
        }
    )
    perms = policy.deepagents_filesystem_permissions()
    assert len(perms) >= 2
    deny_star = [
        p
        for p in perms
        if getattr(p, "mode", None) == "deny"
        and "write" in list(getattr(p, "operations", []))
        and "/**" in list(getattr(p, "paths", []))
    ]
    assert deny_star, "expected auto-appended deny write on /**"


def test_deepagents_permissions_skip_delete_deny_when_explicit_allow() -> None:
    pytest = __import__("pytest")
    pytest.importorskip("deepagents")

    policy = GuardrailPolicy(
        {
            "filesystem_permissions": [
                {"operations": ["delete"], "paths": ["/tmp/**"], "mode": "allow"},
            ]
        }
    )
    perms = policy.deepagents_filesystem_permissions()
    deny_star = [
        p
        for p in perms
        if getattr(p, "mode", None) == "deny"
        and "write" in list(getattr(p, "operations", []))
        and "/**" in list(getattr(p, "paths", []))
    ]
    assert not deny_star


def test_deepagents_permissions_default_deny_even_without_yaml_rules() -> None:
    pytest = __import__("pytest")
    pytest.importorskip("deepagents")

    perms = GuardrailPolicy({}).deepagents_filesystem_permissions()
    assert len(perms) == 1
    assert perms[0].mode == "deny"
    assert perms[0].operations == ["write"]
    assert perms[0].paths == ["/**"]
