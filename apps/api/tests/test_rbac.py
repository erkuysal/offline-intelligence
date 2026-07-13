from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.main import app
from app.models.role import Role
from app.models.user import User
from app.services.roles import ADMIN_ROLE, assign_role, get_or_create_role, seed_default_roles

client = TestClient(app)
pytestmark = pytest.mark.usefixtures("clean_database")


def create_user_token() -> tuple[str, str]:
    email = f"rbac-user-{uuid4().hex}@example.com"
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
    return email, response.json()["access_token"]


def promote_to_admin(email: str) -> None:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        admin_role = get_or_create_role(db, ADMIN_ROLE)
        assign_role(user, admin_role)
        db.commit()
    finally:
        db.close()


def test_users_me_requires_authentication() -> None:
    response = client.get("/api/v1/users/me")

    assert response.status_code == 401


def test_default_role_seeding_is_safe_for_parallel_first_requests() -> None:
    barrier = Barrier(2)

    def seed_roles() -> None:
        with SessionLocal() as db:
            barrier.wait()
            seed_default_roles(db)
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(seed_roles) for _ in range(2)]
        for future in futures:
            future.result()

    with SessionLocal() as db:
        roles = db.scalars(select(Role).order_by(Role.name)).all()
        assert [role.name for role in roles] == ["admin", "user"]


def test_users_me_returns_current_user_with_roles() -> None:
    email, token = create_user_token()

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == email
    assert body["roles"] == ["user"]


def test_admin_health_rejects_normal_user() -> None:
    _, token = create_user_token()

    response = client.get(
        "/api/v1/admin/health",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_admin_health_allows_admin_user() -> None:
    email, token = create_user_token()
    promote_to_admin(email)

    response = client.get(
        "/api/v1/admin/health",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
