from __future__ import annotations

from pathlib import Path

import pytest

from deepagent_skill_guardrails.middleware import verify_registry_digests
from deepagent_skill_guardrails.models import SkillIntegrityError
from deepagent_skill_guardrails.registry import SkillRegistry, verify_digest_lock
from deepagent_skill_guardrails.scanner import NoopSkillScanner


def make_skill(root: Path, name: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: Use this skill for tests.
---
# {name}
""",
        encoding="utf-8",
    )
    return skill_dir


def test_verify_detects_tampering(tmp_path: Path) -> None:
    skill_dir = make_skill(tmp_path, "clean-one")
    registry = SkillRegistry(scanner=NoopSkillScanner())
    registry.ingest(skill_dir)

    ok, _ = registry.verify("clean-one")
    assert ok

    (skill_dir / "payload.py").write_text("import os\n", encoding="utf-8")
    ok, current = registry.verify("clean-one")
    assert not ok
    assert current != registry.records["clean-one"].digest


def test_verify_registry_digests_raises_and_audits(tmp_path: Path) -> None:
    skill_dir = make_skill(tmp_path, "clean-one")
    registry = SkillRegistry(scanner=NoopSkillScanner())
    registry.ingest(skill_dir)

    events: list[dict] = []
    verify_registry_digests(registry, audit_sink=events.append)  # no-op while intact
    assert events == []

    (skill_dir / "SKILL.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(SkillIntegrityError) as exc:
        verify_registry_digests(registry, agent_id="runner", audit_sink=events.append)
    assert exc.value.skill_id == "clean-one"
    assert events and events[0]["kind"] == "integrity_violation"
    assert events[0]["matched"] == ["skill.digest_mismatch"]


def test_digest_lock_relative_paths_portable(tmp_path: Path) -> None:
    import json

    skills_root = tmp_path / "skills"
    make_skill(skills_root, "alpha")
    registry = SkillRegistry(scanner=NoopSkillScanner())
    registry.ingest_many(registry.discover(skills_root))

    lock = registry.save_digest_lock(tmp_path / "skills.lock.json", relative_to=skills_root)
    data = json.loads(lock.read_text())
    assert data["skills"]["alpha"]["path"] == "alpha"  # no machine-specific prefix

    statuses = verify_digest_lock(lock, skills_root=skills_root)
    assert statuses["alpha"]["status"] == "ok"


def test_digest_lock_roundtrip_and_drift(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    make_skill(skills_root, "alpha")
    make_skill(skills_root, "beta")
    registry = SkillRegistry(scanner=NoopSkillScanner())
    registry.ingest_many(registry.discover(skills_root))

    lock_path = registry.save_digest_lock(tmp_path / "skills.lock.json")

    statuses = verify_digest_lock(lock_path)
    assert {s["status"] for s in statuses.values()} == {"ok"}

    # tamper alpha, delete beta, add gamma
    (skills_root / "alpha" / "SKILL.md").write_text("changed", encoding="utf-8")
    (skills_root / "beta" / "SKILL.md").unlink()
    (skills_root / "beta").rmdir()
    make_skill(skills_root, "gamma")

    statuses = verify_digest_lock(lock_path, skills_root=skills_root)
    assert statuses["alpha"]["status"] == "changed"
    assert statuses["beta"]["status"] == "missing"
    assert statuses["gamma"]["status"] == "new"
