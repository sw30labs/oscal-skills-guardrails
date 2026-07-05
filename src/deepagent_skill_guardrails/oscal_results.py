"""Emit guardrail Decisions as an OSCAL assessment-results document (SG-8).

`OscalAssessmentSink` is a plain callable compatible with the `audit_sink` hook used
by the middleware and factory. It buffers decision events and serializes them into
one OSCAL `assessment-results` document:

  * every event  -> an observation (methods: ["TEST"]) with osg:* props
  * deny/interrupt events -> additionally a finding targeting the SG control
    objective (state: not-satisfied), linked to its observation

Closing the loop: profile (policy) -> Decision (runtime) -> assessment-results (audit).

Standard-library only. Usage:

    sink = OscalAssessmentSink(profile_href="data/oscal-policies/skills-policy-profile.json")
    agent = create_guarded_deep_agent(..., audit_sink=sink)
    ...
    sink.write("out/assessment-results.json")
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OSG_NS = "https://sw30labs.com/ns/osg"
OSCAL_VERSION = "1.1.2"

# Stable namespace for deterministic subject UUIDs (uuid5 of skill/tool ids).
_SUBJECT_NS = uuid.uuid5(uuid.NAMESPACE_URL, OSG_NS)

# matched-rule token -> SG control id. First match wins; order matters.
_MATCH_TO_CONTROL: tuple[tuple[str, str], ...] = (
    ("skill.digest_mismatch", "sg-2"),
    ("scan.rubric_missing", "sg-9"),
    ("scan.interrupt_at_severity", "sg-6"),
    ("scan.max_severity", "sg-1"),
    ("scan.min_score", "sg-1"),
    ("scan.min_grade", "sg-1"),
    ("scan.score_missing", "sg-1"),
    ("scan.grade_missing", "sg-1"),
    ("skill.required_metadata", "sg-7"),
    ("agent.allow_skills", "sg-3"),
    ("agent.deny_skills", "sg-3"),
    ("skill.admission", "sg-3"),
    ("skill.effect", "sg-3"),
    ("tool.deny_tools", "sg-4"),
    ("tool.allow_tools", "sg-4"),
    ("tool.admission", "sg-4"),
    ("skill.allow_tools", "sg-4"),
    ("skill.deny_tools", "sg-4"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def control_for_event(event: dict[str, Any]) -> str:
    """Map a decision event to the SG control it exercises."""

    if event.get("kind") == "integrity_violation":
        return "sg-2"
    matched = [str(m) for m in (event.get("matched") or [])]
    obligations = [str(o) for o in (event.get("obligations") or [])]
    for token, control in _MATCH_TO_CONTROL:
        if any(token in m for m in matched):
            if control == "sg-3" and event.get("effect") == "interrupt":
                return "sg-6"
            return control
    if "human_approval" in obligations:
        return "sg-6"
    if event.get("kind") == "tool_decision":
        return "sg-4"
    if event.get("kind") in {"skill_decision", "skill_rescan"}:
        return "sg-3"
    return "sg-8"


class OscalAssessmentSink:
    """Buffer audit events and render them as OSCAL assessment-results.

    Thread-unsafe by design (append-only list); wrap with a lock if you share one
    sink across concurrent runs, or use one sink per run_id.
    """

    def __init__(
        self,
        *,
        title: str = "Skill guardrails decision log",
        profile_href: str = "skills-policy-profile.json",
        run_id: str | None = None,
        version: str = "0.1.0",
    ) -> None:
        self.title = title
        self.profile_href = profile_href
        self.run_id = run_id or str(uuid.uuid4())
        self.version = version
        self.events: list[dict[str, Any]] = []
        self._started = _now()

    # audit_sink protocol -------------------------------------------------
    def __call__(self, event: dict[str, Any]) -> None:
        self.events.append({**event, "collected": event.get("collected") or _now()})

    # convenience ----------------------------------------------------------
    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {"allow": 0, "deny": 0, "interrupt": 0}
        for e in self.events:
            effect = str(e.get("effect") or "allow")
            out[effect] = out.get(effect, 0) + 1
        return out

    def to_document(self) -> dict[str, Any]:
        observations: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        controls_seen: set[str] = set()

        for event in self.events:
            control = control_for_event(event)
            controls_seen.add(control)
            obs_uuid = str(uuid.uuid4())
            subject_id = str(event.get("skill_id") or event.get("tool") or "unknown")
            subject_type = "component" if "skill" in str(event.get("kind", "")) else "resource"
            effect = str(event.get("effect") or "allow").upper()
            title = f"{event.get('kind', 'decision')}: {subject_id} -> {effect}"

            props = [
                {"name": "osg:kind", "value": str(event.get("kind", "")), "ns": OSG_NS},
                {"name": "osg:agent-id", "value": str(event.get("agent_id", "")), "ns": OSG_NS},
                {"name": "osg:effect", "value": str(event.get("effect", "")), "ns": OSG_NS},
                {"name": "osg:control", "value": control, "ns": OSG_NS},
                {"name": "osg:run-id", "value": self.run_id, "ns": OSG_NS},
            ]
            for key, prop in (
                ("skill_id", "osg:skill-id"),
                ("tool", "osg:tool"),
                ("digest", "osg:digest"),
                ("expected_digest", "osg:expected-digest"),
                ("actual_digest", "osg:actual-digest"),
                ("scan_severity", "osg:scan-severity"),
                ("scan_score", "osg:scan-score"),
                ("scan_grade", "osg:scan-grade"),
                ("rubric_judge", "osg:rubric-judge"),
                ("rubric_overall", "osg:rubric-overall"),
            ):
                if event.get(key) not in (None, ""):
                    props.append({"name": prop, "value": str(event[key]), "ns": OSG_NS})
            if event.get("matched"):
                props.append(
                    {"name": "osg:matched", "value": " ".join(map(str, event["matched"])), "ns": OSG_NS}
                )
            if event.get("obligations"):
                props.append(
                    {
                        "name": "osg:obligations",
                        "value": " ".join(map(str, event["obligations"])),
                        "ns": OSG_NS,
                    }
                )

            observations.append(
                {
                    "uuid": obs_uuid,
                    "title": title,
                    "description": f"{effect}: {event.get('reason', '')}",
                    "methods": ["TEST"],
                    "props": props,
                    "subjects": [
                        {
                            "subject-uuid": str(uuid.uuid5(_SUBJECT_NS, subject_id)),
                            "type": subject_type,
                            "title": subject_id,
                        }
                    ],
                    "collected": event["collected"],
                }
            )

            if str(event.get("effect")) in {"deny", "interrupt"}:
                findings.append(
                    {
                        "uuid": str(uuid.uuid4()),
                        "title": f"{effect} {subject_id}",
                        "description": str(event.get("reason", "")),
                        "target": {
                            "type": "objective-id",
                            "target-id": f"{control}_smt",
                            "status": {"state": "not-satisfied"},
                        },
                        "related-observations": [{"observation-uuid": obs_uuid}],
                    }
                )

        result: dict[str, Any] = {
            "uuid": str(uuid.uuid4()),
            "title": f"{self.title} — run {self.run_id}",
            "description": (
                "Automated skill/tool guardrail decisions recorded by "
                "deepagent-skill-guardrails. Observations cover every decision; "
                "findings cover denials and interrupts."
            ),
            "start": self._started,
            "end": _now(),
            "reviewed-controls": {
                "control-selections": [
                    {
                        "include-controls": [
                            {"control-id": c} for c in sorted(controls_seen or {"sg-8"})
                        ]
                    }
                ]
            },
        }
        if observations:
            result["observations"] = observations
        if findings:
            result["findings"] = findings

        return {
            "assessment-results": {
                "uuid": str(uuid.uuid4()),
                "metadata": {
                    "title": self.title,
                    "last-modified": _now(),
                    "version": self.version,
                    "oscal-version": OSCAL_VERSION,
                    "remarks": (
                        "import-ap references the skills policy profile that produced "
                        "these decisions (pragmatic deviation: no separate assessment "
                        "plan document exists)."
                    ),
                },
                "import-ap": {"href": self.profile_href},
                "results": [result],
            }
        }

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_document(), indent=2) + "\n", encoding="utf-8")
        return path
