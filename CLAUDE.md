# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## What this repo is

Python/FastAPI backend for the portfolio chatbot at `burakcevik.dev`. Ships as a single AWS Lambda behind API Gateway HTTP API v2, deployed via AWS SAM. A separate Next.js repo (`chatbot-ui`) owns the UI and calls `POST /chat` with an `X-Internal-Key` shared secret. Full HTTP contract and deploy runbook live in `README.md`.

## Runtime pin

Lambda runs Python **3.12**. `template.yaml` pins it. Local dev should match — a newer Python (e.g. 3.14) will import fine for smoke tests, but anything you verify locally must still work on 3.12 before deploy.

## Commands

```bash
python -m venv .venv
.venv\Scripts\activate                    # Windows; use source .venv/bin/activate elsewhere
pip install -r requirements-dev.txt       # dev pulls in requirements.txt too
cp .env.example .env                      # fill OPENAI_API_KEY, INTERNAL_API_KEY, etc.

uvicorn main:app --reload                 # local server on :8000
sam build && sam local start-api          # exercise the Lambda packaging path
sam deploy --guided                       # first-time deploy; see README Phase B
```

No test suite, linter, or formatter is wired up yet. Verify by hitting the endpoints (see README "Smoke test").

## Architecture notes that aren't obvious from the file list

- **`main.py` is the ASGI entrypoint and the Lambda handler.** `handler = Mangum(app, lifespan="off")` at the bottom — that's what `template.yaml` points at. `lifespan="off"` is deliberate: Lambda has no lifespan events.
- **`Me` is a lazy module-level singleton** (`get_me()` in `main.py`). It's instantiated on first `/chat` call, not at import, so cold-start cost lands on the first request rather than every Lambda init. Don't move construction to module scope without thinking about cold-start.
- **Tool-call loop lives in `me_agent.py`** — `chat_async` runs a bounded loop over OpenAI tool calls (`record_user_details`, `record_unknown_question` from `tools.py`), which in turn fire Pushover pings via `notification.py`. The bound is intentional; don't remove it.
- **Guardrails are layered**, and the layering matters — see README "Guardrails" for the full stack. In code: `guardrails.py` owns the Pydantic schemas, the `X-Internal-Key` dependency (constant-time compare), and the slowapi limiter. `main.py` adds the 30s `asyncio.wait_for` timeout and the OpenAI error → `502`/`504` mapping. HTTP status codes are part of the frozen contract (`400/401/429/502/504`) — a `RequestValidationError` handler in `main.py` exists specifically to rewrite FastAPI's default `422` to `400`.
- **Knowledge base is `me/linkedin.pdf` + `me/summary.txt`** (gitignored). `me/.gitkeep` keeps the dir tracked. Without these files, `Me()` construction will fail — that's why `/health` only checks for the OpenAI key, not the agent.
- **Secrets come from SSM Parameter Store with version pins** (`template.yaml` references `/career-twin/openai-api-key:1` etc.). Rotating a secret means bumping `:1` to `:2` in the template and redeploying — CloudFormation caches the resolved value by version. Locally, the same names come from `.env`.
