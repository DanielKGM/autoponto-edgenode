from datetime import datetime
from pydantic import BaseModel, Field


class Sala(BaseModel):
    id: str
    nome: str


class Dispositivo(BaseModel):
    id: str
    sala_id: str
    ativo: bool = True
    status: str | None = None
    interscity_uuid: str | None = None


class Aula(BaseModel):
    id: str
    nome: str
    sala_id: str
    inicio: datetime
    fim: datetime
    status: str | None = None


class Aluno(BaseModel):
    id: str
    matricula: str
    nome: str


class MatriculaAula(BaseModel):
    aula_id: str
    aluno_id: str


class EmbeddingFacial(BaseModel):
    id: str
    aluno_id: str
    vetor: bytes


class EventoPresenca(BaseModel):
    id: str
    aluno_id: str
    aula_id: str
    dispositivo_id: str
    reconhecido_em: datetime
    score: float
    sync_status: str = "pending"


class SyncState(BaseModel):
    entity: str
    cursor: str


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


class AttendanceQueueEvent(BaseModel):
    event_id: str
    dispositivo_id: str
    aula_id: str
    aluno_id: str
    score: float
    recognized_at: datetime


class SyncDeletedPayload(BaseModel):
    salas: list[str] = Field(default_factory=list)
    dispositivos: list[str] = Field(default_factory=list)
    aulas: list[str] = Field(default_factory=list)
    alunos: list[str] = Field(default_factory=list)
    matriculas_aula: list[MatriculaAula] = Field(default_factory=list)
    embeddings_faciais: list[str] = Field(default_factory=list)


class SyncPullData(BaseModel):
    salas: list[Sala] = Field(default_factory=list)
    dispositivos: list[Dispositivo] = Field(default_factory=list)
    aulas: list[Aula] = Field(default_factory=list)
    alunos: list[Aluno] = Field(default_factory=list)
    matriculas_aula: list[MatriculaAula] = Field(default_factory=list)
    embeddings_faciais: list[EmbeddingFacial] = Field(default_factory=list)


class SyncPullPayload(BaseModel):
    data: SyncPullData = Field(default_factory=SyncPullData)
    deleted: SyncDeletedPayload = Field(default_factory=SyncDeletedPayload)
    cursors: dict[str, str] = Field(default_factory=dict)
