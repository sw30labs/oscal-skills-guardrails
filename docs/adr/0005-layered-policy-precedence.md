# ADR-0005: Layered policy precedence: per-skill spec over agent spec over defaults, deny patterns first, effect overrides never bypass gates

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

The schema doc defines precedence: "most specific wins: per-skill spec → agent spec → defaults. Agent spec itself is layered: `agents["*"]` → matched `roles` → `agents[<id>]`." It also defines `osg:effect`: "`deny` short-circuits immediately; `interrupt` forces human approval after severity checks (severity deny still wins); `allow` is a no-op — it never bypasses the severity/score gates".

## Decision

`GuardrailPolicy.agent_spec` merges `agents["*"]`, then each role in `ctx.roles`, then `agents[<agent_id>]`. `check_skill` evaluates in this order: agent `deny_skills`, agent `allow_skills` (deny if a list exists and the skill does not match), per-skill `effect: deny`, `max_scan_severity` (skill → agent → defaults → "medium"), `require_rubric`, `min_score`, `min_grade`, `interrupt_at_severity` (skill → agent), per-skill `effect: interrupt`, `required_metadata`; otherwise allow. `check_tool_call` merges the subagent spec over the agent spec for known subagents, combines agent and default `deny_tools`, denies on deny match, denies anything outside a non-empty `allow_tools`, then applies per-skill tool lists when a `skill_id` is passed. Matching uses `fnmatch.fnmatchcase` globs.

## Consequences

### Positive

- Predictable, testable ordering; denies are checked before allows.
- Per-skill overrides can only tighten, matching the documented `allow` no-op semantics.

### Negative

- Visibility does not fall back to `defaults.allow_skills` in `check_skill`: an agent with no allow list sees every skill, which contradicts the SG-3 catalog statement 'Absent an allow list, no skills are exposed' (A-001).
- `interrupt_at_severity` set only in defaults (for example via the `osg-interrupt-at-severity` parameter) is compiled but never consulted (A-002).
- Per-skill tool lists only apply when a caller passes `skill_id`, which the runtime middleware never does (A-003).

## Alternatives considered

- A first-match rule list (not used; the engine merges dicts by specificity).

## Evidence

- src/deepagent_skill_guardrails/policy.py (`agent_spec`, `subagent_spec`, `check_skill`, `check_tool_call`, `allowed_skill_ids`)
- docs/oscal-skills-profile-schema.md (Risk appetite, Per-skill overrides)
- data/oscal-policies/skill-guardrails-catalog.json (sg-3, sg-4)
- tests/test_policy.py; tests/test_oscal_loader.py (`test_effect_override`)
