from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from label_platform.auth.sessions import SESSION_COOKIE, read_session_token
from label_platform.db.models import User
from label_platform.domain.enums import UserRole


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


def current_user(request: Request, session: SessionDependency) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    settings = request.app.state.settings
    user_id = read_session_token(
        settings.session_secret,
        token,
        settings.session_max_age_seconds,
    )
    user = session.get(User, user_id) if user_id is not None else None
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_roles(*roles: UserRole) -> Callable[[CurrentUser], User]:
    def check_roles(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return check_roles
