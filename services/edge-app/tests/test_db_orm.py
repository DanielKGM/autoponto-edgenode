from datetime import datetime, timedelta

import msgpack
from sqlalchemy import func, inspect, select

from app import db
from app.db_models import Aluno, Aula, EmbeddingFacial, EventoPresenca, MatriculaAula
from app.db_models import Dispositivo, Sala, SyncState
from app.repository import TZ, compute_context_for_device, save_attendance_event
from app.sync import _current_cursors, _mark_synced, _pending_attendance
from app.sync import apply_pull_payload


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _base_payload(now: datetime | None = None) -> dict:
    now = now or datetime.now(TZ)
    return {
        "data": {
            "salas": [{"id": "sala-1", "nome": "Lab 1"}],
            "dispositivos": [
                {
                    "id": "disp-1",
                    "sala_id": "sala-1",
                    "ativo": True,
                    "status": "online",
                    "interscity_uuid": "uuid-1",
                }
            ],
            "aulas": [
                {
                    "id": "aula-1",
                    "nome": "Calculo",
                    "sala_id": "sala-1",
                    "inicio": _iso(now - timedelta(minutes=10)),
                    "fim": _iso(now + timedelta(minutes=10)),
                    "status": "ABERTA",
                }
            ],
            "alunos": [{"id": "aluno-1", "matricula": "2024001", "nome": "Ana Silva"}],
            "matriculas_aula": [{"aula_id": "aula-1", "aluno_id": "aluno-1"}],
            "embeddings_faciais": [
                {"id": "emb-1", "aluno_id": "aluno-1", "vetor": [0.1, 0.2, 0.3]}
            ],
        },
        "cursors": {"salas": "1", "aulas": "1", "ignored": "x"},
    }


def test_init_db_creates_expected_tables_indices_and_pragmas():
    inspector = inspect(db.engine)

    assert {
        "salas",
        "dispositivos",
        "aulas",
        "alunos",
        "matriculas_aula",
        "embeddings_faciais",
        "eventos_presenca",
        "sync_state",
    }.issubset(set(inspector.get_table_names()))

    aula_indices = {index["name"] for index in inspector.get_indexes("aulas")}
    embedding_indices = {
        index["name"] for index in inspector.get_indexes("embeddings_faciais")
    }
    evento_indices = {index["name"] for index in inspector.get_indexes("eventos_presenca")}

    assert "idx_aulas_sala_tempo" in aula_indices
    assert "idx_embeddings_aluno" in embedding_indices
    assert "idx_eventos_presenca_sync" in evento_indices
    assert "idx_eventos_presenca_aluno_aula" in evento_indices

    with db.engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


def test_apply_pull_payload_upserts_deletes_cascades_and_stores_cursors():
    apply_pull_payload(_base_payload())
    apply_pull_payload(
        {
            "data": {
                "alunos": [
                    {
                        "id": "aluno-1",
                        "matricula": "2024001",
                        "nome": "Ana Souza",
                    }
                ],
                "matriculas_aula": [
                    {"aula_id": "aula-1", "aluno_id": "aluno-1"},
                    {"aula_id": "aula-1", "aluno_id": "aluno-1"},
                ],
                "embeddings_faciais": [
                    {"id": "emb-1", "aluno_id": "aluno-1", "vetor": [9.0, 8.0]}
                ],
            },
            "cursors": {"alunos": "2"},
        }
    )

    with db.SessionLocal() as session:
        assert session.get(Aluno, "aluno-1").nome == "Ana Souza"
        assert session.scalar(select(func.count()).select_from(MatriculaAula)) == 1

        embedding = session.get(EmbeddingFacial, "emb-1")
        unpacked = msgpack.unpackb(embedding.vetor, raw=False)
        assert unpacked["shape"] == [1, 2]
        assert unpacked["data"] == [9.0, 8.0]

    assert _current_cursors() == {"salas": "1", "aulas": "1", "alunos": "2"}

    apply_pull_payload({"data": {}, "deleted": {"aulas": ["aula-1"]}})
    with db.SessionLocal() as session:
        assert session.get(Aula, "aula-1") is None
        assert session.scalar(select(func.count()).select_from(MatriculaAula)) == 0


def test_attendance_event_is_idempotent_pending_and_markable_as_synced():
    apply_pull_payload(_base_payload())

    first = save_attendance_event(
        {
            "eventId": "event-1",
            "alunoId": "aluno-1",
            "aulaId": "aula-1",
            "dispositivoId": "disp-1",
            "recognizedAt": "2026-06-20T12:00:00Z",
            "score": 0.95,
        }
    )
    second = save_attendance_event(
        {
            "eventId": "event-duplicate",
            "alunoId": "aluno-1",
            "aulaId": "aula-1",
            "dispositivoId": "disp-1",
            "recognizedAt": "2026-06-20T12:01:00Z",
            "score": 0.5,
        }
    )

    assert first["id"] == "event-1"
    assert first["is_new"] is True
    assert first["aluno_nome"] == "Ana Silva"
    assert second["id"] == "event-1"
    assert second["is_new"] is False

    pending = _pending_attendance()
    assert [event["id"] for event in pending] == ["event-1"]

    _mark_synced(["event-1"])
    assert _pending_attendance() == []
    with db.SessionLocal() as session:
        assert session.get(EventoPresenca, "event-1").sync_status == "synced"


def test_context_handles_active_inactive_next_and_ignored_statuses():
    now = datetime.now(TZ)
    apply_pull_payload(
        {
            "data": {
                "salas": [{"id": "sala-1", "nome": "Lab 1"}],
                "dispositivos": [
                    {"id": "disp-1", "sala_id": "sala-1", "ativo": True},
                    {"id": "disp-2", "sala_id": "sala-1", "ativo": False},
                ],
                "aulas": [
                    {
                        "id": "aula-fechada",
                        "nome": "Fechada",
                        "sala_id": "sala-1",
                        "inicio": _iso(now - timedelta(minutes=10)),
                        "fim": _iso(now + timedelta(minutes=10)),
                        "status": "FECHADA",
                    },
                    {
                        "id": "aula-proxima",
                        "nome": "Fisica",
                        "sala_id": "sala-1",
                        "inicio": _iso(now + timedelta(minutes=20)),
                        "fim": _iso(now + timedelta(minutes=50)),
                        "status": "ABERTA",
                    },
                ],
            }
        }
    )

    inactive_context = compute_context_for_device("disp-2")
    assert inactive_context.aula_nome == ""
    assert inactive_context.sala_id is None

    next_context = compute_context_for_device("disp-1")
    assert next_context.aula_nome == "Fisica"
    assert next_context.ms_remaining == 0
    assert next_context.ms_for_next > 0

    apply_pull_payload(
        {
            "data": {
                "aulas": [
                    {
                        "id": "aula-atual",
                        "nome": "Programacao",
                        "sala_id": "sala-1",
                        "inicio": _iso(now - timedelta(minutes=5)),
                        "fim": _iso(now + timedelta(minutes=5)),
                        "status": "ABERTA",
                    }
                ]
            }
        }
    )

    current_context = compute_context_for_device("disp-1")
    assert current_context.aula_nome == "Programacao"
    assert current_context.ms_remaining > 0
    assert current_context.ms_for_next == 0


def test_base_tables_can_be_read_with_orm_models():
    apply_pull_payload(_base_payload())
    with db.SessionLocal() as session:
        assert session.get(Sala, "sala-1").nome == "Lab 1"
        assert session.get(Dispositivo, "disp-1").ativo is True
        assert session.get(SyncState, "salas").cursor == "1"
