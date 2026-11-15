# ADR-0009: `create_guarded_deep_agent`: admit skills, pre-filter tools, and enforce tool policy at runtime with a visible POLICY_DENIED result

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

DeepAgents loads skills and tools for a main agent and its subagents. `filter_tools_for_agent` explains why one layer is not enough: "Runtime middleware is still required because MCP tools or dynamically-added tools can appear later. This pre-filter improves model focus and reduces accidental use." SG-4 requires tool allow/deny for every agent and subagent.

## Decision

`create_guarded_deep_agent` wraps `deepagents.create_deep_agent`: optional digest re-verification (ADR-0006); `admit_skills` computes each agent's skill paths from policy decisions; `filter_tools_for_agent` removes disallowed tools up front; `make_tool_policy_middleware` (LangChain `wrap_tool_call`) checks every call through `check_tool_call`, records a `tool_decision` event, and on refusal returns a JSON string with `"error": "POLICY_DENIED"`, reason, matched rules and obligations instead of raising ("the model sees the denial and can pick a safer path"). Each subagent is deep-copied and gets its own context (`for_agent`), its own filtered tools (explicit list or the parent's), its own admitted skills, and its own tool middleware prepended. Filesystem permissions come from the policy (ADR-0010).

## Consequences

### Positive

- Defence in depth: static pre-filter plus per-call runtime check, including for tools added later.
- Subagents are governed independently, matching the per-subagent policy sections.

### Negative

- Per-skill tool lists are never enforced at runtime because the middleware does not pass `skill_id` (A-003).
- Tool names are read from `request.name` / `request.tool`; if the LangChain request object exposes the name elsewhere, the check would run against `str(request)` (A-004, unverified).
- Subagents get neither the digest middleware nor the read-biased filesystem middleware (A-014).

## Alternatives considered

- Raising an exception on denial (not chosen; the code comments say the explicit denial is intentional).
- Pre-filter only (rejected in the `filter_tools_for_agent` docstring).

## Evidence

- src/deepagent_skill_guardrails/deepagents_factory.py (`admit_skills`, `create_guarded_deep_agent`, `filter_tools_for_agent`)
- src/deepagent_skill_guardrails/middleware.py (`make_tool_policy_middleware`)
- data/oscal-policies/skill-guardrails-catalog.json (sg-4)
- tests/test_policy.py; tests/test_digest_verification.py (deepagents-gated)
- commit 46003d3
