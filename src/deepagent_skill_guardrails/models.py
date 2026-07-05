from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Severity = Literal["none", "info", "low", "medium", "high", "critical"]
DecisionEffect = Literal["allow", "deny", "interrupt"]

SEVERITY_ORDER: dict[str, int] = {
    "none": 0,
    "info": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "critical": 5,
}


class SkillIntegrityError(RuntimeError):
    """Raised when a skill's content digest no longer matches its admitted digest (SG-2).

    This is a fail-closed signal: the scanned content and the loadable content have
    diverged (TOCTOU), so the run must not proceed with that skill.
    """

    def __init__(self, skill_id: str, expected: str, actual: str):
        self.skill_id = skill_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"skill {skill_id!r} content digest changed since admission "
            f"(expected {expected[:12]}…, got {actual[:12]}…); re-scan required"
        )


@dataclass(frozen=True)
class AgentContext:
    """Identity and request metadata used to make policy decisions."""

    agent_id: str
    org_id: str | None = None
    user_id: str | None = None
    roles: tuple[str, ...] = ()
    tenant_id: str | None = None
    run_id: str | None = None
    tags: tuple[str, ...] = ()

    def for_agent(self, agent_id: str) -> "AgentContext":
        return AgentContext(
            agent_id=agent_id,
            org_id=self.org_id,
            user_id=self.user_id,
            roles=self.roles,
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            tags=self.tags,
        )


@dataclass(frozen=True)
class Decision:
    effect: DecisionEffect
    reason: str
    matched: tuple[str, ...] = ()
    obligations: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.effect == "allow"

    @property
    def interrupted(self) -> bool:
        return self.effect == "interrupt"

    @staticmethod
    def allow(reason: str = "allowed", *matched: str, obligations: tuple[str, ...] = ()) -> "Decision":
        return Decision("allow", reason, tuple(matched), obligations)

    @staticmethod
    def deny(reason: str, *matched: str, obligations: tuple[str, ...] = ()) -> "Decision":
        return Decision("deny", reason, tuple(matched), obligations)

    @staticmethod
    def interrupt(reason: str, *matched: str, obligations: tuple[str, ...] = ()) -> "Decision":
        return Decision("interrupt", reason, tuple(matched), obligations)


@dataclass(frozen=True)
class ScanFinding:
    rule_id: str
    severity: Severity
    category: str
    message: str
    location: str | None = None
    confidence: str | None = None
    remediation: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScanReport:
    scanner: str
    target: str
    findings: tuple[ScanFinding, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def max_severity(self) -> Severity:
        if not self.findings:
            return "none"
        return max(self.findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 0)).severity

    @property
    def finding_count(self) -> int:
        return len(self.findings)


@dataclass(frozen=True)
class SkillManifest:
    """Parsed SKILL.md metadata plus a few guardrail-specific extensions."""

    name: str
    description: str
    path: Path
    license: str | None = None
    compatibility: str | None = None
    allowed_tools: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    body_preview: str = ""

    @property
    def skill_id(self) -> str:
        return self.name


@dataclass(frozen=True)
class SkillRecord:
    manifest: SkillManifest
    digest: str
    scan: ScanReport

    @property
    def skill_id(self) -> str:
        return self.manifest.skill_id

    @property
    def path(self) -> Path:
        return self.manifest.path
