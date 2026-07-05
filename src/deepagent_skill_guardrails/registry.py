from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import SkillManifest, SkillRecord
from .scanner import NoopSkillScanner, SkillScanner

try:  # pragma: no cover - exercised when PyYAML is installed
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


@dataclass
class SkillRegistry:
    """Scanned, immutable-ish catalog of skills available to your app.

    The registry is an admission-control boundary: a skill is not eligible for any
    DeepAgent until it has a manifest, content digest, and scan report.
    """

    scanner: SkillScanner = field(default_factory=NoopSkillScanner)
    records: dict[str, SkillRecord] = field(default_factory=dict)

    def discover(self, root: Path, *, recursive: bool = True) -> list[Path]:
        pattern = "**/SKILL.md" if recursive else "*/SKILL.md"
        return sorted(p.parent for p in root.glob(pattern) if p.is_file())

    def ingest_many(self, skill_dirs: Iterable[Path]) -> dict[str, SkillRecord]:
        for skill_dir in skill_dirs:
            self.ingest(skill_dir)
        return self.records

    def ingest(self, skill_dir: Path) -> SkillRecord:
        skill_dir = skill_dir.resolve()
        manifest = parse_skill_manifest(skill_dir)
        digest = digest_directory(skill_dir)
        scan = self.scanner.scan(skill_dir)
        record = SkillRecord(manifest=manifest, digest=digest, scan=scan)
        self.records[record.skill_id] = record
        return record

    def get(self, skill_id: str) -> SkillRecord | None:
        return self.records.get(skill_id)

    def require(self, skill_id: str) -> SkillRecord:
        record = self.get(skill_id)
        if not record:
            raise KeyError(f"Unknown skill: {skill_id}")
        return record

    def by_path(self, path: str | Path) -> SkillRecord | None:
        candidate = Path(path).resolve()
        for record in self.records.values():
            if record.path.resolve() == candidate:
                return record
        return None

    # ------------------------------------------------------------------ SG-2
    def verify(self, skill_id: str) -> tuple[bool, str]:
        """Recompute a skill's digest and compare with its admitted digest.

        Returns (ok, current_digest). Missing directories return (False, "").
        """

        record = self.require(skill_id)
        if not record.path.is_dir():
            return False, ""
        current = digest_directory(record.path)
        return current == record.digest, current

    def verify_all(self) -> dict[str, tuple[bool, str]]:
        return {skill_id: self.verify(skill_id) for skill_id in self.records}

    def save_digest_lock(self, path: str | Path, *, relative_to: Path | None = None) -> Path:
        """Persist admitted digests so integrity can be verified across processes/CI.

        Pass `relative_to` (usually the skills root) to record portable relative paths —
        required when the lockfile is committed and verified on other machines/checkouts.
        """

        def _portable(record: SkillRecord) -> str:
            if relative_to is not None:
                try:
                    return record.path.resolve().relative_to(Path(relative_to).resolve()).as_posix()
                except ValueError:
                    pass
            return str(record.path)

        path = Path(path)
        doc = {
            "version": 1,
            "generated": datetime.now(timezone.utc).isoformat(),
            "skills": {
                skill_id: {"digest": record.digest, "path": _portable(record)}
                for skill_id, record in sorted(self.records.items())
            },
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        return path


def verify_digest_lock(
    lock_path: str | Path, *, skills_root: Path | None = None
) -> dict[str, dict[str, str]]:
    """Compare a digest lockfile against the current filesystem state.

    Returns {skill_id: {"status": ok|changed|missing, "expected": ..., "actual": ...}}.
    If `skills_root` is given, skill directories are resolved as root/<dir-name> instead
    of the absolute path recorded in the lock (portable CI checkouts), and skills present
    under the root but absent from the lock are reported with status "new".
    """

    lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    entries: dict[str, dict[str, str]] = {}
    locked = lock.get("skills") or {}

    for skill_id, meta in locked.items():
        recorded = Path(meta.get("path", ""))
        skill_dir = (skills_root / recorded.name) if skills_root else recorded
        expected = str(meta.get("digest", ""))
        if not skill_dir.is_dir():
            entries[skill_id] = {"status": "missing", "expected": expected, "actual": ""}
            continue
        actual = digest_directory(skill_dir)
        entries[skill_id] = {
            "status": "ok" if actual == expected else "changed",
            "expected": expected,
            "actual": actual,
        }

    if skills_root is not None:
        locked_dirs = {Path(m.get("path", "")).name for m in locked.values()}
        for skill_md in sorted(skills_root.glob("**/SKILL.md")):
            if skill_md.parent.name not in locked_dirs:
                entries[skill_md.parent.name] = {
                    "status": "new",
                    "expected": "",
                    "actual": digest_directory(skill_md.parent),
                }
    return entries


def parse_skill_manifest(skill_dir: Path) -> SkillManifest:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        raise ValueError(f"Missing SKILL.md in {skill_dir}")

    text = skill_file.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"SKILL.md must begin with YAML frontmatter: {skill_file}")

    frontmatter_text, body = match.groups()
    data = _load_yaml(frontmatter_text)
    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()
    if not name or not description:
        raise ValueError(f"SKILL.md requires name and description: {skill_file}")
    if not _NAME_RE.match(name) or "--" in name:
        raise ValueError(f"Invalid skill name {name!r} in {skill_file}")
    if skill_dir.name != name:
        raise ValueError(f"Skill name {name!r} must match directory name {skill_dir.name!r}")

    raw_allowed = data.get("allowed-tools") or data.get("allowed_tools") or ""
    allowed_tools: tuple[str, ...]
    if isinstance(raw_allowed, str):
        allowed_tools = tuple(x for x in re.split(r"[\s,]+", raw_allowed.strip()) if x)
    elif isinstance(raw_allowed, list):
        allowed_tools = tuple(str(x) for x in raw_allowed)
    else:
        allowed_tools = ()

    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {"raw_metadata": metadata}
    # Merge unknown top-level frontmatter keys into metadata. This keeps SKILL.md files
    # flat (compatible with Skillspector's YAML-lite frontmatter parser) while still
    # supporting required_metadata policies (e.g. a top-level `owner: governance`).
    known_keys = {
        "name",
        "description",
        "license",
        "compatibility",
        "allowed-tools",
        "allowed_tools",
        "metadata",
        "module",
    }
    for key, value in data.items():
        if key not in known_keys and key not in metadata:
            metadata[key] = value

    return SkillManifest(
        name=name,
        description=description,
        path=skill_dir,
        license=data.get("license"),
        compatibility=data.get("compatibility"),
        allowed_tools=allowed_tools,
        metadata=metadata,
        body_preview=body[:2000],
    )


def _load_yaml(text: str) -> dict[str, Any]:
    if yaml is not None:
        loaded = yaml.safe_load(text) or {}
        if not isinstance(loaded, dict):
            raise ValueError("SKILL.md frontmatter must be a YAML mapping")
        return loaded

    # Tiny fallback for simple key: value frontmatter. Prefer PyYAML in production.
    result: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip('"\'')
    return result


def digest_directory(skill_dir: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in skill_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(skill_dir).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()
