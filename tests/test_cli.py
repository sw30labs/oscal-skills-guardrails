from __future__ import annotations

import json
from pathlib import Path

from deepagent_skill_guardrails.cli import main

POLICY_YAML = """
version: 1
defaults:
  max_scan_severity: medium
agents:
  "*":
    allow_skills: ["*"]
skills:
  gated-skill:
    interrupt_at_severity: info
"""


def make_skill(root: Path, name: str, body: str = "Do things.") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: Use this skill for tests of the admission CLI.
---
# {name}

{body}
""",
        encoding="utf-8",
    )
    return skill_dir


def test_admit_allows_and_writes_artifacts(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    skills_root = tmp_path / "skills"
    make_skill(skills_root, "alpha")
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(POLICY_YAML, encoding="utf-8")
    lock = tmp_path / "skills.lock.json"
    results = tmp_path / "ar.json"

    code = main(
        [
            "admit",
            "--skills",
            str(skills_root),
            "--policy",
            str(policy_path),
            "--agent",
            "coding-agent",
            "--lock-out",
            str(lock),
            "--results",
            str(results),
        ]
    )
    assert code == 0
    assert lock.is_file() and results.is_file()

    ar = json.loads(results.read_text())
    obs = ar["assessment-results"]["results"][0]["observations"]
    assert any("alpha" in o["title"] for o in obs)

    out = capsys.readouterr().out
    assert "alpha" in out and "allow" in out


def test_admit_denies_bad_manifest_and_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    skills_root = tmp_path / "skills"
    make_skill(skills_root, "alpha")
    bad = skills_root / "Bad_Name"
    bad.mkdir()
    (bad / "SKILL.md").write_text(
        "---\nname: Bad_Name\ndescription: broken\n---\nbody\n", encoding="utf-8"
    )
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(POLICY_YAML, encoding="utf-8")

    code = main(["admit", "--skills", str(skills_root), "--policy", str(policy_path)])
    assert code == 1  # manifest rejection counts as a deny


def test_admit_interrupt_approval_loop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    skills_root = tmp_path / "skills"
    make_skill(skills_root, "gated-skill")
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(POLICY_YAML, encoding="utf-8")

    # NoopSkillScanner yields severity "none" < info, so use effect override instead:
    profile = {
        "profile": {
            "metadata": {"title": "t", "version": "0"},
            "modify": {
                "controls": [
                    {
                        "control-id": "sg-agt-wildcard",
                        "props": [
                            {"name": "osg:target-type", "value": "agent"},
                            {"name": "osg:target-id", "value": "*"},
                            {"name": "osg:allow-skill", "value": "*"},
                        ],
                    },
                    {
                        "control-id": "sg-skl-gated-skill",
                        "props": [
                            {"name": "osg:target-type", "value": "skill"},
                            {"name": "osg:target-id", "value": "gated-skill"},
                            {"name": "osg:effect", "value": "interrupt"},
                        ],
                    },
                ]
            },
        }
    }
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    unapproved = main(
        [
            "admit",
            "--skills",
            str(skills_root),
            "--oscal-profile",
            str(profile_path),
            "--fail-on",
            "interrupt",
        ]
    )
    assert unapproved == 1

    approved = main(
        [
            "admit",
            "--skills",
            str(skills_root),
            "--oscal-profile",
            str(profile_path),
            "--fail-on",
            "interrupt",
            "--approve",
            "gated-skill",
        ]
    )
    assert approved == 0


def test_verify_detects_drift(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    skills_root = tmp_path / "skills"
    skill_dir = make_skill(skills_root, "alpha")
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(POLICY_YAML, encoding="utf-8")
    lock = tmp_path / "skills.lock.json"

    assert (
        main(
            [
                "admit",
                "--skills",
                str(skills_root),
                "--policy",
                str(policy_path),
                "--lock-out",
                str(lock),
            ]
        )
        == 0
    )
    assert main(["verify", "--lock", str(lock), "--skills-root", str(skills_root)]) == 0

    (skill_dir / "SKILL.md").write_text("tampered", encoding="utf-8")
    assert main(["verify", "--lock", str(lock), "--skills-root", str(skills_root)]) == 1
