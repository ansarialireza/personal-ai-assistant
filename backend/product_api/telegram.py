import base64
import hashlib
import logging
import secrets

import httpx
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


def _cipher():
    digest = hashlib.sha256(settings.CREDENTIAL_ENCRYPTION_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(value):
    return _cipher().encrypt(value.encode()).decode()


def decrypt_token(value):
    try:
        return _cipher().decrypt(value.encode()).decode()
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise ImproperlyConfigured("The saved Telegram credential cannot be decrypted.") from exc


def telegram_request(token, method, payload=None):
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{token}/{method}",
            json=payload or {},
            timeout=15,
            follow_redirects=False,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        raise ValueError("Telegram request failed.") from None
    if not isinstance(body, dict) or body.get("ok") is not True:
        raise ValueError("Telegram rejected the request.")
    return body.get("result")


def create_webhook_secret():
    return secrets.token_urlsafe(32)


def webhook_url(assistant_id):
    if not settings.TELEGRAM_WEBHOOK_BASE_URL:
        return ""
    return f"{settings.TELEGRAM_WEBHOOK_BASE_URL.rstrip('/')}/api/v1/webhooks/telegram/{assistant_id}/"
