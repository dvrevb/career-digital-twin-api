import os

import requests


def push(text: str) -> None:
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
