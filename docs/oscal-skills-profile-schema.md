# OSCAL Skills-Guardrails Profile Schema (v0.1)

OSCAL equivalent of `oscal-agent-guardrails` — but the governed object is an **Agent Skill** (a `SKILL.md` directory), not a tool. The profile is the single policy artifact that drives:

1. **Admission** — a skill is scanned (Skillspector) and blocked if findings exceed the risk appetite.
2. **Visibility** — which agents/subagents see which skills.
3. **Execution** — tool allow/deny inside skill context, filesystem rules.
4. **Compliance** — the same artifact maps to NIST SP 800-53, and decisions can be logged as OSCAL `assessment-results`.

The profile is **compiled** into the existing `GuardrailPolicy` dict by `deepagent_skill_guardrails.oscal_loader`. The runtime engine is unchanged; OSCAL is the authoring and reporting format.

```text
skills-policy-profile.json ──oscal_loader──▶ GuardrailPolicy ──▶ registry / middleware / factory
        │
        └── imports skill-guardrails-catalog.json (SG control family, 800-53 links)
```

## Files

| File | Role |
|---|---|
| `data/oscal-policies/skill-guardrails-catalog.json` | Catalog defining the SG control family + parameters |
| `data/oscal-policies/skills-policy-profile.json` | Example profile — mirrors `examples/policy.yaml` |
| `src/deepagent_skill_guardrails/oscal_loader.py` | Profile → `GuardrailPolicy` compiler |

## The SG control family (catalog)

| Control | Title | 800-53 rev5 related |
|---|---|---|
| SG-1 | Skill Admission Scanning | RA-5, SI-3 |
| SG-2 | Skill Integrity Verification (digest) | SI-7, SR-4 |
| SG-3 | Skill Visibility & Least Exposure | AC-3, CM-7 |
| SG-4 | Tool Least Functionality | CM-7(5), AC-6 |
| SG-5 | Skill Filesystem Protection | AC-6(1), CM-5 |
| SG-6 | Human Approval Gate | AC-3, CM-3 |
| SG-7 | Skill Provenance & Metadata | SR-3, CM-8 |
| SG-8 | Guardrail Audit Logging | AU-2, AU-12 |
| SG-9 | Semantic Rubric Review (LLM judge) | SA-11, CA-2 |

## Prop vocabulary

Namespace: `https://sw30labs.com/ns/osg` (stable identifier, not resolvable). Props follow the sibling repo's convention of prefixed names (`og:` → here `osg:`). All values are strings (OSCAL constraint). Repeatable props express lists.

### Target binding (every policy control carries these)

| Prop | Values | Meaning |
|---|---|---|
| `osg:target-type` | `defaults` \| `agent` \| `subagent` \| `skill` \| `role` \| `filesystem` | Which policy section this control compiles into |
| `osg:target-id` | free string / glob (`*` for the agent wildcard) | Agent id, subagent name, skill name, or role |

If `osg:target-type` is absent, the loader infers it from the control-id prefix (see conventions below).

### Visibility & tools (SG-3 / SG-4)

| Prop | Repeatable | Compiles to |
|---|---|---|
| `osg:allow-skill` | yes (glob) | `allow_skills` |
| `osg:deny-skill` | yes (glob) | `deny_skills` |
| `osg:allow-tool` | yes (glob) | `allow_tools` |
| `osg:deny-tool` | yes (glob) | `deny_tools` |

### Risk appetite (SG-1 / SG-6)

| Prop | Values | Compiles to | Semantics |
|---|---|---|---|
| `osg:max-scan-severity` | `none`..`critical` | `max_scan_severity` | Deny if scan max severity **exceeds** this |
| `osg:interrupt-at-severity` | `info`..`critical` | `interrupt_at_severity` | Human approval at or above this severity |
| `osg:min-score` | `0`..`100` | `min_score` | Deny if Skillspector score is **below** this. Fail-closed: deny if the scanner reported no score |
| `osg:min-grade` | `A`..`F` | `min_grade` | Deny if Skillspector grade is worse. Fail-closed on missing grade |
| `osg:require-rubric` | `true` \| `false` | `require_rubric` | Deny if the scan carries no LLM rubric-judge evidence stream (SG-9). Rubric criterion failures themselves arrive as ordinary findings (`RUB-*`) at rubric-defined severities and are gated by `osg:max-scan-severity` |

Precedence for thresholds (most specific wins): per-skill spec → agent spec → defaults. Agent spec itself is layered: `agents["*"]` → matched `roles` → `agents[<id>]`.

### Per-skill overrides (SG-1 / SG-7)

| Prop | Values | Semantics |
|---|---|---|
| `osg:effect` | `allow` \| `deny` \| `interrupt` | Hard override. `deny` short-circuits immediately; `interrupt` forces human approval **after** severity checks (severity deny still wins); `allow` is a no-op — it never bypasses the severity/score gates |
| `osg:reason` | string | Human rationale, surfaced in `Decision.reason` |
| `osg:required-metadata` | `key=value`, repeatable | All pairs must match `SKILL.md` frontmatter `metadata` |

