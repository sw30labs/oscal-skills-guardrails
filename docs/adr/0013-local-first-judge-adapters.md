# ADR-0013: Judge adapters are local-first: oMLX on 127.0.0.1 by default, stdlib HTTP, temperature 0

## Status

Accepted (retrospective, inferred 2026-11-15)

## Context

`omlx_judge` says "skills never leave the machine". The CLI help defaults the judge root to `$OMLX_BASE_URL` or `http://127.0.0.1:8000/v1`, "oMLX". The judge is any callable `prompt -> text` so different backends can be used.

## Decision

Adapters: `openai_chat_judge(base_url, model, ...)` posts to any OpenAI-compatible `/chat/completions` using `urllib.request` (no extra dependency), `temperature=0.0`, `max_tokens=2000`, 300 s timeout; `omlx_judge` defaults that to the local oMLX server; `command_judge(command)` pipes the prompt to a CLI (README example `("claude", "-p")`); `langchain_judge("provider:model")` uses the optional `judge` extra. The CLI resolves the model from `--rubric-judge-model`, then `SKILL_JUDGE_MODEL`, then `OMLX_MODEL`, and the key from flag, `SKILL_JUDGE_API_KEY`, or `OMLX_API_KEY`.

## Consequences

### Positive

- Skill content under review can stay on the developer's machine.
- No mandatory network SDK; deterministic sampling settings.

### Negative

- The default endpoint is a local port that other tools on the same machine may also use; availability is outside this repo's control.
- Why oMLX specifically is the default is inferred from the docstring, not stated as a decision (A-023).

## Alternatives considered

- A hosted LLM as default (supported through `openai_chat_judge` / `langchain_judge`, but not the default).

## Evidence

- src/deepagent_skill_guardrails/rubric_judge.py (`openai_chat_judge`, `omlx_judge`, `command_judge`, `langchain_judge`)
- src/deepagent_skill_guardrails/cli.py (judge flags, env fallback)
- README.md (Rubric judge)
- tests/test_omlx_judge.py
