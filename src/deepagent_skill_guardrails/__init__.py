"""DeepAgents skill guardrails scaffold.

This package intentionally keeps DeepAgents and MCP imports optional so policy/registry
unit tests can run without agent runtime dependencies installed.
"""

from .models import (
    AgentContext,
    Decision,
    ScanFinding,
    ScanReport,
    SkillIntegrityError,
    SkillManifest,
    SkillRecord,
)
from .oscal_loader import compile_profile, load_skills_policy_profile
from .oscal_results import OscalAssessmentSink
from .policy import GuardrailPolicy
from .registry import SkillRegistry, verify_digest_lock
from .rubric_judge import (
    DEFAULT_SKILL_RUBRIC,
    Criterion,
    RubricJudgeScanner,
    command_judge,
    langchain_judge,
    omlx_judge,
    openai_chat_judge,
)
from .scanner import (
    CompositeSkillScanner,
    HttpSkillScanner,
    NoopSkillScanner,
    SubprocessSkillScanner,
)

__all__ = [
    "AgentContext",
    "CompositeSkillScanner",
    "Criterion",
    "DEFAULT_SKILL_RUBRIC",
    "Decision",
    "GuardrailPolicy",
    "OscalAssessmentSink",
    "RubricJudgeScanner",
    "SkillIntegrityError",
    "command_judge",
    "langchain_judge",
    "omlx_judge",
    "openai_chat_judge",
    "compile_profile",
    "load_skills_policy_profile",
    "verify_digest_lock",
    "HttpSkillScanner",
    "NoopSkillScanner",
    "ScanFinding",
    "ScanReport",
    "SkillManifest",
    "SkillRecord",
    "SkillRegistry",
    "SubprocessSkillScanner",
]
