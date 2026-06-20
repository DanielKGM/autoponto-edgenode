from sqlalchemy import Boolean, ForeignKey, Index, LargeBinary, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Sala(Base):
    __tablename__ = "salas"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    nome: Mapped[str] = mapped_column(Text, nullable=False)


class Dispositivo(Base):
    __tablename__ = "dispositivos"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    codigo: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    sala_id: Mapped[str] = mapped_column(ForeignKey("salas.id"), nullable=False)
    ativo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )
    interscity_uuid: Mapped[str | None] = mapped_column(Text)


class Aula(Base):
    __tablename__ = "aulas"
    __table_args__ = (
        Index("idx_aulas_sala_tempo", "sala_id", "inicio", "fim"),
        Index("idx_aulas_turma", "turma_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    turma_id: Mapped[str] = mapped_column(String, nullable=False)
    sala_id: Mapped[str] = mapped_column(ForeignKey("salas.id"), nullable=False)
    inicio: Mapped[str] = mapped_column(Text, nullable=False)
    fim: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(Text)


class Aluno(Base):
    __tablename__ = "alunos"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    matricula: Mapped[str] = mapped_column(Text, nullable=False)
    nome: Mapped[str] = mapped_column(Text, nullable=False)


class MatriculaTurma(Base):
    __tablename__ = "matriculas_turma"
    __table_args__ = (
        Index("idx_matriculas_turma_turma", "turma_id"),
        Index("idx_matriculas_turma_aluno", "aluno_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    turma_id: Mapped[str] = mapped_column(String, nullable=False)
    aluno_id: Mapped[str] = mapped_column(
        ForeignKey("alunos.id", ondelete="CASCADE"),
        nullable=False,
    )


class EmbeddingFacial(Base):
    __tablename__ = "embeddings_faciais"
    __table_args__ = (Index("idx_embeddings_aluno", "aluno_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    aluno_id: Mapped[str] = mapped_column(
        ForeignKey("alunos.id", ondelete="CASCADE"),
        nullable=False,
    )
    vetor: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class EventoPresenca(Base):
    __tablename__ = "eventos_presenca"
    __table_args__ = (
        Index("idx_eventos_presenca_sync", "sync_status"),
        Index("idx_eventos_presenca_aluno_aula", "aluno_id", "aula_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    aluno_id: Mapped[str] = mapped_column(String, nullable=False)
    aula_id: Mapped[str] = mapped_column(String, nullable=False)
    dispositivo_id: Mapped[str] = mapped_column(String, nullable=False)
    reconhecido_em: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(nullable=False)
    sync_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )


class SyncState(Base):
    __tablename__ = "sync_state"

    entity: Mapped[str] = mapped_column(String, primary_key=True)
    cursor: Mapped[str] = mapped_column(Text, nullable=False)
