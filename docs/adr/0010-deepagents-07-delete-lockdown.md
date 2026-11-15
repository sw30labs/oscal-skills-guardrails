# ADR-0010: For deepagents 0.7+, auto-deny write on `/**` unless delete is explicitly allowed, and default the main agent to read-only filesystem tools

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

CHANGELOG (commit d9094e4): "deepagents 0.7 classifies recursive `delete` as a write operation, so prior write-allow rules could authorize subtree deletion." The README repeats this under "deepagents 0.7+ filesystem delete lockdown".

## Decision

`GuardrailPolicy.deepagents_filesystem_permissions()` materialises policy `filesystem_permissions` as deepagents `FilesystemPermission`s and always appends `FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")` unless a rule explicitly allows delete (`operations` containing `delete` with `mode: allow`). `create_guarded_deep_agent` also appends a `FilesystemMiddleware(tools=["ls","read_file","glob","grep"])` when deepagents supports `tools=` and the caller has not supplied a FilesystemMiddleware; on older deepagents it returns None and only the permission hardening applies. The optional extra was raised to `deepagents>=0.7.13`. Agents that need write or edit must pass their own `FilesystemMiddleware` via `extra_middleware`.

## Consequences

### Positive

- Recursive deletes fail closed by default after the upstream semantic change.
- Read-only is the default tool surface for the main agent.

### Negative

- A write-allow in policy (for example the coding-agent's `/workspace/**` example) is effectively neutralised unless delete is also explicitly allowed or the caller supplies its own FilesystemMiddleware (A-006, inferred intent).
- Correctness depends on deepagents evaluating the appended deny alongside earlier allows the way the comments assume (A-005, unverified).
- The read-biased middleware is not applied to subagents (A-014).

## Alternatives considered

- Leaving delete governed by existing write rules (rejected in the CHANGELOG as the vulnerability being fixed).
- Adding a separate delete operation (not possible: the code notes `FilesystemOperation` is only read|write).

## Evidence

- src/deepagent_skill_guardrails/policy.py (`deepagents_filesystem_permissions`, `_has_explicit_delete_allow`)
- src/deepagent_skill_guardrails/deepagents_factory.py (`_maybe_read_biased_filesystem_middleware`, `_AUDITOR_FS_TOOLS`)
- pyproject.toml (`deepagents>=0.7.13`)
- CHANGELOG.md; README.md
- tests/test_filesystem_permissions.py
- commit d9094e4
