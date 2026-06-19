from datetime import datetime
from pydantic import BaseModel


class Aula(BaseModel):
    id: str
    nome: str
    sala_id: str
    inicio: datetime
    fim: datetime
    status: str | None = None


class DeviceContext(BaseModel):
    aula_nome: str
    ms_remaining: int
    ms_for_next: int
    aula_id: str | None = None
    sala_id: str | None = None

    def to_payload(self) -> dict:
        return {
            "lesson_name": self.aula_nome,
            "msRemaining": self.ms_remaining,
            "msForNext": self.ms_for_next,
        }


class FrameQueueItem(BaseModel):
    dispositivo_id: str
    sala_id: str
    aula_id: str
    received_at: datetime
    frame: bytes

    def to_queue_payload(self) -> dict:
        return {
            "dispositivoId": self.dispositivo_id,
            "salaId": self.sala_id,
            "aulaId": self.aula_id,
            "receivedAt": self.received_at.isoformat(),
            "frame": self.frame,
        }
