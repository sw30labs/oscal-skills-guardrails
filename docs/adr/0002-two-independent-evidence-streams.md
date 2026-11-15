# ADR-0002: Admit skills on two independent evidence streams: Skillspector static scan plus an LLM rubric judge

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

The README argues that a static scan "catches the shape of an attack" and a judge "catches its meaning": a skill that politely emails a contacts file "scores 100/A" on Skillspector but fails the judge at critical. ROADMAP lists "replacing static analysis with the judge" as a non-goal: "two streams is the design, not a transition". PR #1 (branch `demo/meeting-notes-exfil-skill`, still open) is the deliberately unmergeable demo of that contradiction.

## Decision

Each skill is scanned by `CompositeSkillScanner(scanners=(SubprocessSkillScanner(...Skillspector...), RubricJudgeScanner(...)))`. Merge rules: findings are concatenated; `score` is the minimum reported; `grade` is the worst reported; the judge's `rubric` section is surfaced top-level so policy can test for it; each scanner's raw report is kept under `raw["scanners"][<name>]`. Rubric failures become ordinary `ScanFinding`s, so the same severity, score and grade thresholds gate both streams. The CLI adds the judge automatically when `--rubric-judge-*` flags or `SKILL_JUDGE_MODEL` / `OMLX_MODEL` are set; without them it runs static-only.

## Consequences

### Positive

- No new policy machinery: semantic failures flow through `max_scan_severity` like static findings.
- Contradictions between streams (score 100, severity critical, effect deny) land verbatim in the audit trail.
- Either stream can be swapped (any JSON-on-stdout scanner, any judge callable).

### Negative

- Admission cost and latency now include an LLM call per skill.
- Without a judge configured (the CI default today) only the static stream runs; policies needing SG-9 then fail closed (see ADR-0004).

## Alternatives considered

- Judge only (rejected as a non-goal in ROADMAP).
- Static scan only: the README's meeting-notes example is the stated reason it is insufficient.

## Evidence

- src/deepagent_skill_guardrails/scanner.py (`CompositeSkillScanner`)
- src/deepagent_skill_guardrails/rubric_judge.py (module docstring)
- src/deepagent_skill_guardrails/cli.py (`_build_scanner`)
- README.md (intro, The two evidence streams); ROADMAP.md (Non-goals)
- tests/test_rubric_judge.py (`test_composite_merges_streams`)
- commit 46003d3
