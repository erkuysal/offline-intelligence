from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies.auth import require_roles
from app.models.user import User
from app.services.roles import ADMIN_ROLE

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health")
def admin_health(
    current_user: Annotated[User, Depends(require_roles(ADMIN_ROLE))],
) -> dict[str, str | int]:
    return {
        "status": "healthy",
        "user_id": current_user.id,
    }

