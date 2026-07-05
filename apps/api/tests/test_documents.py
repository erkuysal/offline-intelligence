from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def get_access_token() -> str:
    email = f"document-user-{uuid4().hex}@example.com"
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
    return response.json()["access_token"]


def test_list_documents_requires_authentication() -> None:
    response = client.get("/api/v1/documents")

    assert response.status_code == 401


def test_list_documents_for_authenticated_user() -> None:
    token = get_access_token()

    response = client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == []

