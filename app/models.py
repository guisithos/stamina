from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    hashed_password: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Activity(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="user.id")

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

    raw_filename: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
