"""Formatação de métricas e o catálogo *esporte → métricas relevantes*.

Fonte única de verdade do que cada tipo de atividade exibe no histórico.
Adicionar pace, um esporte novo ou uma métrica é editar os dicionários daqui —
o template só itera sobre o resultado de `activity_metrics`.
"""
from typing import Any, Callable


# ---------- formatação ----------

def format_duration(total_seconds) -> str:
    if not total_seconds:
        return "—"
    total_seconds = int(total_seconds)
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}min"
    return f"{m}min{s:02d}s"


def format_distance(meters) -> str:
    if not meters:
        return "—"
    return f"{meters / 1000:.2f} km"


def format_pace(total_time_s, distance_m) -> str:
    """Ritmo em min:ss por km (corrida)."""
    if not total_time_s or not distance_m:
        return "—"
    sec_per_km = total_time_s / (distance_m / 1000)
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}/km"


def format_speed(total_time_s, distance_m) -> str:
    """Velocidade média em km/h (bicicleta)."""
    if not total_time_s or not distance_m:
        return "—"
    kmh = (distance_m / 1000) / (total_time_s / 3600)
    return f"{kmh:.1f} km/h"


def format_hr(avg_hr, max_hr) -> str:
    if not avg_hr:
        return "—"
    return f"{avg_hr} / {max_hr or '—'}"


def format_calories(calories) -> str:
    return f"{calories} kcal" if calories else "—"


def format_date(dt) -> str:
    if not dt:
        return "—"
    return dt.strftime("%d/%m/%Y %H:%M")


# ---------- catálogo de métricas por esporte ----------

# Cada métrica: rótulo + como extrair/formatar o valor a partir da atividade.
METRIC_BUILDERS: dict[str, tuple[str, Callable[[Any], str]]] = {
    "distance": ("Distância", lambda a: format_distance(a.distance_m)),
    "duration": ("Duração", lambda a: format_duration(a.total_time_s)),
    "pace": ("Pace", lambda a: format_pace(a.total_time_s, a.distance_m)),
    "speed": ("Vel. média", lambda a: format_speed(a.total_time_s, a.distance_m)),
    "hr": ("FC méd/máx", lambda a: format_hr(a.avg_hr, a.max_hr)),
    "calories": ("Calorias", lambda a: format_calories(a.calories)),
}

# Quais métricas (e em que ordem) cada esporte mostra. Chave = `sport` cru do FIT
# (treadmill é sub_sport de "running", então cai aqui também).
SPORT_METRICS: dict[str, list[str]] = {
    "running": ["distance", "duration", "pace", "hr", "calories"],
    "cycling": ["distance", "duration", "speed", "hr", "calories"],
    # natação usa pace por 100m (convenção diferente) — fica fora até termos um
    # arquivo de natação pra mapear o formato certo.
    "swimming": ["distance", "duration", "hr", "calories"],
    "walking": ["distance", "duration", "hr", "calories"],
    "training": ["duration", "hr", "calories"],
}
DEFAULT_METRICS = ["duration", "hr", "calories"]

# Nomes de ícones Phosphor (renderizados como <i class="ph ph-{nome}">).
SPORT_ICONS: dict[str, str] = {
    "running": "person-simple-run",
    "cycling": "person-simple-bike",
    "swimming": "person-simple-swim",
    "walking": "person-simple-walk",
    "training": "barbell",
}


def activity_metrics(activity) -> list[dict[str, str]]:
    """Lista ordenada de {label, value} relevante ao esporte da atividade."""
    keys = SPORT_METRICS.get(activity.sport, DEFAULT_METRICS)
    out = []
    for key in keys:
        label, builder = METRIC_BUILDERS[key]
        out.append({"label": label, "value": builder(activity)})
    return out


def sport_icon(sport) -> str:
    """Nome do ícone Phosphor para o esporte (fallback: ícone genérico de atividade)."""
    return SPORT_ICONS.get(sport, "pulse")
