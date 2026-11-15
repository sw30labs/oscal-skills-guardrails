# ADR-0006: Skill integrity by SHA-256 content digest: committed lockfile for CI, re-verification before and during agent runs

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

SG-2 states the threat: "re-verified before skill content is loaded at runtime, preventing time-of-check to time-of-use substitution of scanned skill content". The README calls the lockfile "exactly like a dependency lockfile, but for agent capabilities" and says the lockfile diff "is the review signal".

## Decision

`digest_directory` hashes every file under the skill directory in sorted relative-path order (path, NUL, bytes, NUL). `SkillRegistry.ingest` records manifest, digest and scan; `verify` / `verify_all` recompute; `save_digest_lock(relative_to=...)` writes portable relative paths (added in 6c5f563 so the committed `skills.lock.json` verifies on CI checkouts); `verify_digest_lock(skills_root=...)` reports `ok`, `changed`, `missing`, or `new`. `cli verify` fails on changed, missing and (unless `--allow-new`) new skills. `create_guarded_deep_agent(verify_digests=True)` re-verifies before computing skill paths (`on_digest_mismatch="deny"` drops the skill; `"rescan"` re-ingests and re-adjudicates) and installs a `before_agent` / `abefore_agent` middleware that raises `SkillIntegrityError` if any admitted skill changes between invocations.

## Consequences

### Positive

- Tampering after admission is caught both across processes (lockfile) and inside a running session (middleware).
- Lockfile changes are reviewable in a PR diff.

### Negative

- The digest follows symlinks while `scan_skill.mjs` skips them, so the two views of a skill can diverge (A-007; listed in ROADMAP).
- The runtime digest middleware is on the main agent only; subagents do not get it (A-014; listed in ROADMAP).
- `--skills-root` verification resolves locked entries by directory basename, so nested skills sharing a basename would collide (A-019).

## Alternatives considered

- Trusting scan results without re-hashing (rejected: that is the TOCTOU gap SG-2 exists for).
- Signed attestations (ROADMAP 'Signed admissions', not yet built).

## Evidence

- src/deepagent_skill_guardrails/registry.py (`digest_directory`, `verify`, `save_digest_lock`, `verify_digest_lock`)
- src/deepagent_skill_guardrails/middleware.py (`verify_registry_digests`, `make_digest_verification_middleware`)
- src/deepagent_skill_guardrails/deepagents_factory.py (SG-2 block)
- src/deepagent_skill_guardrails/cli.py (`cmd_verify`)
- skills.lock.json
- tests/test_digest_verification.py; tests/test_cli.py (`test_verify_detects_drift`)
- commits 46003d3, 6c5f563
