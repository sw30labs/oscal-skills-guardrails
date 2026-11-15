# ADR-0014: Minimal core dependency (PyYAML) with optional extras for DeepAgents, MCP and the LangChain judge; Apache-2.0

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

`__init__.py`: "This package intentionally keeps DeepAgents and MCP imports optional so policy/registry unit tests can run without agent runtime dependencies installed." The initial commit f5a4bcc added an Apache-2.0 LICENSE; the README badge says Apache-2.0.

## Decision

`pyproject.toml` (`deepagent-skill-guardrails` 0.1.0, Python >= 3.10) depends only on `pyyaml>=6.0.1`. Extras: `deepagents` (`deepagents>=0.7.13`, `langchain-mcp-adapters>=0.1.0`), `mcp` (`mcp>=1.27,<2`), `judge` (`langchain>=1.0`), `dev` (pytest, ruff). Optional imports are made inside functions and raise a `RuntimeError` naming the missing package. Console script `skill-guardrails`. Tests that need deepagents use `importorskip`.

## Consequences

### Positive

- Policy, registry, scanner and CLI work in a plain Python environment, including CI.
- Clear errors when an optional feature is used without its extra.

### Negative

- There is no `[build-system]` table, so builds rely on the setuptools legacy default (A-021).
- Deepagents-dependent tests are skipped when the extra is not installed, so behaviour against real deepagents is not always exercised (A-016).

## Alternatives considered

- Hard dependency on deepagents/langchain (rejected by the `__init__` docstring).

## Evidence

- pyproject.toml
- src/deepagent_skill_guardrails/__init__.py
- LICENSE
- commits f5a4bcc, 46003d3, d9094e4
