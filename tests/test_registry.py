from __future__ import annotations

from pathlib import Path

from deepagent_skill_guardrails.registry import SkillRegistry, parse_skill_manifest
from deepagent_skill_guardrails.scanner import NoopSkillScanner


def make_skill(root: Path, name: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: Use this skill for tests.
allowed-tools: read_file grep
metadata:
  owner: governance
---
# {name}

Do test things.
""",
        encoding="utf-8",
    )
    return skill_dir


def test_parse_skill_manifest(tmp_path: Path) -> None:
    skill_dir = make_skill(tmp_path, "langgraph-docs")
    manifest = parse_skill_manifest(skill_dir)
    assert manifest.name == "langgraph-docs"
    assert manifest.allowed_tools == ("read_file", "grep")
    assert manifest.metadata["owner"] == "governance"


def test_registry_discovers_and_ingests(tmp_path: Path) -> None:
    make_skill(tmp_path, "langgraph-docs")
    registry = SkillRegistry(scanner=NoopSkillScanner())
    discovered = registry.discover(tmp_path)
    registry.ingest_many(discovered)
    assert "langgraph-docs" in registry.records
    assert registry.records["langgraph-docs"].scan.max_severity == "none"
