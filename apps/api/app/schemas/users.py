from pydantic import BaseModel


class CurrentUserRead(BaseModel):
    id: int
    email: str
    is_active: bool
    is_verified: bool
    roles: list[str]

