import logging
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def is_configured() -> bool:
    return bool(
        getattr(settings, "TURNSTILE_ENABLED", False)
        and settings.TURNSTILE_SITE_KEY
        and settings.TURNSTILE_SECRET_KEY
    )


def verify_turnstile(response_token: Optional[str], remote_ip: Optional[str] = None) -> bool:
    """
    Validate the Turnstile token with Cloudflare.
    Returns True when the challenge succeeds or Turnstile is disabled.
    """
    if not is_configured():
        return True

    if not response_token:
        logger.warning("Missing Turnstile response token.")
        return False

    payload = {
        "secret": settings.TURNSTILE_SECRET_KEY,
        "response": response_token,
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        resp = requests.post(VERIFY_URL, data=payload, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        success = data.get("success", False)
        if not success:
            logger.warning("Turnstile verification failed: %s", data)
        return success
    except requests.RequestException as exc:  # pragma: no cover - network
        logger.error("Turnstile verification error: %s", exc)
        return False
