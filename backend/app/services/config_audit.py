from typing import Any

from sqlalchemy.orm import Session

from backend.app.models import ConfigAuditLog


def record_config_change(
    session: Session,
    *,
    actor_id: int | None,
    entity_type: str,
    entity_id: str | int,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    session.add(
        ConfigAuditLog(
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=str(entity_id),
            action=action,
            before_json=before,
            after_json=after,
        )
    )
