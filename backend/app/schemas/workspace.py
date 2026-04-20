from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class WorkspaceResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    slug: str
    role: str  # current user's role within this workspace
    created_at: datetime

    model_config = {"from_attributes": True}
