from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ConfigAuditLogResponse(BaseModel):
    id: int
    actor_id: int | None
    entity_type: str
    entity_id: str
    action: str
    before_json: dict | None
    after_json: dict | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
