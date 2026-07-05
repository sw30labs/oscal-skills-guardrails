from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .models import ScanFinding, ScanReport, Severity


class SkillScanner(Protocol):
    def scan(self, skill_dir: Path) -> ScanReport:
        """Return a normalized scan report for one skill directory."""


@dataclass(frozen=True)
class NoopSkillScanner:
    """Dev-only scanner. Never use as the production admission gate."""

    scanner_name: str = "noop"

    def scan(self, skill_dir: Path) -> ScanReport:
        return ScanReport(scanner=self.scanner_name, target=str(skill_dir), findings=(), raw={})


@dataclass(frozen=True)
class SubprocessSkillScanner:
    """Adapter for a local scanner CLI/script that returns JSON on stdout.

    Example commands:
      ["uv", "run", "python", "/Users/spider/Code/REPOS/Skill Scanner/scripts/scan_skill.py"]
      ["skill-scanner", "scan", "--format", "json"]

    The skill directory path is appended as the final argument.
    """

    command: tuple[str, ...]
    timeout_seconds: int = 60
    scanner_name: str = "subprocess-skill-scanner"

    def scan(self, skill_dir: Path) -> ScanReport:
        skill_dir = skill_dir.resolve()
        if not skill_dir.exists():
            return ScanReport(
                scanner=self.scanner_name,
                target=str(skill_dir),
                findings=(
                    ScanFinding(
                        rule_id="SCANNER-TARGET-MISSING",
                        severity="critical",
                        category="scanner",
                        message=f"Skill directory does not exist: {skill_dir}",
                    ),
                ),
                raw={},
            )

        proc = subprocess.run(
            [*self.command, str(skill_dir)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.timeout_seconds,
        )
        if proc.returncode not in (0, 1):
            return ScanReport(
                scanner=self.scanner_name,
                target=str(skill_dir),
                findings=(
                    ScanFinding(
                        rule_id="SCANNER-EXECUTION-FAILED",
                        severity="critical",
                        category="scanner",
                        message=f"Scanner failed with exit code {proc.returncode}: {proc.stderr.strip()}",
                    ),
                ),
                raw={"stderr": proc.stderr, "stdout": proc.stdout, "returncode": proc.returncode},
            )

        try:
            raw = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError as exc:
            return ScanReport(
                scanner=self.scanner_name,
                target=str(skill_dir),
                findings=(
                    ScanFinding(
                        rule_id="SCANNER-INVALID-JSON",
                        severity="critical",
                        category="scanner",
                        message=f"Scanner did not return valid JSON: {exc}",
                    ),
                ),
                raw={"stderr": proc.stderr, "stdout": proc.stdout},
            )
        return normalize_scan_report(raw, target=str(skill_dir), scanner=self.scanner_name)


@dataclass(frozen=True)
class HttpSkillScanner:
    """Adapter for a scanner exposed as an internal HTTP API.

    Expected response: JSON containing either `findings` or a scanner-specific object
    that `normalize_scan_report` can best-effort normalize.
    """

    endpoint: str
    timeout_seconds: int = 60
    scanner_name: str = "http-skill-scanner"

    def scan(self, skill_dir: Path) -> ScanReport:
        payload = json.dumps({"path": str(skill_dir.resolve())}).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return ScanReport(
                scanner=self.scanner_name,
                target=str(skill_dir),
                findings=(
                    ScanFinding(
                        rule_id="SCANNER-HTTP-FAILED",
                        severity="critical",
                        category="scanner",
                        message=f"HTTP scanner failed: {exc}",
                    ),
                ),
                raw={},
            )
        return normalize_scan_report(raw, target=str(skill_dir), scanner=self.scanner_name)


_GRADE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}


@dataclass(frozen=True)
class CompositeSkillScanner:
    """Run several scanners over one skill and merge their evidence streams.

    Typical pairing: static analysis (Skillspector via SubprocessSkillScanner) plus the
    semantic RubricJudgeScanner. Merge semantics: findings are concatenated; `score`
    is the minimum reported; `grade` is the worst reported; a `rubric` section is
    surfaced top-level so policies (`require_rubric`) can see it; every scanner's full
    raw report is kept under raw["scanners"][<name>].
    """

    scanners: tuple[SkillScanner, ...]
    scanner_name: str = "composite"

    def scan(self, skill_dir: Path) -> ScanReport:
        findings: list[ScanFinding] = []
        raw: dict[str, Any] = {"scanners": {}}
        for scanner in self.scanners:
            report = scanner.scan(skill_dir)
            findings.extend(report.findings)
            raw["scanners"][report.scanner] = report.raw
            score = report.raw.get("score")
            if isinstance(score, (int, float)):
                raw["score"] = min(raw["score"], score) if "score" in raw else score
            grade = report.raw.get("grade")
            if isinstance(grade, str) and grade.upper() in _GRADE_RANK:
                current = raw.get("grade")
                if current is None or _GRADE_RANK[grade.upper()] < _GRADE_RANK.get(str(current).upper(), 5):
                    raw["grade"] = grade.upper()
            if "rubric" in report.raw:
                raw["rubric"] = report.raw["rubric"]
        return ScanReport(
            scanner=self.scanner_name,
            target=str(Path(skill_dir).resolve()),
            findings=tuple(findings),
            raw=raw,
        )


def normalize_scan_report(raw: dict[str, Any], *, target: str, scanner: str) -> ScanReport:
    """Normalize common JSON report shapes into ScanReport.

    This intentionally accepts loose scanner formats so you can plug in your local
    `/Users/spider/Code/REPOS/Skill Scanner` without changing the policy engine.
    """

    raw_findings = raw.get("findings") or raw.get("results") or raw.get("issues") or []
    if isinstance(raw_findings, dict):
        raw_findings = raw_findings.get("items", [])

    findings: list[ScanFinding] = []
    for idx, item in enumerate(raw_findings):
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or item.get("level") or "info").lower()
        if severity not in {"none", "info", "low", "medium", "high", "critical"}:
            severity = "info"
        findings.append(
            ScanFinding(
                rule_id=str(item.get("rule_id") or item.get("id") or item.get("rule") or f"FINDING-{idx+1}"),
                severity=severity,  # type: ignore[arg-type]
                category=str(item.get("category") or item.get("type") or "unspecified"),
                message=str(item.get("message") or item.get("issue") or item.get("title") or item),
                location=item.get("location") or item.get("path"),
                confidence=item.get("confidence"),
                remediation=item.get("remediation") or item.get("fix"),
                raw=item,
            )
        )

    # Some scanners only provide severity_counts with no detailed findings.
    counts = raw.get("severity_counts") or raw.get("summary", {}).get("severity_counts")
    if not findings and isinstance(counts, dict):
        for sev in ("critical", "high", "medium", "low", "info"):
            count = int(counts.get(sev, 0) or 0)
            if count:
                findings.append(
                    ScanFinding(
                        rule_id=f"SCANNER-{sev.upper()}-COUNT",
                        severity=sev,  # type: ignore[arg-type]
                        category="scanner-summary",
                        message=f"Scanner reported {count} {sev} finding(s), but did not include details.",
                        raw={"count": count},
                    )
                )
    return ScanReport(scanner=scanner, target=target, findings=tuple(findings), raw=raw)


def severity_from_string(value: str | None) -> Severity:
    value = (value or "none").lower()
    if value in {"none", "info", "low", "medium", "high", "critical"}:
        return value  # type: ignore[return-value]
    return "none"
