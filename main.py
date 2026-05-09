import asyncio
import logging
import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum
from openai import APIError, APITimeoutError
from slowapi.errors import RateLimitExceeded

load_dotenv(override=False)


def _bootstrap_ssm_secrets() -> None:
    if not os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return
    import boto3

    name_to_env = {
        os.environ["OPENAI_KEY_PARAM"]: "OPENAI_API_KEY",
        os.environ["INTERNAL_KEY_PARAM"]: "INTERNAL_API_KEY",
        os.environ["PUSHOVER_USER_PARAM"]: "PUSHOVER_USER_KEY",
        os.environ["PUSHOVER_TOKEN_PARAM"]: "PUSHOVER_API_TOKEN",
        os.environ["TELEGRAM_BOT_TOKEN_PARAM"]: "TELEGRAM_BOT_TOKEN",
        os.environ["TELEGRAM_CHAT_ID_PARAM"]: "TELEGRAM_CHAT_ID",
    }
    resp = boto3.client("ssm").get_parameters(
        Names=list(name_to_env), WithDecryption=True
    )
    for p in resp["Parameters"]:
        os.environ[name_to_env[p["Name"]]] = p["Value"]


_bootstrap_ssm_secrets()


from guardrails import (
    RATE_LIMIT,
    ChatRequest,
    ChatResponse,
    client_ip,
    limiter,
    require_internal_key,
    truncate_history,
)
from me_agent import Me

log = logging.getLogger("career_twin")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":%(message)s}',
)

_me: Me | None = None


def get_me() -> Me:
    global _me
    if _me is None:
        _me = Me()
    return _me


app = FastAPI(title="career-digital-twin-api", version="1.0.0")
app.state.limiter = limiter

allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ["*"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Content-Type", "X-Internal-Key", "X-Forwarded-For"],
    allow_credentials=False,
)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "rate limit exceeded"},
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": jsonable_encoder(exc.errors())},
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
    }


@app.post("/chat", response_model=ChatResponse)
@limiter.limit(RATE_LIMIT)
async def chat(
    request: Request,
    body: ChatRequest,
    _auth: None = Depends(require_internal_key),
):
    ip = client_ip(request)
    history = truncate_history(body.history)
    me = get_me()

    try:
        reply, tokens_used, model = await asyncio.wait_for(
            me.chat_async(body.message, history), timeout=13.0
        )
    except asyncio.TimeoutError:
        log.warning('"timeout","ip":"%s"', ip)
        raise HTTPException(status_code=504, detail="upstream timeout") from None
    except APITimeoutError:
        log.warning('"openai_timeout","ip":"%s"', ip)
        raise HTTPException(status_code=504, detail="openai timeout") from None
    except APIError as e:
        log.error('"openai_error","ip":"%s","err":"%s"', ip, str(e))
        raise HTTPException(status_code=502, detail="upstream error") from None

    return ChatResponse(reply=reply, tokens_used=tokens_used, model=model)


handler = Mangum(app, lifespan="off")
