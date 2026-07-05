from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from deepagent_skill_guardrails.cli import main
from deepagent_skill_guardrails.rubric_judge import (
    DEFAULT_SKILL_RUBRIC,
    RubricJudgeScanner,
    openai_chat_judge,
)


def verdict_json() -> str:
    return json.dumps(
        {
            "criteria": [
                {"id": c.id, "verdict": "pass", "evidence": "", "explanation": "ok"}
                for c in DEFAULT_SKILL_RUBRIC
            ],
            "overall": "pass",
            "summary": "fake omlx verdict",
        }
    )


class FakeOpenAIHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible /chat/completions endpoint (oMLX contract)."""

    seen: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length))
        type(self).seen.append(
            {"path": self.path, "auth": self.headers.get("Authorization"), "body": request}
        )
        response = json.dumps(
            {
                "id": "chatcmpl-fake",
                "object": "chat.completion",
                "model": request.get("model"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": verdict_json()},
                        "finish_reason": "stop",
                    }
                ],
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args):  # silence
        pass


@pytest.fixture()
def fake_server():
    FakeOpenAIHandler.seen = []
    server = HTTPServer(("127.0.0.1", 0), FakeOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


def make_skill(root: Path, name: str = "local-skill") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use this skill for tests.\n---\n# {name}\n",
        encoding="utf-8",
    )
    return skill_dir


def test_openai_chat_judge_roundtrip(tmp_path: Path, fake_server: str) -> None:
    judge = openai_chat_judge(fake_server, "mlx-community/test-model", api_key="test")
    scanner = RubricJudgeScanner(judge=judge, judge_name=f"mlx-community/test-model@{fake_server}")
    report = scanner.scan(make_skill(tmp_path))

    assert report.max_severity == "none"
    assert report.raw["rubric"]["overall"] == "pass"
    assert "test-model" in report.raw["rubric"]["judge"]

    request = FakeOpenAIHandler.seen[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["auth"] == "Bearer test"
    assert request["body"]["model"] == "mlx-community/test-model"
    assert request["body"]["temperature"] == 0.0
    assert "<<<SKILL_CONTENT_BEGIN>>>" in request["body"]["messages"][0]["content"]


def test_judge_endpoint_down_fails_closed(tmp_path: Path) -> None:
    judge = openai_chat_judge("http://127.0.0.1:9", "m")  # port 9: refused
    report = RubricJudgeScanner(judge=judge).scan(make_skill(tmp_path))
    assert report.max_severity == "critical"
    assert report.findings[0].rule_id == "RUB-JUDGE-ERROR"


def test_cli_admit_with_omlx_style_endpoint(tmp_path: Path, fake_server: str, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    skills_root = tmp_path / "skills"
    make_skill(skills_root, "alpha")
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        "defaults:\n  max_scan_severity: medium\n  require_rubric: true\n"
        'agents:\n  "*":\n    allow_skills: ["*"]\n',
        encoding="utf-8",
    )
    results = tmp_path / "ar.json"

    code = main(
        [
            "admit",
            "--skills",
            str(skills_root),
            "--policy",
            str(policy_path),
            "--rubric-judge-url",
            fake_server,
            "--rubric-judge-model",
            "mlx-community/test-model",
            "--rubric-judge-api-key",
            "test",
            "--results",
            str(results),
        ]
    )
    assert code == 0  # rubric present + pass -> allowed despite require_rubric

    ar = json.loads(results.read_text())
    obs = ar["assessment-results"]["results"][0]["observations"][0]
    props = {p["name"]: p["value"] for p in obs["props"]}
    assert props["osg:rubric-judge"].startswith("mlx-community/test-model@")
    assert props["osg:rubric-overall"] == "pass"


def test_cli_env_fallback_activates_judge(tmp_path: Path, fake_server: str, monkeypatch) -> None:
    """SKILL_JUDGE_MODEL + OMLX_BASE_URL alone are enough — no judge flags needed."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SKILL_JUDGE_MODEL", "Qwen3.6-27B-bf16")
    monkeypatch.setenv("OMLX_BASE_URL", fake_server)
    monkeypatch.setenv("OMLX_API_KEY", "test")
    skills_root = tmp_path / "skills"
    make_skill(skills_root, "alpha")
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        "defaults:\n  require_rubric: true\nagents:\n  \"*\":\n    allow_skills: [\"*\"]\n",
        encoding="utf-8",
    )
    results = tmp_path / "ar.json"

    code = main(
        ["admit", "--skills", str(skills_root), "--policy", str(policy_path), "--results", str(results)]
    )
    assert code == 0

    request = FakeOpenAIHandler.seen[0]
    assert request["body"]["model"] == "Qwen3.6-27B-bf16"
    assert request["auth"] == "Bearer test"

    ar = json.loads(results.read_text())
    props = {
        p["name"]: p["value"]
        for p in ar["assessment-results"]["results"][0]["observations"][0]["props"]
    }
    assert props["osg:rubric-judge"].startswith("Qwen3.6-27B-bf16@")


def test_cli_rejects_conflicting_judge_flags(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    skills_root = tmp_path / "skills"
    make_skill(skills_root, "alpha")
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text('agents:\n  "*":\n    allow_skills: ["*"]\n', encoding="utf-8")
    code = main(
        [
            "admit",
            "--skills",
            str(skills_root),
            "--policy",
            str(policy_path),
            "--rubric-judge-cmd",
            "claude -p",
            "--rubric-judge-model",
            "x",
        ]
    )
    assert code == 2
