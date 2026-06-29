from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
import secrets
from typing import Any

from app.core.config import settings

_JWT_ALGORITHM = "HS256"
_PASSWORD_ALGORITHM = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 600_000
_UNUSABLE_PASSWORD_PREFIX = "oauth2_unusable$"


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PASSWORD_ITERATIONS,
    ).hex()
    return f"{_PASSWORD_ALGORITHM}${_PASSWORD_ITERATIONS}${salt}${digest}"


def create_unusable_password_hash() -> str:
    return f"{_UNUSABLE_PASSWORD_PREFIX}{secrets.token_hex(32)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected_digest = password_hash.split("$", 3)
        if algorithm != _PASSWORD_ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations_text),
        ).hex()
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(digest, expected_digest)


def _base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def create_access_token(subject: int, role: str, expires_delta: timedelta | None = None) -> str:
    now = datetime.now(UTC)
    expires_at = now + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    header = {"alg": _JWT_ALGORITHM, "typ": "JWT"}
    payload = {
        "sub": str(subject),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    signing_input = ".".join(
        [
            _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_base64url_encode(signature)}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".", 2)
    except ValueError as exc:
        raise ValueError("Invalid token format") from exc

    signing_input = f"{encoded_header}.{encoded_payload}"
    expected_signature = hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    actual_signature = _base64url_decode(encoded_signature)
    if not hmac.compare_digest(expected_signature, actual_signature):
        raise ValueError("Invalid token signature")

    payload = json.loads(_base64url_decode(encoded_payload))
    expires_at = payload.get("exp")
    if not isinstance(expires_at, int) or expires_at < int(datetime.now(UTC).timestamp()):
        raise ValueError("Token expired")
    return payload
