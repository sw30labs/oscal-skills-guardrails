# ADR-0003: The judge grades a fixed R1-R7 rubric whose severities it can confirm but never soften, over a bounded, sentinel-wrapped snapshot

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

The judge reads hostile content (the skills under review). `rubric_judge.py` documents the threat: "the judge reads hostile content", and states that residual injection risk is why the judge is "evidence stream number two, never a replacement for the static scan".

## Decision

`DEFAULT_SKILL_RUBRIC` defines seven criteria with fixed fail severities: R1 intent alignment (high), R2 scope minimality (medium), R3 tool justification (medium), R4 data boundary (critical), R5 influence boundary (critical), R6 provenance (low), R7 human oversight (medium). `build_judge_prompt` wraps the skill between `<<<SKILL_CONTENT_BEGIN>>>` / `<<<SKILL_CONTENT_END>>>` sentinels, declares it untrusted data, and says an attempt to address the reviewer is itself an R5 failure. Output must be strict JSON; `extract_json_object` takes the first parseable object (tolerating prose and fences). Each `fail` becomes `RUB-<id>` at the rubric's severity; `unclear` or missing criteria become `info` findings; criterion ids outside the rubric are ignored. Content is a bounded snapshot from `collect_skill_content`: full SKILL.md up to 16,000 chars, a file inventory, and text-file excerpts (known suffixes, 4,000 chars each, 48,000 total). Verdicts carry `RUBRIC_VERSION = "0.1"` and the judge name.

## Consequences

### Positive

- Severity is set by policy authors, not by the model: the judge can only say pass, fail or unclear.
- Every criterion is reported, so missing coverage is visible (`missing`).
- Prompt size is bounded regardless of skill size.

### Negative

- `unclear` and missing criteria are only `info`, so an evasive or incomplete judge answer does not block admission by itself.
- Content beyond the caps, or in files without a listed text suffix, is seen only by the static stream (A-008).
- The sentinels are not escaped inside skill content (A-009).

## Alternatives considered

- Letting the judge assign severities (not adopted; the docstring says the judge 'can confirm a failure but never lower its severity').
- Free-form judge prose without a schema (rejected: output is 'strictly parsed JSON validated against the rubric's criterion ids').

## Evidence

- src/deepagent_skill_guardrails/rubric_judge.py (`DEFAULT_SKILL_RUBRIC`, `build_judge_prompt`, `collect_skill_content`, `extract_json_object`, `RubricJudgeScanner.scan`)
- README.md (Rubric judge)
- data/oscal-policies/skill-guardrails-catalog.json (sg-9)
- tests/test_rubric_judge.py
- commit 46003d3
