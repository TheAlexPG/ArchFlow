import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.activity_log import ActivityAction, ActivityTargetType


class ActivityLogResponse(BaseModel):
    id: uuid.UUID
    target_type: ActivityTargetType
    target_id: uuid.UUID
    action: ActivityAction
    changes: dict | None = None
    user_id: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
