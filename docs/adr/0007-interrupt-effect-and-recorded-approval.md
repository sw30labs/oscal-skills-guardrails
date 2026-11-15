# ADR-0007: Human approval is an `interrupt` decision effect, cleared only by an explicit, recorded approval

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

SG-6: "Skills whose scan severity meets the interrupt threshold, or which carry an explicit interrupt effect, require human approval before exposure. Approval decisions are recorded." ROADMAP's v0.2 item "Approvals bound to digests" says the current approval "approves a name; it should approve a content hash".

## Decision

`check_skill` returns `interrupt` (obligation `human_approval`) when the scan's max severity is at or above `interrupt_at_severity`, or when the per-skill `effect` is `interrupt` (after the severity gates). `admit_skills` and `cmd_admit` admit an interrupted skill only if its id is in `approved_skill_ids` / `--approve`; the audit event is rewritten to `allow` with reason `human-approved: ...` and obligation `approval_recorded`. Unapproved interrupts are excluded at runtime; in the CLI they fail the run only with `--fail-on interrupt` (default `--fail-on deny`).

## Consequences

### Positive

- Approval is explicit and appears in the assessment-results trail.
- An interrupt never overrides a severity denial (tested).

### Negative

- Approval is keyed by skill name, not by digest, so an approved skill that later changes is still approved by name (A-013; ROADMAP).
- The CLI default `--fail-on deny` lets unapproved interrupts pass a gate unless the caller opts in (CI does opt in).

## Alternatives considered

- Approving content hashes with persisted approval records (ROADMAP v0.2, not built).

## Evidence

- src/deepagent_skill_guardrails/policy.py (`check_skill` interrupt branches)
- src/deepagent_skill_guardrails/deepagents_factory.py (`admit_skills`)
- src/deepagent_skill_guardrails/cli.py (`cmd_admit`, `--approve`, `--fail-on`)
- data/oscal-policies/skill-guardrails-catalog.json (sg-6); ROADMAP.md
- tests/test_cli.py (`test_admit_interrupt_approval_loop`); tests/test_oscal_loader.py (`test_effect_override`)
