from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from label_platform.api.dependencies import SessionDependency
from label_platform.db.models import AuditEvent


router = APIRouter(prefix="/api/admin", tags=["administration"])


class ConnectorStatus(BaseModel):
    url: str
    version: str
    status: str
    api_key_configured: bool


class SystemConfigResponse(BaseModel):
    label_studio: ConnectorStatus
    unitrain: ConnectorStatus


class AuditEventResponse(BaseModel):
    id: str
    action: str
    resource_type: str
    resource_id: str
    resource_name: str
    timestamp: datetime
    details: dict[str, Any]


@router.get("/system-config", response_model=SystemConfigResponse)
def get_system_config(request: Request) -> SystemConfigResponse:
    settings = request.app.state.settings
    return SystemConfigResponse(
        label_studio=ConnectorStatus(
            url=settings.label_studio_url,
            version="",
            status="checking",
            api_key_configured=bool(settings.label_studio_api_token),
        ),
        unitrain=ConnectorStatus(
            url=settings.unitrain_url,
            version="",
            status="checking",
            api_key_configured=bool(settings.unitrain_api_token),
        ),
    )


@router.get("/audit-events")
def list_audit_events(
    session: SessionDependency,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    total = session.scalar(select(func.count()).select_from(AuditEvent)) or 0
    events = session.scalars(
        select(AuditEvent)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": [_audit_response(event).model_dump() for event in events],
        "meta": {"page": page, "page_size": page_size, "total": total},
    }


def _audit_response(event: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse(
        id=event.id,
        action=event.action,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        resource_name=event.resource_id,
        timestamp=event.created_at,
        details=event.details,
    )
