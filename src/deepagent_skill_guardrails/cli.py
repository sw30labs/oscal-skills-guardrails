"""Admission CLI — run the skill guardrail gate from a terminal or CI.

Commands:
  scan    Scan one skill directory, print the normalized report.
  admit   Discover + scan + adjudicate all skills for one or more agents.
          Optionally writes a digest lockfile (SG-2) and an OSCAL
          assessment-results document (SG-8). Non-zero exit gates CI.
  verify  Compare a digest lockfile against the current tree (SG-2 drift check).

Examples:
  skill-guardrails scan ./skills/my-skill --scanner-cmd 'node scripts/scan_skill.mjs'
  skill-guardrails admit --skills ./examples/skills \
      --oscal-profile data/oscal-policies/skills-policy-profile.json \
      --agent supervisor --agent coding-agent \
      --scanner-cmd 'node scripts/scan_skill.mjs' \
      --lock-out out/skills.lock.json --results out/assessment-results.json
  skill-guardrails verify --lock out/skills.lock.json --skills-root ./examples/skills

Exit codes: 0 = gate passed, 1 = gate failed (denials / drift), 2 = usage or runtime error.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

from .deepagents_factory import skill_decision_event
from .models import AgentContext
from .oscal_loader import load_skills_policy_profile
from .oscal_results import OscalAssessmentSink
from .policy import GuardrailPolicy
from .registry import SkillRegistry, verify_digest_lock
from .scanner import NoopSkillScanner, SubprocessSkillScanner


def _err(message: str) -> int:
    print(f"skill-guardrails: {message}", file=sys.stderr)
    return 2


def _build_scanner(
    scanner_cmd: str | None,
    *,
    rubric_judge_cmd: str | None = None,
    rubric_judge_url: str | None = None,
    rubric_judge_model: str | None = None,
    rubric_judge_api_key: str | None = None,
    quiet: bool = False,
):
    if scanner_cmd:
        base = SubprocessSkillScanner(command=tuple(shlex.split(scanner_cmd)))
    else:
        default = Path("scripts/scan_skill.mjs")
        if default.is_file():
            base = SubprocessSkillScanner(command=("node", str(default)))
        else:
            if not quiet:
                print(
                    "skill-guardrails: warning: no --scanner-cmd and scripts/scan_skill.mjs not "
                    "found; using NoopSkillScanner (dev only — score/grade policies fail closed)",
                    file=sys.stderr,
                )
            base = NoopSkillScanner()

    if rubric_judge_cmd and (rubric_judge_url or rubric_judge_model):
        raise ValueError("use either --rubric-judge-cmd or --rubric-judge-url/--rubric-judge-model, not both")

    # Set-and-forget: with no judge flags, fall back to $SKILL_JUDGE_MODEL / $OMLX_MODEL
    # so scheduled/CI runs get the semantic stream without extra arguments.
    if not rubric_judge_cmd and not rubric_judge_model:
        rubric_judge_model = os.environ.get("SKILL_JUDGE_MODEL") or os.environ.get("OMLX_MODEL")

    judge = None
    judge_name = None
    if rubric_judge_cmd:
        from .rubric_judge import command_judge

        judge = command_judge(tuple(shlex.split(rubric_judge_cmd)))
        judge_name = rubric_judge_cmd.split()[0]
    elif rubric_judge_model or rubric_judge_url:
        if not rubric_judge_model:
            raise ValueError("--rubric-judge-url requires --rubric-judge-model")
        from .rubric_judge import OMLX_DEFAULT_BASE_URL, openai_chat_judge

        url = rubric_judge_url or os.environ.get("OMLX_BASE_URL", OMLX_DEFAULT_BASE_URL)
        key = (
            rubric_judge_api_key
            or os.environ.get("SKILL_JUDGE_API_KEY")
            or os.environ.get("OMLX_API_KEY")
        )
        judge = openai_chat_judge(url, rubric_judge_model, api_key=key)
        judge_name = f"{rubric_judge_model}@{url}"

    if judge:
        from .rubric_judge import RubricJudgeScanner
        from .scanner import CompositeSkillScanner

        judge_scanner = RubricJudgeScanner(judge=judge, judge_name=judge_name or "judge")
        return CompositeSkillScanner(scanners=(base, judge_scanner))
    return base


def _load_policy(args) -> GuardrailPolicy | None:
    if getattr(args, "oscal_profile", None):
        return load_skills_policy_profile(args.oscal_profile)
    if getattr(args, "policy", None):
        return GuardrailPolicy.from_yaml(args.policy)
    return None


def _scanner_from_args(args):
    return _build_scanner(
        args.scanner_cmd,
        rubric_judge_cmd=args.rubric_judge_cmd,
        rubric_judge_url=args.rubric_judge_url,
        rubric_judge_model=args.rubric_judge_model,
        rubric_judge_api_key=args.rubric_judge_api_key,
    )


def cmd_scan(args) -> int:
    scanner = _scanner_from_args(args)
    report = scanner.scan(Path(args.skill_dir))
    if args.json:
        print(json.dumps(report.raw or {"findings": []}, indent=2))
    else:
        score = report.raw.get("score")
        grade = report.raw.get("grade")
        print(f"target        : {report.target}")
        print(f"scanner       : {report.scanner}")
        print(f"max severity  : {report.max_severity}")
        print(f"score / grade : {score} / {grade}" if score is not None else "score / grade : n/a")
        print(f"findings      : {report.finding_count}")
        for f in report.findings:
            print(f"  {f.rule_id:<10} [{f.severity:<8}] {f.location or '-'}  {f.message[:90]}")
    from .models import SEVERITY_ORDER

    return 1 if SEVERITY_ORDER.get(report.max_severity, 0) >= SEVERITY_ORDER["high"] else 0


def cmd_admit(args) -> int:
    policy = _load_policy(args)
    if policy is None:
        return _err("admit requires --policy <yaml> or --oscal-profile <json>")

    skills_root = Path(args.skills)
    if not skills_root.is_dir():
        return _err(f"skills root not found: {skills_root}")

    scanner = _scanner_from_args(args)
    registry = SkillRegistry(scanner=scanner)

    rejected_at_manifest: list[tuple[str, str]] = []
    for skill_dir in registry.discover(skills_root):
        try:
            registry.ingest(skill_dir)
        except Exception as exc:  # noqa: BLE001 - manifest gate must not crash the run
            rejected_at_manifest.append((skill_dir.name, str(exc)))

    sink = OscalAssessmentSink(
        profile_href=str(args.oscal_profile or args.policy),
        title="Skill guardrails admission run",
    )
    approved = set(args.approve or [])
    agents = args.agent or ["default"]

    rows: list[dict] = []
    for agent_id in agents:
        ctx = AgentContext(agent_id=agent_id)
        for record in registry.records.values():
            decision = policy.check_skill(ctx, record)
            event = skill_decision_event(ctx, record, decision)
            effect = decision.effect
            if decision.interrupted and record.skill_id in approved:
                effect = "allow"
                event["effect"] = "allow"
                event["reason"] = f"human-approved: {decision.reason}"
                event["obligations"] = ["approval_recorded"]
            sink(event)
            rows.append(
                {
                    "agent": agent_id,
                    "skill": record.skill_id,
                    "severity": record.scan.max_severity,
                    "score": record.scan.raw.get("score"),
                    "grade": record.scan.raw.get("grade"),
                    "effect": effect,
                    "reason": event["reason"],
                }
            )

    for name, reason in rejected_at_manifest:
        sink(
            {
                "kind": "skill_decision",
                "agent_id": "-",
                "skill_id": name,
                "effect": "deny",
                "reason": f"manifest rejected: {reason}",
                "matched": ["skill.manifest"],
                "obligations": [],
            }
        )
        rows.append(
            {
                "agent": "-",
                "skill": name,
                "severity": "-",
                "score": None,
                "grade": None,
                "effect": "deny",
                "reason": f"manifest rejected: {reason}",
            }
        )

    if args.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        header = f"{'AGENT':<14} {'SKILL':<24} {'SEV':<9} {'SCORE':<6} {'GRD':<4} {'EFFECT':<10} REASON"
        print(header)
        print("-" * len(header))
        for r in rows:
            score = "-" if r["score"] is None else str(r["score"])
            grade = r["grade"] or "-"
            print(
                f"{r['agent']:<14} {r['skill']:<24} {r['severity']:<9} {score:<6} {grade:<4} "
                f"{r['effect']:<10} {str(r['reason'])[:70]}"
            )
        counts = sink.counts
        print(
            f"\n{len(registry.records)} skill(s) scanned, {len(rejected_at_manifest)} manifest "
            f"rejection(s) | allow={counts.get('allow', 0)} deny={counts.get('deny', 0)} "
            f"interrupt={counts.get('interrupt', 0)}"
        )

    if args.lock_out:
        registry.save_digest_lock(args.lock_out)
        print(f"digest lock written: {args.lock_out}", file=sys.stderr)
    if args.results:
        sink.write(args.results)
        print(f"OSCAL assessment-results written: {args.results}", file=sys.stderr)

    denies = sum(1 for r in rows if r["effect"] == "deny")
    interrupts = sum(1 for r in rows if r["effect"] == "interrupt")
    if args.fail_on == "never":
        return 0
    if args.fail_on == "interrupt":
        return 1 if (denies or interrupts) else 0
    return 1 if denies else 0  # fail_on == "deny"


def cmd_verify(args) -> int:
    lock = Path(args.lock)
    if not lock.is_file():
        return _err(f"lockfile not found: {lock}")
    skills_root = Path(args.skills_root) if args.skills_root else None
    statuses = verify_digest_lock(lock, skills_root=skills_root)

    if args.json:
        print(json.dumps(statuses, indent=2))
    else:
        for skill_id, info in sorted(statuses.items()):
            print(f"{info['status']:<8} {skill_id}")

    bad = {"changed", "missing"} | (set() if args.allow_new else {"new"})
    failures = [s for s, info in statuses.items() if info["status"] in bad]
    if failures:
        print(f"integrity drift detected: {', '.join(sorted(failures))}", file=sys.stderr)
        return 1
    return 0


def _add_judge_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--rubric-judge-cmd",
        default=None,
        help="LLM judge command (prompt on stdin, JSON on stdout), e.g. 'claude -p'",
    )
    parser.add_argument(
        "--rubric-judge-url",
        default=None,
        help="OpenAI-compatible API root for the judge (default $OMLX_BASE_URL or http://127.0.0.1:8000/v1 — oMLX)",
    )
    parser.add_argument(
        "--rubric-judge-model",
        default=None,
        help="model id for --rubric-judge-url (implies oMLX default URL if URL omitted)",
    )
    parser.add_argument(
        "--rubric-judge-api-key",
        default=None,
        help="bearer token for the judge endpoint (default $SKILL_JUDGE_API_KEY or $OMLX_API_KEY)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skill-guardrails", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="scan one skill directory")
    p_scan.add_argument("skill_dir")
    p_scan.add_argument("--scanner-cmd", default=None)
    _add_judge_args(p_scan)
    p_scan.add_argument("--json", action="store_true")
    p_scan.set_defaults(func=cmd_scan)

    p_admit = sub.add_parser("admit", help="scan + adjudicate all skills under a root")
    p_admit.add_argument("--skills", required=True, help="root directory containing skill folders")
    p_admit.add_argument("--policy", default=None, help="YAML policy path")
    p_admit.add_argument("--oscal-profile", default=None, help="OSCAL profile JSON path")
    p_admit.add_argument("--agent", action="append", default=None, help="agent id (repeatable)")
    p_admit.add_argument("--approve", action="append", default=None, help="approved skill id (repeatable)")
    p_admit.add_argument("--scanner-cmd", default=None)
    _add_judge_args(p_admit)
    p_admit.add_argument("--lock-out", default=None, help="write digest lockfile (SG-2)")
    p_admit.add_argument("--results", default=None, help="write OSCAL assessment-results (SG-8)")
    p_admit.add_argument("--fail-on", choices=["deny", "interrupt", "never"], default="deny")
    p_admit.add_argument("--json", action="store_true")
    p_admit.set_defaults(func=cmd_admit)

    p_verify = sub.add_parser("verify", help="verify a digest lockfile against the tree")
    p_verify.add_argument("--lock", required=True)
    p_verify.add_argument("--skills-root", default=None)
    p_verify.add_argument("--allow-new", action="store_true", help="do not fail on un-locked new skills")
    p_verify.add_argument("--json", action="store_true")
    p_verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        return _err(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
