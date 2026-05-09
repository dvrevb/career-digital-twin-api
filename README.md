# career-digital-twin-api

FastAPI backend that powers the portfolio chatbot. Ports the chat logic from [`career-digital-twin`](../career-digital-twin) — same brain, minus the Gradio shell — and exposes it as a JSON HTTP API deployed to AWS Lambda behind API Gateway (HTTP API v2) via AWS SAM.

## Contract

### `POST /chat`

Headers:
- `X-Internal-Key` — shared secret (required; 401 without)
- `X-Forwarded-For` — client IP, set by the Next.js proxy for rate-limiting
- `Content-Type: application/json`

Body:
```json
{ "message": "...", "history": [{ "role": "user|assistant", "content": "..." }] }
```

Response:
```json
{ "reply": "...", "tokens_used": 387, "model": "gpt-4o-mini" }
```

Errors: `400` validation, `401` bad key, `429` rate-limited, `502` OpenAI error, `504` timeout.

### `GET /health`

```json
{ "status": "ok", "openai_key_present": true }
```

## Local development

Requires Python 3.12.

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements-dev.txt

cp .env.example .env          # fill in values
# Drop your knowledge base into me/linkedin.pdf and me/summary.txt (gitignored)

uvicorn main:app --reload
```

Smoke test:

```bash
curl http://localhost:8000/health
# -> {"status":"ok","openai_key_present":true}

curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Internal-Key: <your-INTERNAL_API_KEY>" \
  -d '{"message":"What is your background?","history":[]}'
```

## Project layout

```
main.py          FastAPI app, routes, Mangum handler
me_agent.py      Me class — async chat with tool-call loop
tools.py         record_user_details, record_unknown_question + OpenAI schemas
notification.py  push() dispatcher → Telegram or Pushover (toggle via USE_TELEGRAM_NOTIFICATIONS)
guardrails.py    rate limit, Pydantic validation, API key dep
me/              knowledge base (linkedin.pdf + summary.txt — gitignored)
template.yaml    AWS SAM: Lambda + HTTP API v2 + custom domain
samconfig.toml   SAM deploy defaults
```

## Deployment (Phase B — manual)

DNS lives at **Porkbun**. Two CNAME records go there: one for ACM cert validation, one for the custom domain.

1. Request an ACM certificate for `api.burakcevik.dev` in the same region you'll deploy Lambda (e.g. `eu-central-1`). Validation method: DNS.
2. Add the ACM validation CNAME at Porkbun. Wait for "Issued".
3. Put secrets in SSM Parameter Store (SecureString). Always required:
   - `/career-twin/openai-api-key`
   - `/career-twin/internal-api-key` — generate 32 random chars

   Notification channel is selected by the `USE_TELEGRAM_NOTIFICATIONS` template parameter (default `true`). Create only the active channel's params; the inactive ones can be skipped — `push()` no-ops when its credentials are missing.

   - Telegram (default): `/career-twin/telegram-bot-token` (from BotFather), `/career-twin/telegram-chat-id` (message the bot, then `getUpdates`)
   - Pushover (toggle = `false`): `/career-twin/pushover-user-key`, `/career-twin/pushover-api-token`
4. Set a $10 monthly hard cap on your OpenAI key (OpenAI dashboard → Billing → Usage limits).
5. `sam build && sam deploy --guided` for the first deploy (saves answers to `samconfig.toml`); after that just `sam build && sam deploy`. Pass the ACM cert ARN as `AcmCertificateArn`.
6. SAM outputs `CustomDomainTarget` — CNAME `api.burakcevik.dev` → that value at Porkbun.
7. `curl https://api.burakcevik.dev/health` → 200.
8. Copy the `INTERNAL_API_KEY` value into the Next.js Vercel env vars.

Rotating a secret? Overwrite the value in SSM (same parameter name). `_bootstrap_ssm_secrets` in `main.py` re-fetches at every Lambda cold start, so the new value is picked up without a redeploy — force a refresh by either waiting for natural cold start or republishing the function.

## Guardrails

1. `X-Internal-Key` shared secret (app-level, constant-time compare)
2. CORS allowlist at API Gateway
3. API Gateway default throttling (burst 5 / rate 2 rps)
4. `slowapi` IP rate limit (10/min on `X-Forwarded-For`)
5. Pydantic validation (message 1–500 chars, history last 10 turns)
6. `max_tokens: 400` per OpenAI call
7. Layered timeouts (Lambda 15s, app 13s, OpenAI client 12s)
8. Model pinned via `OPENAI_MODEL`
9. OpenAI monthly budget cap — set manually in dashboard
10. CloudWatch 5-day log retention (Lambda only; API Gateway access logs disabled) + CloudWatch Alarm on >5 Lambda errors / 5 min

## Out of scope for v1

- Streaming responses (v1.5 — requires Lambda Function URL + `streamifyResponse`)
- RAG / vector DB
- Conversation persistence
- Multi-region deploy
