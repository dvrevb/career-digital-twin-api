import os

import requests


def push(text: str) -> None:
    if os.getenv("USE_TELEGRAM_NOTIFICATIONS", "").lower() == "true":
        push_telegram(text)
    else:
        push_pushover(text)

def push_pushover(text: str) -> None:
    token = os.getenv("PUSHOVER_API_TOKEN")
    user = os.getenv("PUSHOVER_USER_KEY")
    if not token or not user:
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": token, "user": user, "message": text},
            timeout=5,
        )
    except requests.RequestException:
        pass

def push_telegram(text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text},
            timeout=5,
        )
    except requests.RequestException:
        pass
