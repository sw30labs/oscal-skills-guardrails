"""Compile an OSCAL skills-policy profile into a GuardrailPolicy.

OSCAL is the authoring and compliance format; the runtime engine stays
`GuardrailPolicy`. See docs/oscal-skills-profile-schema.md for the prop
vocabulary (namespace https://sw30labs.com/ns/osg).

Accepted profile shapes:
  * pragmatic (sibling-repo style): profile.modify.controls[*].props
  * strict OSCAL:                   profile.modify.alters[*].adds[*].props
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from .policy import GuardrailPolicy

OSG_NS = "https://sw30labs.com/ns/osg"

_TARGET_TYPES = {"defaults", "agent", "subagent", "skill", "role", "filesystem"}

# control-id prefix -> target type, used when osg:target-type is absent.
_ID_PREFIX_TO_TYPE = {
    "sg-def": "defaults",
    "sg-agt-": "agent",
    "sg-sub-": "subagent",
    "sg-skl-": "skill",
    "sg-rol-": "role",
    "sg-fs-": "filesystem",
}

# set-parameters param-id -> defaults key (scalar unless noted).
_PARAM_TO_DEFAULT = {
    "osg-max-scan-severity": "max_scan_severity",
    "osg-interrupt-at-severity": "interrupt_at_severity",
    "osg-min-score": "min_score",
    "osg-min-grade": "min_grade",
    "osg-require-rubric": "require_rubric",
    "osg-allow-skills": "allow_skills",  # list: all values
    "osg-deny-tools": "deny_tools",  # list: all values
}
_LIST_PARAMS = {"osg-allow-skills", "osg-deny-tools"}

# repeatable prop -> spec list key
_LIST_PROPS = {
    "osg:allow-skill": "allow_skills",
    "osg:deny-skill": "deny_skills",
    "osg:allow-tool": "allow_tools",
    "osg:deny-tool": "deny_tools",
}

# scalar prop -> spec key
_SCALAR_PROPS = {
    "osg:max-scan-severity": "max_scan_severity",
    "osg:interrupt-at-severity": "interrupt_at_severity",
    "osg:min-grade": "min_grade",
    "osg:effect": "effect",
    "osg:reason": "reason",
}


def load_skills_policy_profile(path: str | Path) -> GuardrailPolicy:
    with Path(path).open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return GuardrailPolicy(compile_profile(raw))


def compile_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """Compile a parsed OSCAL profile document into the GuardrailPolicy dict shape."""

    profile = raw.get("profile", raw)
    if not isinstance(profile, dict):
        raise ValueError("OSCAL document must contain a 'profile' mapping")

    out: dict[str, Any] = {
        "version": 1,
        "defaults": {},
        "agents": {},
        "subagents": {},
        "skills": {},
        "roles": {},
        "filesystem_permissions": [],
        "_oscal": {
            "uuid": profile.get("uuid"),
            "title": (profile.get("metadata") or {}).get("title"),
            "version": (profile.get("metadata") or {}).get("version"),
        },
    }

    modify = profile.get("modify") or {}

    for sp in modify.get("set-parameters") or []:
        param_id = str(sp.get("param-id") or "")
        key = _PARAM_TO_DEFAULT.get(param_id)
        if not key:
            continue
        values = [str(v) for v in (sp.get("values") or [])]
        if not values:
            continue
        if param_id in _LIST_PARAMS:
            out["defaults"][key] = values
        elif key == "min_score":
            out["defaults"][key] = int(values[0])
        else:
            out["defaults"][key] = values[0]

    for control_id, props in _iter_policy_controls(modify):
        target_type, target_id, spec, fs_rule = _compile_control(control_id, props)
        if target_type == "defaults":
            out["defaults"].update(spec)
        elif target_type == "filesystem":
            if fs_rule:
                out["filesystem_permissions"].append(fs_rule)
        elif target_type == "agent":
            out["agents"].setdefault(target_id, {}).update(spec)
        elif target_type == "subagent":
            out["subagents"].setdefault(target_id, {}).update(spec)
        elif target_type == "skill":
            out["skills"].setdefault(target_id, {}).update(spec)
        elif target_type == "role":
            out["roles"].setdefault(target_id, {}).update(spec)

    return out


def _iter_policy_controls(modify: dict[str, Any]) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    for ctl in modify.get("controls") or []:
        yield str(ctl.get("control-id") or ""), list(ctl.get("props") or [])
    for alter in modify.get("alters") or []:
        control_id = str(alter.get("control-id") or "")
        for add in alter.get("adds") or []:
            props = list(add.get("props") or [])
            if props:
                yield control_id, props


def _compile_control(
    control_id: str, props: list[dict[str, Any]]
) -> tuple[str, str, dict[str, Any], dict[str, Any] | None]:
    grouped: dict[str, list[str]] = {}
    for p in props:
        name = str(p.get("name") or "")
        if not name.startswith("osg:"):
            continue
        grouped.setdefault(name, []).append(str(p.get("value") or ""))

    target_type = (grouped.get("osg:target-type") or [None])[0] or _infer_target_type(control_id)
    if target_type not in _TARGET_TYPES:
        raise ValueError(f"Unknown osg:target-type {target_type!r} on control {control_id!r}")

    target_id = (grouped.get("osg:target-id") or [None])[0] or _infer_target_id(control_id)

    spec: dict[str, Any] = {}
    for prop_name, key in _LIST_PROPS.items():
        if grouped.get(prop_name):
            spec[key] = list(grouped[prop_name])
    for prop_name, key in _SCALAR_PROPS.items():
        if grouped.get(prop_name):
            spec[key] = grouped[prop_name][0]
    if grouped.get("osg:min-score"):
        spec["min_score"] = int(grouped["osg:min-score"][0])
    if grouped.get("osg:require-rubric"):
        spec["require_rubric"] = grouped["osg:require-rubric"][0].strip().lower() in {
            "true",
            "1",
            "yes",
        }

    metadata_pairs = grouped.get("osg:required-metadata") or []
    if metadata_pairs:
        required: dict[str, str] = {}
        for pair in metadata_pairs:
            if "=" not in pair:
                raise ValueError(
                    f"osg:required-metadata must be key=value, got {pair!r} on {control_id!r}"
                )
            k, v = pair.split("=", 1)
            required[k.strip()] = v.strip()
        spec["required_metadata"] = required

    fs_rule: dict[str, Any] | None = None
    if target_type == "filesystem":
        fs_rule = {
            "operations": grouped.get("osg:fs-operation") or [],
            "paths": grouped.get("osg:fs-path") or [],
            "mode": (grouped.get("osg:fs-mode") or ["allow"])[0],
        }

    return target_type, str(target_id or ""), spec, fs_rule


def _infer_target_type(control_id: str) -> str | None:
    if control_id == "sg-def":
        return "defaults"
    for prefix, ttype in _ID_PREFIX_TO_TYPE.items():
        if control_id.startswith(prefix):
            return ttype
    return None


def _infer_target_id(control_id: str) -> str:
    for prefix in _ID_PREFIX_TO_TYPE:
        if prefix != "sg-def" and control_id.startswith(prefix):
            suffix = control_id[len(prefix):]
            return "*" if suffix == "wildcard" else suffix
    return ""
