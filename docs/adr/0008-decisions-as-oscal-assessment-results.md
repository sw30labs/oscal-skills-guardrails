# ADR-0008: Every guardrail decision is emitted as OSCAL assessment-results (observations for all, findings for deny/interrupt)

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

SG-8: "Every admission and tool-call decision (effect, reason, matched rule, skill digest) is emitted to an audit sink, suitable for serialization as OSCAL assessment-results." The schema doc calls this the closed loop: "profile → decision → assessment result".

## Decision

`OscalAssessmentSink` is a plain callable used as `audit_sink` by the CLI, factory and middleware. It buffers events and `to_document()` renders one `assessment-results` document (OSCAL 1.1.2): every event becomes an observation (`methods: ["TEST"]`, `osg:*` props for kind, agent, effect, control, run id, skill, tool, digests, scan severity/score/grade, rubric judge/overall, matched, obligations; subject UUIDs are uuid5 of the skill or tool id); every `deny` / `interrupt` also becomes a finding targeting `<sg-control>_smt` with state `not-satisfied`. `control_for_event` maps matched-rule tokens to SG controls (first match wins). `import-ap` points at the policy profile, a documented deviation because no assessment plan document exists. The sink is standard-library only and documented as thread-unsafe (one sink per run).

## Consequences

### Positive

- Each CI run uploads its compliance evidence as a build artefact (ADR-0011).
- Decisions are traceable to the SG control and, through the catalog, to 800-53.

### Negative

- `import-ap` referencing a profile is not strictly valid OSCAL; ROADMAP plans a real assessment-plan document.
- The document is not validated against OSCAL schemas (ROADMAP).
- A `skill_rescan` event is always recorded with effect `allow`, even if the re-adjudication then denies the skill (A-017).

## Alternatives considered

- A plain JSON log (the sink could do this, but OSCAL output is the stated goal).

## Evidence

- src/deepagent_skill_guardrails/oscal_results.py
- src/deepagent_skill_guardrails/deepagents_factory.py (`skill_decision_event`)
- docs/oscal-skills-profile-schema.md (Audit (SG-8))
- tests/test_oscal_results.py; tests/test_cli.py
- commit 46003d3
