# Roadmap

Where this goes from v0.1.0. Shipped baseline: dual-evidence admission (Skillspector
static scan + LLM rubric judge), OSCAL SG-1…9 catalog mapped to 800-53, digest
lockfile + runtime TOCTOU guard, human-approval loop, DeepAgents enforcement,
assessment-results audit trail, and the CI gate with both jobs as required checks —
demonstrated live by [PR #1](https://github.com/sw30labs/oscal-skills-guardrails/pull/1),
the deliberately unmergeable exfil skill (static 100/A, denied on meaning).

Items are ordered by intent, not by promise. Rule ids (`SEC-*`, `QUA-*`, `RUB-*`),
`osg:` props, and SG control ids freeze as stable contracts at 1.0.

## Now (v0.2) — harden the reference

**Pin the Skillspector checkout.** CI checks the engine out from
`sw30labs/skillspector-trial@main`; pin `ref:` to a tag/SHA and bump deliberately.
The gate's own supply chain should meet the standard it enforces (SR-4 for
ourselves).

**Semantic stream in CI.** Point repo vars `SKILL_JUDGE_URL` / `SKILL_JUDGE_MODEL`
(+ secret `SKILL_JUDGE_API_KEY`) at a reachable OpenAI-compatible endpoint so SG-9
runs in CI, not only locally against oMLX. Then PR #1 goes red for the deeper
reason: R4/R5 critical, not just rubric-evidence-missing.

**Digest guard for subagents.** The runtime `before_agent` digest middleware
currently ships on the main agent; extend it to custom subagent middleware stacks
so SG-2 covers every execution context.

**Approvals bound to digests.** `approved_skill_ids` approves a name; it should
approve a *content hash*. Persist approval records as `(skill_id, digest, approver,
timestamp)` and invalidate automatically when the skill changes — re-approval after
mutation is the whole point of SG-6 × SG-2.

**Symlink policy in the registry.** `scan_skill.mjs` skips symlinks; `digest_directory`
should apply the same rule (or hash link targets explicitly) so the two views of a
skill can never diverge.

## Next (v0.3–v0.5) — deepen the OSCAL loop

**Strict OSCAL validation.** Validate the catalog, profile, and emitted
assessment-results against the NIST OSCAL 1.1.2 schemas (oscal-cli / metaschema) in
CI; replace the documented `import-ap` deviation by generating a real assessment-plan
document from the profile.

**POA&M generation.** Denied and interrupted skills become OSCAL
plan-of-action-and-milestones entries with remediation drawn from findings — closing
the last gap in the profile → decision → evidence → remediation chain.

**Runtime evidence.** The factory already audits admission; ship a worked example
where a long-running agent's tool denials and integrity events flush periodically to
assessment-results, giving a continuous-monitoring story (CA-7), not only an
admission-time one.

**Judge rigor.** Pin the judge in policy (`osg:rubric-judge-pattern`: deny if the
evidence stream's judge doesn't match the mandated model class); per-criterion
verdicts as individual observations; a small golden-skill eval set (clean / subtle-exfil
/ influence attempts) to measure judge recall before trusting a new model; optional
multi-judge quorum for high-assurance catalogs.

**Skillspector upstream.** Teach the YAML-lite frontmatter parser (QUA-002) to
tolerate spec-valid nested `metadata:` blocks, and decide on the naming collision
with NVIDIA's SkillSpector before wider publication.

## Later (v1.0 and beyond) — from reference to infrastructure

**Reusable GitHub Action.** Package the gate as `uses:
sw30labs/oscal-skills-guardrails@v1` with inputs for skills root, profile, judge
endpoint, and fail mode — one stanza to adopt in any repo that ships skills.

**PyPI release.** `pip install deepagent-skill-guardrails`; the `skill-guardrails`
console script becomes the canonical entry point.

**Signed admissions.** Grow the digest lockfile into attestation: sign
`(digest, scan report, rubric verdict, approver)` with sigstore/cosign so a runtime
can verify not just *that* content is unchanged but *that this exact content passed
this exact gate* — the trust-and-signing pattern the ecosystem is converging on.

**Pre-install gate for skill marketplaces.** Expose `admit` through the existing MCP
server so agent platforms (Claude/Cowork skills, DeepAgents CLI, plugin registries)
can call the gate before installation, with the assessment-results document returned
as the install receipt.

**The write-up.** An article walking the whole loop, with PR #1 as the centerpiece
exhibit: the skill that scored 100/A and could not merge.

## Non-goals

Replacing static analysis with the judge (two streams is the design, not a
transition); becoming a general LangChain guardrails framework (tool-call policy
beyond skills stays minimal); shipping a hosted service — this stays a reference
implementation others can run entirely on their own machines, judge included.
