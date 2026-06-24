import os
from sqlmodel import SQLModel, Session, create_engine

# Em produção (Fly.io) vamos apontar DATABASE_URL pra um volume persistente,
# ex: sqlite:////data/app.db . Localmente cai num arquivo na raiz do projeto.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
