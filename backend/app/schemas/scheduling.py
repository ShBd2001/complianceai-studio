from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import Framework, ScheduleCadence


class ScheduleCreate(BaseModel):
    cadence: ScheduleCadence


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    framework: Framework
    cadence: ScheduleCadence
    next_run_at: datetime
    last_run_audit_id: uuid.UUID | None
    is_active: bool
    created_at: datetime
