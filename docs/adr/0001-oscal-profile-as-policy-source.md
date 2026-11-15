# ADR-0001: An OSCAL profile is the single policy source, compiled into the existing GuardrailPolicy dict

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

The project governs Agent Skills (`SKILL.md` directories) loaded into LangGraph DeepAgents. The README states the aim: "OSCAL as the policy brain for Agent Skills" where "one OSCAL profile drives all of it — admission thresholds, per-agent skill visibility, tool allow/deny, filesystem rules, human-approval gates — and doubles as the compliance artifact, with every control mapped to NIST SP 800-53". `docs/oscal-skills-profile-schema.md` calls itself the "OSCAL equivalent of `oscal-agent-guardrails`", the sibling repo that governs tools rather than skills.

## Decision

Policy is authored as an OSCAL 1.1.2 profile (`data/oscal-policies/skills-policy-profile.json`) that imports an SG control catalog (`skill-guardrails-catalog.json`, SG-1 to SG-9 with 800-53 links). `oscal_loader.compile_profile` compiles it into the plain dict that `GuardrailPolicy` already consumes (`defaults`, `agents`, `subagents`, `skills`, `roles`, `filesystem_permissions`, plus `_oscal` metadata for audit). Policy statements are `osg:`-prefixed props (namespace `https://sw30labs.com/ns/osg`); org-wide defaults come from `modify.set-parameters`; the target type comes from `osg:target-type` or is inferred from the control-id prefix (`sg-def`, `sg-agt-`, `sg-sub-`, `sg-skl-`, `sg-rol-`, `sg-fs-`; `wildcard` maps to `*`). Both the pragmatic `modify.controls[*].props` shape and strict `modify.alters[*].adds[*].props` are accepted. Unknown props are ignored; an unknown target type raises. YAML (`GuardrailPolicy.from_yaml`, `examples/policy.yaml`) remains an interchangeable input.

## Consequences

### Positive

- One artefact is both the runtime policy and the compliance record mapped to 800-53.
- The runtime engine stays small and format-agnostic; OSCAL is only the authoring and reporting layer.
- Forward compatible: unknown props are skipped rather than failing a load.

### Negative

- All OSCAL prop values are strings, so typed values (`min_score`, `require_rubric`) need explicit conversion in the loader.
- The profile is not validated against the NIST OSCAL schemas; ROADMAP lists strict schema validation as future work.
- The shipped profile and `examples/policy.yaml` must be kept in step by hand (the profile remarks call itself the OSCAL equivalent of the YAML).

## Alternatives considered

- YAML-only policy (still supported via `--policy`, but not the primary format).
- A general policy engine such as OPA or Cedar: the `GuardrailPolicy` docstring says to keep the interface and swap the implementation if that is wanted later; not adopted.

## Evidence

- src/deepagent_skill_guardrails/oscal_loader.py
- src/deepagent_skill_guardrails/policy.py (`GuardrailPolicy`, `from_yaml`)
- data/oscal-policies/skills-policy-profile.json; data/oscal-policies/skill-guardrails-catalog.json
- docs/oscal-skills-profile-schema.md (Prop vocabulary, Loader contract)
- README.md (Policy as an OSCAL profile)
- tests/test_oscal_loader.py
- commit 46003d3 (Initial release)
