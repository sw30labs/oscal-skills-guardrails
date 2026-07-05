from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Collection, Literal, Sequence

from .middleware import (
    filter_tools_for_agent,
    make_digest_verification_middleware,
    make_tool_policy_middleware,
)
from .models import AgentContext, Decision, SkillRecord
from .policy import GuardrailPolicy
from .registry import SkillRegistry


def skill_decision_event(ctx: AgentContext, record: SkillRecord, decision: Decision) -> dict[str, Any]:
    """Shape a skill admission Decision as an audit event (consumed by OscalAssessmentSink)."""
    rubric = record.scan.raw.get("rubric") if isinstance(record.scan.raw, dict) else None
    return {
        "kind": "skill_decision",
        "agent_id": ctx.agent_id,
        "skill_id": record.skill_id,
        "effect": decision.effect,
        "reason": decision.reason,
        "matched": list(decision.matched),
        "obligations": list(decision.obligations),
        "digest": record.digest,
        "scan_severity": record.scan.max_severity,
        "scan_score": record.scan.raw.get("score"),
        "scan_grade": record.scan.raw.get("grade"),
        "rubric_judge": (rubric or {}).get("judge") if isinstance(rubric, dict) else None,
        "rubric_overall": (rubric or {}).get("overall") if isinstance(rubric, dict) else None,
    }


def admit_skills(
    policy: GuardrailPolicy,
    ctx: AgentContext,
    records: Collection[SkillRecord],
    *,
    approved_skill_ids: Collection[str] = (),
    audit_sink: Callable[[dict[str, Any]], None] | None = None,
) -> list[str]:
    """Evaluate every record for `ctx`; return admitted skill paths, auditing each decision.

    * allow            -> admitted
    * interrupt        -> admitted only if the skill id is in `approved_skill_ids`
                          (the recorded human-approval loop, SG-6); otherwise excluded
    * deny             -> excluded
    """

    approved = set(approved_skill_ids)
    admitted: list[str] = []
    for record in records:
        decision = policy.check_skill(ctx, record)
        event = skill_decision_event(ctx, record, decision)
        if decision.interrupted and record.skill_id in approved:
            event["effect"] = "allow"
            event["reason"] = f"human-approved: {decision.reason}"
            event["obligations"] = ["approval_recorded"]
            admitted.append(str(record.path))
        elif decision.allowed:
            admitted.append(str(record.path))
        if audit_sink:
            audit_sink(event)
    return admitted


def create_guarded_deep_agent(
    *,
    model: Any,
    tools: Sequence[Any] | None,
    system_prompt: str | None,
    agent_context: AgentContext,
    policy: GuardrailPolicy,
    registry: SkillRegistry,
    subagents: Sequence[dict[str, Any]] | None = None,
    approved_skill_ids: Collection[str] = (),
    verify_digests: bool = True,
    on_digest_mismatch: Literal["deny", "rescan"] = "deny",
    backend: Any | None = None,
    checkpointer: Any | None = None,
    store: Any | None = None,
    audit_sink: Callable[[dict[str, Any]], None] | None = None,
    extra_middleware: Sequence[Any] = (),
    **kwargs: Any,
):
    """Factory that turns a registry+policy decision into a Deep Agent.

    Behavior:
      * SG-2: admitted digests are re-verified before skill paths are computed.
        Mismatches are denied (default) or re-ingested/re-scanned (`"rescan"`), and a
        runtime middleware re-verifies on every invocation (fails closed with
        SkillIntegrityError).
      * SG-3: main agent and each custom subagent get their own policy-filtered
        `skills` list; every admission decision is emitted to `audit_sink`.
      * SG-4: tools are pre-filtered and enforced at runtime with middleware.
      * SG-5: DeepAgents filesystem permissions are materialized from policy.
      * SG-6: interrupt-effect skills load only when listed in `approved_skill_ids`.
    """

    try:
        from deepagents import create_deep_agent
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install deepagents to use create_guarded_deep_agent") from exc

    # ------------------------------------------------------------------ SG-2
    records: dict[str, SkillRecord] = dict(registry.records)
    if verify_digests:
        for skill_id, record in list(records.items()):
            ok, current = registry.verify(skill_id)
            if ok:
                continue
            if on_digest_mismatch == "rescan" and record.path.is_dir():
                fresh = registry.ingest(record.path)
                records[skill_id] = fresh
                if audit_sink:
                    audit_sink(
                        {
                            "kind": "skill_rescan",
                            "agent_id": agent_context.agent_id,
                            "skill_id": skill_id,
                            "effect": "allow",
                            "reason": "digest changed since admission; re-scanned and re-adjudicated",
                            "matched": ["skill.digest_mismatch"],
                            "obligations": ["review_scan_report"],
                            "expected_digest": record.digest,
                            "actual_digest": fresh.digest,
                        }
                    )
            else:
                records.pop(skill_id)
                if audit_sink:
                    audit_sink(
                        {
                            "kind": "integrity_violation",
                            "agent_id": agent_context.agent_id,
                            "skill_id": skill_id,
                            "effect": "deny",
                            "reason": "skill content digest changed since admission",
                            "matched": ["skill.digest_mismatch"],
                            "obligations": ["rescan_required"],
                            "expected_digest": record.digest,
                            "actual_digest": current,
                        }
                    )

    tool_list = list(tools or [])
    main_skills = admit_skills(
        policy,
        agent_context,
        records.values(),
        approved_skill_ids=approved_skill_ids,
        audit_sink=audit_sink,
    )
    main_tools = filter_tools_for_agent(policy, agent_context, tool_list)
    main_middleware: list[Any] = [
        make_tool_policy_middleware(policy, agent_context, audit_sink=audit_sink),
    ]
    if verify_digests:
        main_middleware.append(
            make_digest_verification_middleware(registry, agent_context, audit_sink=audit_sink)
        )
    main_middleware.extend(extra_middleware)

    guarded_subagents: list[dict[str, Any]] = []
    for subagent in subagents or []:
        spec = deepcopy(dict(subagent))
        subagent_id = str(spec["name"])
        sub_ctx = agent_context.for_agent(subagent_id)
        explicit_tools = spec.get("tools")
        spec["tools"] = filter_tools_for_agent(
            policy,
            sub_ctx,
            list(explicit_tools if explicit_tools is not None else tool_list),
        )
        spec["skills"] = admit_skills(
            policy,
            sub_ctx,
            records.values(),
            approved_skill_ids=approved_skill_ids,
            audit_sink=audit_sink,
        )
        spec["middleware"] = [
            make_tool_policy_middleware(policy, sub_ctx, audit_sink=audit_sink),
            *(spec.get("middleware") or []),
        ]
        guarded_subagents.append(spec)

    permissions = policy.deepagents_filesystem_permissions()

    return create_deep_agent(
        model=model,
        tools=main_tools,
        system_prompt=system_prompt,
        skills=main_skills,
        subagents=guarded_subagents,
        middleware=main_middleware,
        permissions=permissions,
        backend=backend,
        checkpointer=checkpointer,
        store=store,
        **kwargs,
    )
