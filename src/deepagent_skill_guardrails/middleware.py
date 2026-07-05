from __future__ import annotations

import json
from typing import Any, Callable

from .models import AgentContext, SkillIntegrityError
from .policy import GuardrailPolicy
from .registry import SkillRegistry, digest_directory


def make_tool_policy_middleware(
    policy: GuardrailPolicy,
    ctx: AgentContext,
    *,
    audit_sink: Callable[[dict[str, Any]], None] | None = None,
):
    """Create LangChain/DeepAgents middleware that gates tool calls.

    The middleware intercepts every tool call and either forwards it to the handler
    or returns a structured denial message. Keep any durable audit persistence in
    `audit_sink`; do not mutate middleware object state during concurrent runs.
    """

    try:
        from langchain.agents.middleware import wrap_tool_call
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("langchain is required for make_tool_policy_middleware") from exc

    @wrap_tool_call
    def tool_policy_guard(request, handler):  # type: ignore[no-untyped-def]
        tool_name = getattr(request, "name", None) or getattr(request, "tool", None) or str(request)
        args = getattr(request, "args", None) or {}
        decision = policy.check_tool_call(ctx, str(tool_name), args if isinstance(args, dict) else {})
        event = {
            "kind": "tool_decision",
            "agent_id": ctx.agent_id,
            "tool": str(tool_name),
            "effect": decision.effect,
            "reason": decision.reason,
            "matched": list(decision.matched),
            "obligations": list(decision.obligations),
        }
        if audit_sink:
            audit_sink(event)

        if decision.allowed:
            return handler(request)

        # This is intentionally explicit: the model sees the denial and can pick
        # a safer path rather than silently failing.
        return json.dumps(
            {
                "error": "POLICY_DENIED",
                "tool": str(tool_name),
                "reason": decision.reason,
                "matched": list(decision.matched),
                "obligations": list(decision.obligations),
            }
        )

    return tool_policy_guard


def verify_registry_digests(
    registry: SkillRegistry,
    *,
    agent_id: str = "runtime",
    audit_sink: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Re-verify every admitted skill's digest; raise SkillIntegrityError on mismatch.

    This is the SG-2 fail-closed check, callable from any hook. Cost is one SHA-256
    pass over each (small) skill directory.
    """

    for record in registry.records.values():
        if not record.path.is_dir():
            current = ""
        else:
            current = digest_directory(record.path)
        if current != record.digest:
            if audit_sink:
                audit_sink(
                    {
                        "kind": "integrity_violation",
                        "agent_id": agent_id,
                        "skill_id": record.skill_id,
                        "effect": "deny",
                        "reason": "skill content digest changed since admission",
                        "matched": ["skill.digest_mismatch"],
                        "obligations": ["rescan_required"],
                        "expected_digest": record.digest,
                        "actual_digest": current,
                    }
                )
            raise SkillIntegrityError(record.skill_id, record.digest, current)


def make_digest_verification_middleware(
    registry: SkillRegistry,
    ctx: AgentContext,
    *,
    audit_sink: Callable[[dict[str, Any]], None] | None = None,
):
    """LangChain/DeepAgents middleware enforcing SG-2 at run time.

    `before_agent` re-verifies every admitted skill's digest on each invocation, so a
    skill directory mutated after admission (TOCTOU) aborts the run instead of being
    silently loaded by the SkillsMiddleware.
    """

    try:
        from langchain.agents.middleware import AgentMiddleware
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("langchain is required for make_digest_verification_middleware") from exc

    class SkillDigestGuardMiddleware(AgentMiddleware):  # type: ignore[misc]
        def before_agent(self, state, runtime=None):  # type: ignore[no-untyped-def]
            verify_registry_digests(registry, agent_id=ctx.agent_id, audit_sink=audit_sink)
            return None

        async def abefore_agent(self, state, runtime=None):  # type: ignore[no-untyped-def]
            verify_registry_digests(registry, agent_id=ctx.agent_id, audit_sink=audit_sink)
            return None

    return SkillDigestGuardMiddleware()


def filter_tools_for_agent(policy: GuardrailPolicy, ctx: AgentContext, tools: list[Any]) -> list[Any]:
    """Reduce the tool list before handing it to an agent/subagent.

    Runtime middleware is still required because MCP tools or dynamically-added tools
    can appear later. This pre-filter improves model focus and reduces accidental use.
    """

    filtered: list[Any] = []
    for tool in tools:
        name = getattr(tool, "name", None) or getattr(tool, "__name__", None) or str(tool)
        if policy.tool_allowed(ctx, str(name)):
            filtered.append(tool)
    return filtered
