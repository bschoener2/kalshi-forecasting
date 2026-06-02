import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session


def get_db_url() -> str:
    return (
        f"postgresql+psycopg2://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@{os.environ['POSTGRES_HOST']}:"
        f"{os.environ.get('POSTGRES_PORT', '5432')}/{os.environ['POSTGRES_DB']}"
    )


def make_engine():
    return create_engine(get_db_url(), pool_pre_ping=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine)


def get_session() -> Session:
    return SessionLocal()
