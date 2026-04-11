from datetime import datetime
from pydantic import BaseModel


class ScheduleEntry(BaseModel):
    schedule_id: str
    locale_id: str
    lesson_name: str
    starts_at: datetime
    ends_at: datetime


class DeviceContext(BaseModel):
    lesson_name: str
    ms_remaining: int
    ms_for_next: int

    def to_payload(self) -> dict:
        return {
            "lesson_name": self.lesson_name,
            "msRemaining": self.ms_remaining,
            "msForNext": self.ms_for_next,
        }