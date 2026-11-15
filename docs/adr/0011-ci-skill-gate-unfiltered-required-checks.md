# ADR-0011: The CI skill gate runs `admit` and `verify` on every PR, unfiltered, as two required checks

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

The workflow comment: "No `paths:` filter, deliberately: both jobs are branch-protection required checks, and a path-filtered required check never reports on unrelated PRs — blocking their merge." Commit 2d55a4f ("gate runs on every PR") removed the earlier filter added in 6c5f563.

## Decision

`.github/workflows/skill-gate.yml` has two jobs. `admit` checks out `sw30labs/skillspector-trial` (currently `@main`, with a comment to pin a tag/SHA), installs the package, and runs `skill-guardrails admit` over `examples/skills` against the shipped OSCAL profile as the `supervisor` persona with `--fail-on interrupt`, uploading the assessment-results document as an artefact. The judge joins only when repo variables `SKILL_JUDGE_URL` / `SKILL_JUDGE_MODEL` (and secret `SKILL_JUDGE_API_KEY`) are set; otherwise the log says it is static-only. `verify` checks the committed `skills.lock.json` with `--skills-root`. CI adjudicates as `supervisor` because, per the workflow comment, its allowlist covers the curated set.

## Consequences

### Positive

- Unrelated PRs (including docs-only ones) still receive both required checks.
- The lockfile diff and assessment-results artefact are the review evidence for each PR.

### Negative

- The scanner engine is pulled from an unpinned branch, so gate results can change without a commit here (A-015).
- CI does not run pytest, so the test suite is not a gate (A-016).
- Without judge variables the semantic stream (SG-9) does not run in CI.

## Alternatives considered

- Path-filtered workflow (used in 6c5f563, removed in 2d55a4f for the reason above).
- Running the judge unconditionally (not possible without a reachable endpoint; it is opt-in through repo vars).

## Evidence

- .github/workflows/skill-gate.yml
- skills.lock.json
- README.md (CI gate); ROADMAP.md (Pin Skillspector, Semantic stream in CI)
- commits 6c5f563, 2d55a4f
