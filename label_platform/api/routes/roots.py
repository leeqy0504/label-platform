from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from label_platform.api.dependencies import CurrentUser, SessionDependency, require_roles
from label_platform.datasets.paths import (
    SourcePathError,
    list_safe_children,
    resolve_approved_root,
)
from label_platform.db.models import AllowedRoot, AuditEvent, User
from label_platform.domain.enums import UserRole


router = APIRouter(tags=["source roots"])
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


class SourceRootResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    path: str
    label: str
    description: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SourceRootCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)


class SourceRootUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    is_active: bool | None = None


class SourceTreeEntry(BaseModel):
    name: str
    path: str
    type: Literal["dir", "file"]


class SourceTreeResponse(BaseModel):
    path: str
    entries: list[SourceTreeEntry]


def _visible_root(
    session: Session,
    root_id: str,
    user: User,
) -> AllowedRoot:
    root = session.get(AllowedRoot, root_id)
    if root is None or (not root.is_active and user.role is not UserRole.ADMIN):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source root not found")
    return root


@router.get("/api/source-roots", response_model=list[SourceRootResponse])
def list_source_roots(session: SessionDependency, user: CurrentUser) -> list[AllowedRoot]:
    query = select(AllowedRoot)
    if user.role is not UserRole.ADMIN:
        query = query.where(AllowedRoot.is_active.is_(True))
    query = query.order_by(AllowedRoot.label, AllowedRoot.id)
    return list(session.scalars(query).all())


@router.get(
    "/api/source-roots/{root_id}/tree",
    response_model=SourceTreeResponse,
)
def browse_source_root(
    root_id: str,
    session: SessionDependency,
    user: CurrentUser,
    path: str = "",
) -> SourceTreeResponse:
    root = _visible_root(session, root_id, user)
    try:
        entries = list_safe_children(Path(root.path), path)
    except SourcePathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return SourceTreeResponse(
        path=path,
        entries=[
            SourceTreeEntry(
                name=entry.name,
                path=entry.relative_path,
                type="dir" if entry.is_directory else "file",
            )
            for entry in entries
        ],
    )


@router.post(
    "/api/admin/source-roots",
    response_model=SourceRootResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_source_root(
    payload: SourceRootCreate,
    session: SessionDependency,
    admin: AdminUser,
) -> AllowedRoot:
    submitted = Path(payload.path)
    if not submitted.is_absolute():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source root path must be absolute",
        )
    try:
        normalized = resolve_approved_root(submitted)
    except (OSError, SourcePathError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    root = AllowedRoot(
        path=str(normalized),
        label=payload.label.strip(),
        description=payload.description.strip(),
        is_active=True,
        created_by_id=admin.id,
    )
    session.add(root)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source root already exists",
        ) from exc

    session.add(
        AuditEvent(
            actor_user_id=admin.id,
            action="source_root.created",
            resource_type="source_root",
            resource_id=root.id,
            details={"path": root.path, "label": root.label},
        )
    )
    session.commit()
    session.refresh(root)
    return root


@router.patch(
    "/api/admin/source-roots/{root_id}",
    response_model=SourceRootResponse,
)
def update_source_root(
    root_id: str,
    payload: SourceRootUpdate,
    session: SessionDependency,
    admin: AdminUser,
) -> AllowedRoot:
    root = session.get(AllowedRoot, root_id)
    if root is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source root not found")

    changes: dict[str, object] = {}
    if payload.label is not None:
        root.label = payload.label.strip()
        changes["label"] = root.label
    if payload.description is not None:
        root.description = payload.description.strip()
        changes["description"] = root.description
    if payload.is_active is not None:
        root.is_active = payload.is_active
        changes["is_active"] = root.is_active

    session.add(
        AuditEvent(
            actor_user_id=admin.id,
            action="source_root.updated",
            resource_type="source_root",
            resource_id=root.id,
            details=changes,
        )
    )
    session.commit()
    session.refresh(root)
    return root
