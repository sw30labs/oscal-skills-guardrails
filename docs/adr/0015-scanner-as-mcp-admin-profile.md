# ADR-0015: Expose the scanner as an MCP server, but only in an admin/CI profile

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

`build_skill_scanner_mcp` docstring: "Keep this MCP server in an admin/CI profile, not in every production agent." ROADMAP's "Pre-install gate for skill marketplaces" proposes exposing `admit` through the existing MCP server.

## Decision

`mcp_server.py` builds a FastMCP server ("Skill Scanner Guardrail") with two tools: one scans a skill directory and returns summary fields (including `max_severity`), and one parses `SKILL.md` frontmatter and returns name, description and declared tools. It runs over `MCP_TRANSPORT` (default stdio) and requires the `mcp` extra. The example policy denies `mcp__dangerous__*` tool patterns.

## Consequences

### Positive

- Scanner capability is reusable by agents and tools that speak MCP.
- Keeping it out of production agents avoids giving runtime agents a scanner they could probe.

### Negative

- Why the admin-only restriction is wanted is not explained beyond the docstring; treated here as stated intent.
- Fallback scanner command paths in the MCP entrypoint and CLI are hardcoded to a local Mac path (A-020).

## Alternatives considered

- Exposing `admit` itself over MCP (ROADMAP item, not built).

## Evidence

- src/deepagent_skill_guardrails/mcp_server.py
- ROADMAP.md
- examples/policy.yaml (`mcp__dangerous__*`)
- pyproject.toml (`mcp` extra)
