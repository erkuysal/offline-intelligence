from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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

