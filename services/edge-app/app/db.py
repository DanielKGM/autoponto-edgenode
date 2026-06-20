from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import SQLITE_PATH as DEFAULT_SQLITE_PATH


class Base(DeclarativeBase):
    pass


SQLITE_PATH = DEFAULT_SQLITE_PATH


def _url_sqlite(sqlite_path: Path) -> str:
    return f"sqlite:///{sqlite_path}"


def _criar_engine(sqlite_path: Path) -> Engine:
    return create_engine(
        _url_sqlite(sqlite_path),
        connect_args={"check_same_thread": False},
    )


@event.listens_for(Engine, "connect")
def _configurar_pragmas_sqlite(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


engine = _criar_engine(SQLITE_PATH)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def configurar_banco(sqlite_path: Path) -> None:
    global SQLITE_PATH, engine

    SQLITE_PATH = Path(sqlite_path)
    engine.dispose()
    engine = _criar_engine(SQLITE_PATH)
    SessionLocal.configure(bind=engine)


def inicializar_banco() -> None:
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    from app import db_models  # noqa: F401

    Base.metadata.create_all(engine)


@contextmanager
def escopo_sessao() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
