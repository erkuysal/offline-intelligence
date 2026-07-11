from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User
from app.security.tokens import create_refresh_token

client = TestClient(app)
pytestmark = pytest.mark.usefixtures("clean_database")


def unique_email() -> str:
    return f"user-{uuid4().hex}@example.com"


def test_register_user() -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": unique_email(),
            "password": "correct-horse-battery-staple",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"].endswith("@example.com")
    assert body["is_active"] is True
    assert body["is_verified"] is False
    assert "password_hash" not in body


def test_register_duplicate_email_is_rejected() -> None:
    email = unique_email()
    payload = {
        "email": email,
        "password": "correct-horse-battery-staple",
    }

    first_response = client.post("/api/v1/auth/register", json=payload)
    second_response = client.post("/api/v1/auth/register", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 409


def test_login_returns_access_token() -> None:
    email = unique_email()
    password = "correct-horse-battery-staple"
    client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
        },
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


def test_refresh_returns_new_token_pair() -> None:
    email = unique_email()
    password = "correct-horse-battery-staple"
    client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
        },
    )
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    response = client.post(
        "/api/v1/auth/refresh",
        json={
            "refresh_token": login_response.json()["refresh_token"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["access_token"] != login_response.json()["access_token"]
    assert body["refresh_token"] != login_response.json()["refresh_token"]


def test_refresh_rejects_access_token() -> None:
    email = unique_email()
    password = "correct-horse-battery-staple"
    client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
        },
    )
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    response = client.post(
        "/api/v1/auth/refresh",
        json={
            "refresh_token": login_response.json()["access_token"],
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid refresh token"
    assert response.headers["www-authenticate"] == "Bearer"


def test_refresh_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    email = unique_email()
    register_response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery-staple"},
    )
    settings = get_settings()
    monkeypatch.setattr(settings, "jwt_refresh_token_expire_minutes", -1)
    expired_token = create_refresh_token(subject=str(register_response.json()["id"]))

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": expired_token},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid refresh token"
    assert response.headers["www-authenticate"] == "Bearer"


def test_refresh_rejects_inactive_user() -> None:
    email = unique_email()
    password = "correct-horse-battery-staple"
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        user.is_active = False
        db.commit()

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login_response.json()["refresh_token"]},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid refresh token"
    assert response.headers["www-authenticate"] == "Bearer"


def test_login_rejects_wrong_password() -> None:
    email = unique_email()
    client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "correct-horse-battery-staple",
        },
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": "wrong-password",
        },
    )

    assert response.status_code == 401
