"""
SQLite en modo WAL: permite lecturas concurrentes mientras alguien escribe.
Sin WAL, con varios usuarios aparecen errores de "database is locked".
"""
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_settings = get_settings()

engine = create_engine(
    f"sqlite:///{_settings.db_path}",
    connect_args={"check_same_thread": False, "timeout": 15},
    future=True,
)


@event.listens_for(engine, "connect")
def _pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")      # lecturas concurrentes con escrituras
    cur.execute("PRAGMA synchronous=NORMAL")    # buen equilibrio durabilidad/velocidad en WAL
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=15000")    # espera en vez de fallar si hay lock
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    """Dependencia de FastAPI: abre y cierra la sesión por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (registra los modelos)
    models.Base.metadata.create_all(engine)
