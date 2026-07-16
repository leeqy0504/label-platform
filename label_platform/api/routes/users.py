from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from label_platform.api.dependencies import SessionDependency, require_roles
from label_platform.auth.passwords import hash_password
from label_platform.db.models import User
from label_platform.domain.enums import UserRole


router = APIRouter(prefix="/api/admin/users", tags=["users"])
AdminUser = Depends(require_roles(UserRole.ADMIN))


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str
    role: UserRole
    is_active: bool


class UserCreate(BaseModel):
    email: str
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=512)
    role: UserRole

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized:
            raise ValueError("Invalid email address")
        return normalized


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: UserRole | None = None
    is_active: bool | None = None


@router.get("", response_model=list[UserResponse], dependencies=[AdminUser])
def list_users(session: SessionDependency) -> list[User]:
    return list(session.scalars(select(User).order_by(User.created_at)).all())


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[AdminUser],
)
def create_user(payload: UserCreate, session: SessionDependency) -> User:
    user = User(
        email=payload.email,
        name=payload.name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists") from exc
    session.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserResponse, dependencies=[AdminUser])
def update_user(user_id: str, payload: UserUpdate, session: SessionDependency) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    removes_active_admin = user.role is UserRole.ADMIN and user.is_active and (
        payload.is_active is False
        or (payload.role is not None and payload.role is not UserRole.ADMIN)
    )
    if removes_active_admin:
        active_admins = session.scalar(
            select(func.count()).select_from(User).where(
                User.role == UserRole.ADMIN,
                User.is_active.is_(True),
            )
        )
        if active_admins == 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="At least one active administrator is required",
            )

    if payload.name is not None:
        user.name = payload.name
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    session.commit()
    session.refresh(user)
    return user
