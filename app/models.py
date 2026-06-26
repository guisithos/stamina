from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    hashed_password: str
    # token usado pela ingestão automática (Health Auto Export) p/ identificar o
    # usuário sem cookie de sessão. Gerado no cadastro; revogável (regenerável).
    ingest_token: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Activity(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="user.id")

    # Origem do dado: "fit" (upload manual) ou "hae" (Health Auto Export).
    source: str = Field(default="fit")
    # ID do treino na origem (UUID do Apple Health via HAE) — chave de idempotência:
    # evita duplicar a mesma atividade quando o HAE reenvia janelas sobrepostas.
    external_id: Optional[str] = Field(default=None, index=True)

    # Classificação
    sport: str  # valor cru do FIT, ex: "running", "cycling", "training"
    sub_sport: Optional[str] = None
    label: str  # nome amigável já resolvido, ex: "Corrida", "Musculação"

    # Tempo
    start_time: datetime
    total_time_s: float  # segundos (total_timer_time)

    # Métricas principais (todas as atividades)
    avg_hr: Optional[int] = None
    min_hr: Optional[int] = None
    max_hr: Optional[int] = None
    calories: Optional[int] = None

    # Métricas de atividades externas
    distance_m: Optional[float] = None
    total_ascent_m: Optional[float] = None
    total_descent_m: Optional[float] = None
    has_gps: bool = False

    # Pontos do percurso (lat/lon/altitude/hr/timestamp por amostra),
    # guardados como JSON serializado em texto — simples para o MVP.
    # Quando o volume de dados crescer, isso migra pra uma tabela própria.
    track_points_json: Optional[str] = None

    # Registro subjetivo do treino (preenchido manualmente no detalhe).
    rpe: Optional[int] = None      # esforço percebido (0–10); RIR ≈ 10 - rpe
    note: Optional[str] = None     # nota livre: como foi, o que foi feito

    raw_filename: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrengthSet(SQLModel, table=True):
    """Uma série registrada numa atividade de musculação.

    1 linha = 1 série (ex.: Supino reto, 10 reps, 40 kg). Várias séries do mesmo
    exercício são agrupadas na exibição. O exercício referencia o catálogo em
    `app/strength.py`, que mapeia exercício -> músculos para o mapa muscular.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    activity_id: int = Field(index=True, foreign_key="activity.id")
    exercise: str  # chave do catálogo, ex: "supino_reto"
    reps: Optional[int] = None
    weight_kg: Optional[float] = None  # None = peso corporal / não informado
    created_at: datetime = Field(default_factory=datetime.utcnow)
