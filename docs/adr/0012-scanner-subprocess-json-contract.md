# ADR-0012: Scanners are pluggable adapters behind a JSON-on-stdout subprocess contract; Skillspector runs through `scripts/scan_skill.mjs`

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

The scanner is a separate project (`sw30labs/skillspector-trial`, Node). The Python package needs a stable boundary that also accepts other scanners.

## Decision

`SkillScanner` is a protocol returning `ScanReport`. Adapters: `SubprocessSkillScanner` (runs a command with the skill path, parses JSON on stdout, accepts exit 0 or 1 as a completed scan, anything else is a failure), `HttpSkillScanner` (POSTs to a scanner service), `NoopSkillScanner` (dev only), plus `CompositeSkillScanner` and `RubricJudgeScanner`. `scripts/scan_skill.mjs` adapts the Skillspector engine: it walks the skill directory, skips symlinks, skips files over 30 MB (`MAX_FILE_BYTES`) with a stderr warning, prints the engine's report as JSON, and exits 0 or 1 on a completed scan and 2 on error. Findings are normalised into `ScanFinding` (rule id, severity, message, file, line).

## Consequences

### Positive

- Any scanner that emits the JSON shape can be plugged in without Python changes.
- Exit-code semantics separate 'found issues' from 'scanner broke' (the latter fails closed, ADR-0004).

### Negative

- The digest covers what the scanner skips (symlinks, oversize files), so a scanned report may not describe all hashed content (A-007).
- A subprocess timeout is not converted into a finding (A-010).
- Unknown severity strings collapse to `info` (A-011); merging zero reports yields an unusual score/grade (A-012, low confidence).

## Alternatives considered

- Importing the scanner as a library (not possible across Node/Python without a bridge; inferred, not stated).

## Evidence

- src/deepagent_skill_guardrails/scanner.py
- scripts/scan_skill.mjs
- src/deepagent_skill_guardrails/models.py (`ScanFinding`, `ScanReport`)
- tests/test_scanner.py
- commit 46003d3
