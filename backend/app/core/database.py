from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


def create_db_engine(
    database_url: URL | str,
    *,
    connect_args: dict[str, object] | None = None,
) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=3600,
        connect_args=connect_args or {},
    )


def create_session_factory(db_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=db_engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


engine = create_db_engine(
    settings.DATABASE_URL,
    connect_args=settings.DATABASE_CONNECT_ARGS,
)
SessionLocal = create_session_factory(engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped session without committing implicitly."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def dispose_engine() -> None:
    """Release all pooled database connections during application shutdown."""
    engine.dispose()
