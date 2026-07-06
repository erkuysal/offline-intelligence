from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.users import CurrentUserRead
from app.services.roles import role_names

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=CurrentUserRead)
def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> CurrentUserRead:
    return CurrentUserRead(
        id=current_user.id,
        email=current_user.email,
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
        roles=role_names(current_user),
    )

