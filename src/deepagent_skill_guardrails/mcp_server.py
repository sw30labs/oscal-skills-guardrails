from __future__ import annotations

from pathlib import Path
from typing import Any

from .registry import parse_skill_manifest
from .scanner import SubprocessSkillScanner


def build_skill_scanner_mcp(command: tuple[str, ...]):
    """Expose your local Skill Scanner as an MCP server.

    Keep this MCP server in an admin/CI profile, not in every production agent.
    Agents that can install or activate skills should not automatically be allowed
    to self-certify those skills.
    """

    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install mcp>=1.27,<2 to run the scanner MCP server") from exc

    scanner = SubprocessSkillScanner(command=command)
    mcp = FastMCP("Skill Scanner Guardrail")

    @mcp.tool()
    def scan_skill(skill_dir: str) -> dict[str, Any]:
        """Scan an Agent Skill directory and return normalized findings."""

        report = scanner.scan(Path(skill_dir))
        return {
            "scanner": report.scanner,
            "target": report.target,
            "max_severity": report.max_severity,
            "finding_count": report.finding_count,
            "findings": [
                {
                    "rule_id": f.rule_id,
                    "severity": f.severity,
                    "category": f.category,
                    "message": f.message,
                    "location": f.location,
                    "confidence": f.confidence,
                    "remediation": f.remediation,
                }
                for f in report.findings
            ],
        }

    @mcp.tool()
    def inspect_skill_manifest(skill_dir: str) -> dict[str, Any]:
        """Parse SKILL.md frontmatter and return name, description, and declared tools."""

        manifest = parse_skill_manifest(Path(skill_dir))
        return {
            "name": manifest.name,
            "description": manifest.description,
            "path": str(manifest.path),
            "allowed_tools": list(manifest.allowed_tools),
            "metadata": manifest.metadata,
            "compatibility": manifest.compatibility,
        }

    return mcp


if __name__ == "__main__":
    # Example:
    #   SKILL_SCANNER_CMD='uv run python /Users/spider/Code/REPOS/Skill Scanner/scripts/scan_skill.py' \
    #   python -m deepagent_skill_guardrails.mcp_server
    import os
    import shlex

    cmd = tuple(shlex.split(os.environ.get("SKILL_SCANNER_CMD", "")))
    if not cmd:
        raise SystemExit("Set SKILL_SCANNER_CMD to your scanner command without the target path")
    build_skill_scanner_mcp(cmd).run(transport=os.environ.get("MCP_TRANSPORT", "stdio"))
