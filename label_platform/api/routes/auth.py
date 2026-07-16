from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from label_platform.api.dependencies import CurrentUser, SessionDependency
from label_platform.auth.passwords import verify_password
from label_platform.auth.sessions import SESSION_COOKIE, create_session_token
from label_platform.db.models import User
from label_platform.domain.enums import UserRole


router = APIRouter(prefix="/api/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str
    role: UserRole
    is_active: bool


@router.post("/login", response_model=UserResponse)
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    session: SessionDependency,
) -> User:
    email = payload.email.strip().lower()
    user = session.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    user.last_login_at = datetime.now(timezone.utc)
    session.commit()
    settings = request.app.state.settings
    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_session_token(settings.session_secret, user.id),
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path="/",
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/", httponly=True, samesite="strict")


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> User:
    return user
