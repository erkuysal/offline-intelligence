import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.config import get_settings


class TokenError(ValueError):
    pass


def create_access_token(subject: str) -> str:
    settings = get_settings()
    return _create_token(
        subject=subject,
        token_type="access",
        expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes),
        secret_key=settings.jwt_secret_key,
    )


def create_refresh_token(subject: str) -> str:
    settings = get_settings()
    return _create_token(
        subject=subject,
        token_type="refresh",
        expires_delta=timedelta(minutes=settings.jwt_refresh_token_expire_minutes),
        secret_key=settings.jwt_secret_key,
    )


def _create_token(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    secret_key: str,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": uuid4().hex,
        "typ": token_type,
    }
    return _encode_jwt(payload, secret_key)


def decode_access_token(token: str) -> dict[str, Any]:
    return _decode_token(token, expected_type="access")


def decode_refresh_token(token: str) -> dict[str, Any]:
    return _decode_token(token, expected_type="refresh")


def _decode_token(token: str, expected_type: str) -> dict[str, Any]:
    settings = get_settings()
    payload = _decode_jwt(token, settings.jwt_secret_key)
    expires_at = payload.get("exp")
    if not isinstance(expires_at, int) or expires_at < int(datetime.now(UTC).timestamp()):
        raise TokenError("Token has expired")

    if payload.get("typ") != expected_type:
        raise TokenError("Invalid token type")

    return payload


def _encode_jwt(payload: dict[str, Any], secret_key: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join(
        [
            _base64url_json(header),
            _base64url_json(payload),
        ]
    )
    signature = _sign(signing_input, secret_key)
    return f"{signing_input}.{signature}"


def _decode_jwt(token: str, secret_key: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenError("Malformed token")

    signing_input = ".".join(parts[:2])
    expected_signature = _sign(signing_input, secret_key)
    if not hmac.compare_digest(parts[2], expected_signature):
        raise TokenError("Invalid token signature")

    header = _base64url_decode_json(parts[0])
    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise TokenError("Unsupported token header")

    return _base64url_decode_json(parts[1])


def _sign(signing_input: str, secret_key: str) -> str:
    signature = hmac.new(
        secret_key.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return _base64url_encode(signature)


def _base64url_json(value: dict[str, Any]) -> str:
    return _base64url_encode(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )


def _base64url_decode_json(value: str) -> dict[str, Any]:
    try:
        decoded = base64.urlsafe_b64decode(_add_base64_padding(value)).decode("utf-8")
        result = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        raise TokenError("Invalid token payload") from exc

    if not isinstance(result, dict):
        raise TokenError("Invalid token payload")

    return result


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _add_base64_padding(value: str) -> bytes:
    return (value + "=" * (-len(value) % 4)).encode("ascii")
