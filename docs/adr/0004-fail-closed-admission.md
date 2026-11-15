# ADR-0004: Admission fails closed: scanner errors become critical findings and missing evidence is a denial

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

README section "Fail-closed invariants": "Unknown skill → not loaded. Scanner crash, timeout, or bad JSON → critical finding. Score/grade threshold set but scanner reported none → deny. `require_rubric` set but no judge evidence → deny. Judge endpoint down → critical. Digest drift → `SkillIntegrityError`. The gate never fails open." The catalog's SG-1 and SG-9 statements say the same.

## Decision

`SubprocessSkillScanner` returns a critical `SCANNER-TARGET-MISSING`, `SCANNER-EXECUTION-FAILED` (exit code other than 0 or 1) or `SCANNER-INVALID-JSON` finding; `HttpSkillScanner` returns critical `SCANNER-HTTP-FAILED`; `RubricJudgeScanner` returns critical `RUB-JUDGE-ERROR` on any exception. In `GuardrailPolicy.check_skill`, `min_score` / `min_grade` thresholds deny with `scan.score_missing` / `scan.grade_missing` when the scanner reported none, and `require_rubric` (truthy strings accepted) denies with `scan.rubric_missing` when the scan has no `rubric` section. The CLI turns any manifest/ingest exception into a `deny` row, and `NoopSkillScanner` is labelled dev-only with a warning that score/grade policies then fail closed.

## Consequences

### Positive

- A broken scanner or judge blocks rather than silently admitting.
- Missing evidence is distinguishable in the audit trail by its matched token (`scan.score_missing`, `scan.rubric_missing`).

### Negative

- Operational outages (judge endpoint down) stop admissions.
- Some paths do not match the README wording: a subprocess timeout raises instead of producing a critical finding (A-010), and unknown severity strings from a scanner are normalised to `info` (A-011).

## Alternatives considered

- Fail-open with a warning (rejected by the README's 'The gate never fails open').

## Evidence

- src/deepagent_skill_guardrails/scanner.py
- src/deepagent_skill_guardrails/policy.py (`check_skill`, `_truthy`)
- src/deepagent_skill_guardrails/rubric_judge.py (`RubricJudgeScanner.scan`)
- src/deepagent_skill_guardrails/cli.py (`_build_scanner`, `cmd_admit`)
- README.md (Fail-closed invariants); docs/oscal-skills-profile-schema.md (Fail-closed rules)
- tests/test_oscal_loader.py (`test_min_grade_denies_and_fails_closed`); tests/test_rubric_judge.py (`test_judge_error_fails_closed`, `test_require_rubric_fails_closed_and_oscal_prop`); tests/test_omlx_judge.py (`test_judge_endpoint_down_fails_closed`)
