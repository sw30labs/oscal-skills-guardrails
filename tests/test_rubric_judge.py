from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from deepagent_skill_guardrails.models import AgentContext, ScanFinding, ScanReport, SkillManifest, SkillRecord
from deepagent_skill_guardrails.oscal_loader import compile_profile
from deepagent_skill_guardrails.policy import GuardrailPolicy
from deepagent_skill_guardrails.rubric_judge import (
    DEFAULT_SKILL_RUBRIC,
    RubricJudgeScanner,
    build_judge_prompt,
    extract_json_object,
)
from deepagent_skill_guardrails.scanner import CompositeSkillScanner


def make_skill(root: Path, name: str = "judged-skill") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use this skill for tests.\n---\n# {name}\n",
        encoding="utf-8",
    )
    return skill_dir


def verdict_json(fails: dict[str, str] | None = None, unclear: set[str] = frozenset()) -> str:
    fails = fails or {}
    criteria = []
    for c in DEFAULT_SKILL_RUBRIC:
        if c.id in fails:
            criteria.append(
                {"id": c.id, "verdict": "fail", "evidence": "SKILL.md", "explanation": fails[c.id]}
            )
        elif c.id in unclear:
            criteria.append({"id": c.id, "verdict": "unclear", "evidence": "", "explanation": "?"})
        else:
            criteria.append({"id": c.id, "verdict": "pass", "evidence": "", "explanation": "ok"})
    overall = "fail" if fails else "pass"
    return json.dumps({"criteria": criteria, "overall": overall, "summary": "test"})


def test_pass_all_yields_no_blocking_findings(tmp_path: Path) -> None:
    skill_dir = make_skill(tmp_path)
    scanner = RubricJudgeScanner(judge=lambda prompt: verdict_json())
    report = scanner.scan(skill_dir)
    assert report.max_severity == "none"
    assert report.raw["rubric"]["overall"] == "pass"
    assert len(report.raw["rubric"]["criteria"]) == len(DEFAULT_SKILL_RUBRIC)


def test_fail_r4_is_critical_and_denied_by_policy(tmp_path: Path) -> None:
    skill_dir = make_skill(tmp_path)
    scanner = RubricJudgeScanner(
        judge=lambda prompt: verdict_json({"R4": "sends ~/.aws to webhook"})
    )
    report = scanner.scan(skill_dir)
    assert report.max_severity == "critical"
    finding = next(f for f in report.findings if f.rule_id == "RUB-R4")
    assert finding.category == "rubric"

    policy = GuardrailPolicy({"agents": {"*": {"allow_skills": ["*"], "max_scan_severity": "medium"}}})
    record = SkillRecord(
        manifest=SkillManifest(name="judged-skill", description="d", path=skill_dir),
        digest="x",
        scan=report,
    )
    decision = policy.check_skill(AgentContext(agent_id="a"), record)
    assert decision.effect == "deny"
    assert "exceeds" in decision.reason


def test_unclear_and_missing_are_info_only(tmp_path: Path) -> None:
    skill_dir = make_skill(tmp_path)

    def judge(prompt: str) -> str:
        # omit R7 entirely, mark R2 unclear
        doc = json.loads(verdict_json(unclear={"R2"}))
        doc["criteria"] = [c for c in doc["criteria"] if c["id"] != "R7"]
        return json.dumps(doc)

    report = RubricJudgeScanner(judge=judge).scan(skill_dir)
    assert report.max_severity == "info"
    by_rule = {f.rule_id: f for f in report.findings}
    assert by_rule["RUB-R2"].severity == "info"
    assert by_rule["RUB-R7"].severity == "info"
    criteria = {c["id"]: c for c in report.raw["rubric"]["criteria"]}
    assert criteria["R7"]["verdict"] == "missing"


def test_judge_error_fails_closed(tmp_path: Path) -> None:
    skill_dir = make_skill(tmp_path)

    def broken(prompt: str) -> str:
        return "I refuse to answer in JSON."

    report = RubricJudgeScanner(judge=broken).scan(skill_dir)
    assert report.max_severity == "critical"
    assert report.findings[0].rule_id == "RUB-JUDGE-ERROR"
    assert "error" in report.raw["rubric"]


def test_prompt_wraps_content_and_extractor_tolerates_prose() -> None:
    prompt = build_judge_prompt("SOME CONTENT")
    assert "<<<SKILL_CONTENT_BEGIN>>>" in prompt and "UNTRUSTED DATA" in prompt
    extracted = extract_json_object('Sure! Here is the verdict:\n```json\n{"a": {"b": 1}}\n``` done')
    assert extracted == {"a": {"b": 1}}


@dataclass(frozen=True)
class FakeStaticScanner:
    scanner_name: str = "fake-skillspector"

    def scan(self, skill_dir: Path) -> ScanReport:
        return ScanReport(
            scanner=self.scanner_name,
            target=str(skill_dir),
            findings=(
                ScanFinding(rule_id="SEC-010", severity="medium", category="security", message="m"),
            ),
            raw={"score": 93, "grade": "A"},
        )


def test_composite_merges_streams(tmp_path: Path) -> None:
    skill_dir = make_skill(tmp_path)
    composite = CompositeSkillScanner(
        scanners=(
            FakeStaticScanner(),
            RubricJudgeScanner(judge=lambda p: verdict_json({"R2": "scope creep"})),
        )
    )
    report = composite.scan(skill_dir)
    rule_ids = {f.rule_id for f in report.findings}
    assert "SEC-010" in rule_ids and "RUB-R2" in rule_ids
    assert report.raw["score"] == 93 and report.raw["grade"] == "A"
    assert report.raw["rubric"]["overall"] == "fail"
    assert "fake-skillspector" in report.raw["scanners"]
    assert report.max_severity == "medium"  # R2 fail is medium; SEC-010 medium


def test_require_rubric_fails_closed_and_oscal_prop() -> None:
    policy_dict = compile_profile(
        {
            "profile": {
                "metadata": {},
                "modify": {
                    "controls": [
                        {
                            "control-id": "sg-agt-wildcard",
                            "props": [
                                {"name": "osg:target-type", "value": "agent"},
                                {"name": "osg:target-id", "value": "*"},
                                {"name": "osg:allow-skill", "value": "*"},
                                {"name": "osg:require-rubric", "value": "true"},
                            ],
                        }
                    ]
                },
            }
        }
    )
    assert policy_dict["agents"]["*"]["require_rubric"] is True
    policy = GuardrailPolicy(policy_dict)
    ctx = AgentContext(agent_id="anything")

    def record(raw: dict) -> SkillRecord:
        return SkillRecord(
            manifest=SkillManifest(name="s", description="d", path=Path("/tmp/s")),
            digest="x",
            scan=ScanReport(scanner="t", target="s", findings=(), raw=raw),
        )

    denied = policy.check_skill(ctx, record({"score": 100}))
    assert denied.effect == "deny"
    assert "rubric" in denied.reason
    allowed = policy.check_skill(ctx, record({"score": 100, "rubric": {"overall": "pass"}}))
    assert allowed.allowed
