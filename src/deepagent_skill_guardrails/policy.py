from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .models import AgentContext, Decision, SEVERITY_ORDER, Severity, SkillRecord

try:  # pragma: no cover - exercised when PyYAML is installed
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

# Skillspector letter grades, best to worst. Used by min_grade thresholds.
GRADE_ORDER: dict[str, int] = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}


@dataclass(frozen=True)
class GuardrailPolicy:
    """Small, YAML-backed policy engine for agent/tool/skill decisions.

    Use this as your local engine first. If you later want OPA/Cedar/OSCAL-native
    policy, keep this interface and swap the implementation behind it.
    """

    raw: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_yaml(path: str | Path) -> "GuardrailPolicy":
        if yaml is None:
            raise RuntimeError("PyYAML is required to load policy YAML")
        with Path(path).open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if not isinstance(loaded, dict):
            raise ValueError("Policy YAML must be a mapping")
        return GuardrailPolicy(loaded)

    def agent_spec(self, ctx: AgentContext) -> dict[str, Any]:
        agents = self.raw.get("agents", {}) or {}
        spec: dict[str, Any] = {}
        spec.update(agents.get("*") or {})
        for role in ctx.roles:
            spec.update((self.raw.get("roles", {}) or {}).get(role) or {})
        spec.update(agents.get(ctx.agent_id) or {})
        return spec

    def subagent_spec(self, ctx: AgentContext) -> dict[str, Any]:
        subagents = self.raw.get("subagents", {}) or {}
        spec = dict(subagents.get("*") or {})
        spec.update(subagents.get(ctx.agent_id) or {})
        return spec

    def allowed_skill_ids(self, ctx: AgentContext, available: Iterable[SkillRecord]) -> list[str]:
        spec = self.agent_spec(ctx)
        allow_patterns = _as_list(spec.get("allow_skills") or spec.get("skills"))
        deny_patterns = _as_list(spec.get("deny_skills"))
        if not allow_patterns:
            allow_patterns = _as_list((self.raw.get("defaults", {}) or {}).get("allow_skills"))
        if not allow_patterns:
            return []

        result: list[str] = []
        for record in available:
            skill_id = record.skill_id
            if _matches_any(skill_id, deny_patterns):
                continue
            if _matches_any(skill_id, allow_patterns) and self.check_skill(ctx, record).effect in {
                "allow",
                "interrupt",
            }:
                result.append(skill_id)
        return result

    def check_skill(self, ctx: AgentContext, record: SkillRecord) -> Decision:
        spec = self.agent_spec(ctx)
        skill_spec = (self.raw.get("skills", {}) or {}).get(record.skill_id) or {}
        allow_patterns = _as_list(spec.get("allow_skills") or spec.get("skills"))
        deny_patterns = _as_list(spec.get("deny_skills"))

        if _matches_any(record.skill_id, deny_patterns):
            return Decision.deny(f"skill {record.skill_id!r} explicitly denied", "agent.deny_skills")
        if allow_patterns and not _matches_any(record.skill_id, allow_patterns):
            return Decision.deny(f"skill {record.skill_id!r} not in allow_skills", "agent.allow_skills")

        # Hard per-skill override (osg:effect). "deny" short-circuits; "interrupt" is
        # applied after the severity/score gates below; "allow" never bypasses them.
        effect_override = str(skill_spec.get("effect") or "").lower()
        override_reason = skill_spec.get("reason") or "per-skill policy override"
        if effect_override == "deny":
            return Decision.deny(
                f"skill {record.skill_id!r} denied by policy: {override_reason}",
                "skill.effect",
            )

        max_allowed = (
            skill_spec.get("max_scan_severity")
            or spec.get("max_scan_severity")
            or (self.raw.get("defaults", {}) or {}).get("max_scan_severity")
            or "medium"
        )
        if _severity_gt(record.scan.max_severity, str(max_allowed)):
            return Decision.deny(
                f"skill {record.skill_id!r} scan severity {record.scan.max_severity} exceeds {max_allowed}",
                "scan.max_severity",
                obligations=("review_scan_report",),
            )

        defaults = self.raw.get("defaults", {}) or {}

        # SG-9: require the semantic rubric-judge evidence stream. Fail closed if the
        # scan carries no rubric section (judge not run, or stripped).
        require_rubric = _first_not_none(
            skill_spec.get("require_rubric"), spec.get("require_rubric"), defaults.get("require_rubric")
        )
        if _truthy(require_rubric) and not (record.scan.raw or {}).get("rubric"):
            return Decision.deny(
                f"skill {record.skill_id!r} requires a rubric-judge review but the scan has none",
                "scan.rubric_missing",
                obligations=("run_rubric_judge",),
            )

        # Skillspector score/grade thresholds. Fail closed: if a threshold is set but
        # the scanner did not report a score/grade, the skill is denied.
        min_score = _first_not_none(
            skill_spec.get("min_score"), spec.get("min_score"), defaults.get("min_score")
        )
        if min_score is not None:
            score = record.scan.raw.get("score")
            if not isinstance(score, (int, float)):
                return Decision.deny(
                    f"skill {record.skill_id!r} requires scan score >= {min_score} "
                    "but the scanner reported no score",
                    "scan.score_missing",
                    obligations=("review_scan_report",),
                )
            if float(score) < float(min_score):
                return Decision.deny(
                    f"skill {record.skill_id!r} scan score {score} below minimum {min_score}",
                    "scan.min_score",
                    obligations=("review_scan_report",),
                )

        min_grade = _first_not_none(
            skill_spec.get("min_grade"), spec.get("min_grade"), defaults.get("min_grade")
        )
        if min_grade is not None:
            grade = record.scan.raw.get("grade")
            grade_key = str(grade).upper() if isinstance(grade, str) else ""
            if grade_key not in GRADE_ORDER:
                return Decision.deny(
                    f"skill {record.skill_id!r} requires scan grade >= {min_grade} "
                    "but the scanner reported no grade",
                    "scan.grade_missing",
                    obligations=("review_scan_report",),
                )
            if GRADE_ORDER[grade_key] < GRADE_ORDER.get(str(min_grade).upper(), 0):
                return Decision.deny(
                    f"skill {record.skill_id!r} scan grade {grade} below minimum {min_grade}",
                    "scan.min_grade",
                    obligations=("review_scan_report",),
                )

        interrupt_at = skill_spec.get("interrupt_at_severity") or spec.get("interrupt_at_severity")
        if interrupt_at and _severity_gte(record.scan.max_severity, str(interrupt_at)):
            return Decision.interrupt(
                f"skill {record.skill_id!r} requires approval at severity {record.scan.max_severity}",
                "scan.interrupt_at_severity",
                obligations=("human_approval",),
            )

        if effect_override == "interrupt":
            return Decision.interrupt(
                f"skill {record.skill_id!r} requires approval: {override_reason}",
                "skill.effect",
                obligations=("human_approval",),
            )

        required_metadata = skill_spec.get("required_metadata") or {}
        if isinstance(required_metadata, dict):
            for key, expected in required_metadata.items():
                if record.manifest.metadata.get(key) != expected:
                    return Decision.deny(
                        f"skill {record.skill_id!r} missing required metadata {key}={expected!r}",
                        "skill.required_metadata",
                    )
        return Decision.allow("skill allowed", "skill.admission")

    def filter_skill_paths(self, ctx: AgentContext, available: Iterable[SkillRecord]) -> list[str]:
        return [str(record.path) for record in available if self.check_skill(ctx, record).effect == "allow"]

    def check_tool_call(
        self,
        ctx: AgentContext,
        tool_name: str,
        args: dict[str, Any] | None = None,
        *,
        skill_id: str | None = None,
    ) -> Decision:
        spec = self.agent_spec(ctx)
        if ctx.agent_id in (self.raw.get("subagents", {}) or {}):
            merged = dict(spec)
            merged.update(self.subagent_spec(ctx))
            spec = merged

        allow_tools = _as_list(spec.get("allow_tools") or spec.get("tools"))
        deny_tools = _as_list(spec.get("deny_tools")) + _as_list(
            (self.raw.get("defaults", {}) or {}).get("deny_tools")
        )

        if _matches_any(tool_name, deny_tools):
            return Decision.deny(f"tool {tool_name!r} explicitly denied", "tool.deny_tools")
        if allow_tools and not _matches_any(tool_name, allow_tools):
            return Decision.deny(f"tool {tool_name!r} not in allow_tools", "tool.allow_tools")

        if skill_id:
            skill_spec = (self.raw.get("skills", {}) or {}).get(skill_id) or {}
            skill_allow_tools = _as_list(skill_spec.get("allow_tools"))
            skill_deny_tools = _as_list(skill_spec.get("deny_tools"))
            if _matches_any(tool_name, skill_deny_tools):
                return Decision.deny(
                    f"tool {tool_name!r} denied for skill {skill_id!r}",
                    "skill.deny_tools",
                )
            if skill_allow_tools and not _matches_any(tool_name, skill_allow_tools):
                return Decision.deny(
                    f"tool {tool_name!r} not allowed for skill {skill_id!r}",
                    "skill.allow_tools",
                )

        return Decision.allow("tool allowed", "tool.admission")

    def tool_allowed(self, ctx: AgentContext, tool_name: str) -> bool:
        return self.check_tool_call(ctx, tool_name).allowed

    def deepagents_filesystem_permissions(self) -> list[Any]:
        """Create DeepAgents FilesystemPermission objects if deepagents is installed.

        Policy YAML shape:
          filesystem_permissions:
            - operations: ["write"]
              paths: ["/skills/shared/**"]
              mode: "deny"
        """

        rules = self.raw.get("filesystem_permissions") or []
        if not rules:
            return []
        try:
            from deepagents import FilesystemPermission
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("deepagents is required to materialize FilesystemPermission") from exc

        return [
            FilesystemPermission(
                operations=_as_list(rule.get("operations")),
                paths=_as_list(rule.get("paths")),
                mode=rule.get("mode", "allow"),
            )
            for rule in rules
        ]


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(x) for x in value]
    return [str(value)]


def _matches_any(value: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)


def _severity_gt(left: str, right: str) -> bool:
    return SEVERITY_ORDER.get(left, 0) > SEVERITY_ORDER.get(right, 0)


def _severity_gte(left: str, right: str) -> bool:
    return SEVERITY_ORDER.get(left, 0) >= SEVERITY_ORDER.get(right, 0)