### Filesystem (SG-5)

| Prop | Repeatable | Compiles to |
|---|---|---|
| `osg:fs-operation` | yes (`read`/`write`/`edit`/`delete`) | `filesystem_permissions[].operations` |
| `osg:fs-path` | yes (glob) | `filesystem_permissions[].paths` |
| `osg:fs-mode` | no (`allow`/`deny`/`interrupt`) | `filesystem_permissions[].mode` |

## Global defaults via `set-parameters`

Org-wide risk appetite lives in `modify.set-parameters`, referencing catalog parameter ids:

| `param-id` | Compiles to `defaults.` |
|---|---|
| `osg-max-scan-severity` | `max_scan_severity` |
| `osg-interrupt-at-severity` | `interrupt_at_severity` |
| `osg-min-score` | `min_score` |
| `osg-min-grade` | `min_grade` |
| `osg-allow-skills` | `allow_skills` (all `values`) |
| `osg-deny-tools` | `deny_tools` (all `values`) |
| `osg-require-rubric` | `require_rubric` |

```json
{ "param-id": "osg-max-scan-severity", "values": ["medium"] }
```

## Control-id conventions (profile)

One policy statement = one entry in `modify.controls[]`. The id encodes the catalog control it instantiates plus the target:

```text
sg-def                      defaults           (SG-1)
sg-agt-<agent-id>           agent spec         (SG-1/3/4)
sg-sub-<subagent-name>      subagent spec      (SG-3/4)
sg-skl-<skill-name>         per-skill spec     (SG-1/7)
sg-rol-<role>               role spec          (SG-3/4)
sg-fs-<n>                   filesystem rule    (SG-5)
```

Example — a per-agent control:

```json
{
  "control-id": "sg-agt-coding-agent",
  "props": [
    { "name": "osg:target-type", "value": "agent", "ns": "https://sw30labs.com/ns/osg" },
    { "name": "osg:target-id", "value": "coding-agent" },
    { "name": "osg:allow-skill", "value": "langgraph-*" },
    { "name": "osg:allow-skill", "value": "code-review" },
    { "name": "osg:allow-tool", "value": "read_file" },
    { "name": "osg:deny-tool", "value": "execute" },
    { "name": "osg:max-scan-severity", "value": "medium" },
    { "name": "osg:min-grade", "value": "B" }
  ]
}
```

Example — a hard skill override:

```json
{
  "control-id": "sg-skl-oscal-authoring",
  "props": [
    { "name": "osg:target-type", "value": "skill" },
    { "name": "osg:target-id", "value": "oscal-authoring" },
    { "name": "osg:max-scan-severity", "value": "low" },
    { "name": "osg:required-metadata", "value": "owner=governance" },
    { "name": "osg:reason", "value": "Curated governance skill; low tolerance." }
  ]
}
```

## Loader contract

`oscal_loader.load_skills_policy_profile(path) -> GuardrailPolicy`

- Accepts both the pragmatic shape (`modify.controls[*].props`, sibling-repo style) and strict OSCAL (`modify.alters[*].adds[*].props`).
- Unknown props are ignored (forward compatible); unknown `osg:target-type` raises.
- `ns` on props is optional; matching is by prefixed `name`.
- The compiled dict is exactly the shape `GuardrailPolicy` already consumes, so YAML and OSCAL policies are interchangeable at runtime. `GuardrailPolicy.raw["_oscal"]` retains profile metadata (uuid, version, title) for audit trails.

## Fail-closed rules

- Scanner execution failure, missing target, or invalid JSON → synthetic `critical` finding (existing scaffold behavior) → blocked by any sane threshold.
- `min_score`/`min_grade` set but scanner reported no score/grade → **deny** with reason `scan.score_missing`.
- Unknown skills (never ingested/scanned) never reach `create_deep_agent` — admission is allowlist-shaped by construction.

## Audit (SG-8) — implemented

`oscal_results.OscalAssessmentSink` is an `audit_sink`-compatible callable. Every decision event becomes an observation (with `osg:*` props: agent, skill, effect, digest, scan score/grade, matched rule, run id); every deny/interrupt additionally becomes a finding targeting `<sg-control>_smt` with state `not-satisfied`. `sink.write(path)` emits the `assessment-results` document. Closed loop: profile → decision → assessment result.

## Integrity (SG-2) — implemented

`SkillRegistry.verify/verify_all` recompute digests against admitted ones; `save_digest_lock`/`verify_digest_lock` persist and check them across processes (CI drift detection, statuses ok/changed/missing/new). `create_guarded_deep_agent(verify_digests=True)` re-verifies before computing skill paths (`on_digest_mismatch="deny"|"rescan"`) and installs a `before_agent` middleware that raises `SkillIntegrityError` (fail closed) if any admitted skill mutates between invocations.

## Versioning

Schema version is carried in `profile.metadata.version` plus prop `osg:schema-version` on `sg-def` (current: `0.1`). Prop names are a stable contract once tagged `1.0` — same rule as Skillspector rule ids.
