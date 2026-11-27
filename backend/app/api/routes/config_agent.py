from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.dependencies import AgentUser
from backend.app.db.session import get_db
from backend.app.models import ConfigAuditLog
from backend.app.schemas.config import ConfigAuditLogResponse

router = APIRouter(prefix="/agent/config", tags=["agent"])


@router.get("/audit-logs", response_model=list[ConfigAuditLogResponse])
def list_config_audit_logs(
    current_agent: AgentUser,
    session: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[ConfigAuditLogResponse]:
    logs = list(
        session.scalars(
            select(ConfigAuditLog)
            .order_by(ConfigAuditLog.created_at.desc(), ConfigAuditLog.id.desc())
            .limit(limit)
        )
    )
    return [ConfigAuditLogResponse.model_validate(log) for log in logs]
