from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any


TOKEN_TTL_HOURS = int(os.getenv("JARVIX_TOKEN_TTL_HOURS", "720"))


def _secret() -> str:
    secret = os.getenv("JARVIX_SECRET_KEY") or os.getenv("SECRET_KEY")
    if secret:
        return secret
    if os.getenv("RENDER"):
        raise RuntimeError("Configure JARVIX_SECRET_KEY na Render.")
    return "jarvix-dev-secret-change-me"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, salt, expected = password_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240_000)
    return hmac.compare_digest(digest.hex(), expected)


def create_access_token(user: dict[str, Any]) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)
    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "name": user["name"],
        "exp": int(expires_at.timestamp()),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    head = _b64(json.dumps(header, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = _sign(f"{head}.{body}")
    return f"{head}.{body}.{signature}"


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        head, body, signature = token.split(".", 2)
    except ValueError:
        return None
    expected = _sign(f"{head}.{body}")
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        return None
    return payload


def _sign(value: str) -> str:
    digest = hmac.new(_secret().encode(), value.encode(), hashlib.sha256).digest()
    return _b64(digest)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
