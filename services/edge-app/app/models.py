from datetime import datetime
from pydantic import BaseModel, Field


class Locale(BaseModel):
    id: str
    name: str


class Device(BaseModel):
    id: str
    locale_id: str
    active: bool = True
    status: str | None = None


class Lesson(BaseModel):
    id: str
    name: str
    locale_id: str
    starts_at: datetime
    ends_at: datetime
    status: str | None = None


class Student(BaseModel):
    id: str
    registration: str
    name: str
    active: bool = True


class Enrollment(BaseModel):
    lesson_id: str
    student_id: str


class FaceEmbedding(BaseModel):
    id: str
    student_id: str
    embedding: bytes


class AttendanceEvent(BaseModel):
    id: str
    student_id: str
    lesson_id: str
    device_id: str
    recognized_at: datetime
    score: float
    sync_status: str = "pending"


class SyncState(BaseModel):
    entity: str
    cursor: str


class DeviceContext(BaseModel):
    lesson_name: str
    ms_remaining: int
    ms_for_next: int
    lesson_id: str | None = None
    locale_id: str | None = None

    def to_payload(self) -> dict:
        return {
            "lesson_name": self.lesson_name,
            "msRemaining": self.ms_remaining,
            "msForNext": self.ms_for_next,
        }


class FrameQueueItem(BaseModel):
    device_id: str
    locale_id: str
    lesson_id: str
    received_at: datetime
    frame: bytes

    def to_queue_payload(self) -> dict:
        return {
            "deviceId": self.device_id,
            "localeId": self.locale_id,
            "lessonId": self.lesson_id,
            "receivedAt": self.received_at.isoformat(),
            "frame": self.frame,
        }


class AttendanceQueueEvent(BaseModel):
    event_id: str
    device_id: str
    lesson_id: str
    student_id: str
    score: float
    recognized_at: datetime


class SyncDeletedPayload(BaseModel):
    locales: list[str] = Field(default_factory=list)
    devices: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    students: list[str] = Field(default_factory=list)
    enrollments: list[Enrollment] = Field(default_factory=list)
    face_embeddings: list[str] = Field(default_factory=list)


class SyncPullData(BaseModel):
    locales: list[Locale] = Field(default_factory=list)
    devices: list[Device] = Field(default_factory=list)
    lessons: list[Lesson] = Field(default_factory=list)
    students: list[Student] = Field(default_factory=list)
    enrollments: list[Enrollment] = Field(default_factory=list)
    face_embeddings: list[FaceEmbedding] = Field(default_factory=list)


class SyncPullPayload(BaseModel):
    data: SyncPullData = Field(default_factory=SyncPullData)
    deleted: SyncDeletedPayload = Field(default_factory=SyncDeletedPayload)
    cursors: dict[str, str] = Field(default_factory=dict)
