# Architecture Decision Records — sw30labs/oscal-skills-guardrails

Retrospective decision log for `deepagent-skill-guardrails`, the OSCAL-driven admission and runtime guardrails for Agent Skills in LangGraph DeepAgents. Reviewed at `9d848f0` (main). The pre-existing schema reference stays at [`../oscal-skills-profile-schema.md`](../oscal-skills-profile-schema.md).

Format: Title; Status; Context; Decision; Consequences (positive/negative); Alternatives considered; Evidence (file paths, commit SHAs). All records here were written retrospectively on 2026-11-15 from a full read of the repository at the reviewed commit. Where the *why* is inferred rather than stated in the code, docs, or commit messages, the ADR says so and the inference is logged in [`../assumptions.md`](../assumptions.md).

| ADR | Title | Status |
|---|---|---|
| [0001](0001-oscal-profile-as-policy-source.md) | An OSCAL profile is the single policy source, compiled into the existing GuardrailPolicy dict | Accepted (retrospective) |
| [0002](0002-two-independent-evidence-streams.md) | Admit skills on two independent evidence streams: Skillspector static scan plus an LLM rubric judge | Accepted (retrospective) |
| [0003](0003-fixed-rubric-judge.md) | The judge grades a fixed R1-R7 rubric whose severities it can confirm but never soften, over a bounded, sentinel-wrapped snapshot | Accepted (retrospective) |
| [0004](0004-fail-closed-admission.md) | Admission fails closed: scanner errors become critical findings and missing evidence is a denial | Accepted (retrospective) |
| [0005](0005-layered-policy-precedence.md) | Layered policy precedence: per-skill spec over agent spec over defaults, deny patterns first, effect overrides never bypass gates | Accepted (retrospective) |
| [0006](0006-content-digest-lockfile-and-runtime-recheck.md) | Skill integrity by SHA-256 content digest: committed lockfile for CI, re-verification before and during agent runs | Accepted (retrospective) |
| [0007](0007-interrupt-effect-and-recorded-approval.md) | Human approval is an `interrupt` decision effect, cleared only by an explicit, recorded approval | Accepted (retrospective) |
| [0008](0008-decisions-as-oscal-assessment-results.md) | Every guardrail decision is emitted as OSCAL assessment-results (observations for all, findings for deny/interrupt) | Accepted (retrospective) |
| [0009](0009-guarded-deepagents-factory.md) | `create_guarded_deep_agent`: admit skills, pre-filter tools, and enforce tool policy at runtime with a visible POLICY_DENIED result | Accepted (retrospective) |
| [0010](0010-deepagents-07-delete-lockdown.md) | For deepagents 0.7+, auto-deny write on `/**` unless delete is explicitly allowed, and default the main agent to read-only filesystem tools | Accepted (retrospective) |
| [0011](0011-ci-skill-gate-unfiltered-required-checks.md) | The CI skill gate runs `admit` and `verify` on every PR, unfiltered, as two required checks | Accepted (retrospective) |
| [0012](0012-scanner-subprocess-json-contract.md) | Scanners are pluggable adapters behind a JSON-on-stdout subprocess contract; Skillspector runs through `scripts/scan_skill.mjs` | Accepted (retrospective) |
| [0013](0013-local-first-judge-adapters.md) | Judge adapters are local-first: oMLX on 127.0.0.1 by default, stdlib HTTP, temperature 0 | Accepted (retrospective) |
| [0014](0014-minimal-core-optional-extras.md) | Minimal core dependency (PyYAML) with optional extras for DeepAgents, MCP and the LangChain judge; Apache-2.0 | Accepted (retrospective) |
| [0015](0015-scanner-as-mcp-admin-profile.md) | Expose the scanner as an MCP server, but only in an admin/CI profile | Accepted (retrospective) |
| [0016](0016-strict-skill-manifest-gate.md) | Strict SKILL.md manifest gate, with flat top-level keys merged into metadata for Skillspector compatibility | Accepted (retrospective) |
