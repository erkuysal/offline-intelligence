from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.role import Role
from app.models.user import User

DEFAULT_USER_ROLE = "user"
ADMIN_ROLE = "admin"

ROLE_DESCRIPTIONS = {
    ADMIN_ROLE: "Administrator with elevated access",
    DEFAULT_USER_ROLE: "Default authenticated user",
}


def get_or_create_role(db: Session, name: str) -> Role:
    role = db.scalar(select(Role).where(Role.name == name))
    if role is not None:
        return role

    role = Role(
        name=name,
        description=ROLE_DESCRIPTIONS.get(name),
    )
    db.add(role)
    db.flush()

    return role


def seed_default_roles(db: Session) -> None:
    get_or_create_role(db, ADMIN_ROLE)
    get_or_create_role(db, DEFAULT_USER_ROLE)


def assign_role(user: User, role: Role) -> None:
    if role not in user.roles:
        user.roles.append(role)


def role_names(user: User) -> list[str]:
    return sorted(role.name for role in user.roles)

