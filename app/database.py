import os
import secrets

from sqlmodel import SQLModel, Session, create_engine

# Em produção (Fly.io) vamos apontar DATABASE_URL pra um volume persistente,
# ex: sqlite:////data/app.db . Localmente cai num arquivo na raiz do projeto.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def run_light_migrations() -> None:
    """Migrações leves e idempotentes (SQLite).

    `create_all` cria tabelas novas, mas NÃO adiciona colunas a tabelas que já
    existem. Como há um `app.db` em produção, adicionamos as colunas novas via
    `ALTER TABLE ADD COLUMN` (guardado por `PRAGMA table_info`) e geramos
    `ingest_token` para usuários que ainda não têm. Sem Alembic, no estilo do projeto.
    """
    if not DATABASE_URL.startswith("sqlite"):
        return  # PRAGMA é específico do SQLite; em Postgres usar migração própria
    with engine.begin() as conn:
        act_cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(activity)").fetchall()}
        if "source" not in act_cols:
            conn.exec_driver_sql("ALTER TABLE activity ADD COLUMN source VARCHAR DEFAULT 'fit'")
        if "external_id" not in act_cols:
            conn.exec_driver_sql("ALTER TABLE activity ADD COLUMN external_id VARCHAR")

        user_cols = {r[1] for r in conn.exec_driver_sql('PRAGMA table_info("user")').fetchall()}
        if "ingest_token" not in user_cols:
            conn.exec_driver_sql('ALTER TABLE "user" ADD COLUMN ingest_token VARCHAR')

        rows = conn.exec_driver_sql('SELECT id FROM "user" WHERE ingest_token IS NULL').fetchall()
        for (uid,) in rows:
            conn.exec_driver_sql(
                'UPDATE "user" SET ingest_token = ? WHERE id = ?',
                (secrets.token_urlsafe(32), uid),
            )


def get_session():
    with Session(engine) as session:
        yield session
