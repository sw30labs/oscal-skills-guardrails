# ADR-0016: Strict SKILL.md manifest gate, with flat top-level keys merged into metadata for Skillspector compatibility

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

Skills must be identified reliably before anything is scanned or admitted. The manifest code notes that flat frontmatter keeps files "compatible with Skillspector's YAML-lite frontmatter parser" while still supporting `required_metadata` (SG-7).

## Decision

`load_skill_manifest` requires `SKILL.md` to begin with YAML frontmatter, requires `name` and `description`, enforces the name pattern `^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$` with no `--`, and requires the name to equal the directory name. `allowed-tools` / `allowed_tools` accepts a whitespace/comma string or a list. Unknown top-level keys (anything other than name, description, license, compatibility, allowed-tools, metadata, module) are merged into `metadata` if not already present. Manifest errors are fatal for that skill (the CLI reports a deny row). `SkillRegistry` keys records by skill name.

## Consequences

### Positive

- Names are safe identifiers and match on-disk layout, so allow/deny globs are predictable.
- SG-7 provenance checks work on flat files that Skillspector also parses.

### Negative

- Two skill directories with the same name in different roots overwrite each other in the registry (A-022).
- Merging arbitrary top-level keys means a typo'd key silently becomes metadata.

## Alternatives considered

- Requiring a nested `metadata:` block only (not chosen, because of the Skillspector parser compatibility note).

## Evidence

- src/deepagent_skill_guardrails/registry.py (`_FRONTMATTER_RE`, `_NAME_RE`, `load_skill_manifest`, `SkillRegistry`)
- examples/skills/*/SKILL.md
- ROADMAP.md (Skillspector upstream, QUA-002)
- tests/test_registry.py
