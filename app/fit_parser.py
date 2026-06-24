"""
Extrai de um arquivo .fit os dados que o app precisa:
- resumo da sessão (tempo, FC min/méd/máx, calorias, distância, ganho/perda de altitude)
- pontos do percurso (timestamp, lat/lon em graus, altitude, FC, velocidade, cadência)

Testado contra os 3 arquivos reais do Zepp/Amazfit que você enviou
(Musculacao.fit, Esteira.fit, Caminhada.fit).
"""
import io
from datetime import datetime
from typing import Any, Optional

import fitparse

# Conversão de semicírculos (unidade nativa do FIT) para graus decimais.
# graus = semicirculos * (180 / 2^31)
SEMICIRCLE_TO_DEGREE = 180 / (2**31)

# Mapeia (sport, sub_sport) do FIT pra um nome amigável em PT-BR.
# Cobre o que apareceu nos seus arquivos + os 4 tipos iniciais do app.
# Sport ou sub_sport não mapeados caem no fallback (sport.title()).
SPORT_LABELS = {
    ("running", "treadmill"): "Corrida (esteira)",
    ("running", None): "Corrida",
    ("cycling", None): "Bicicleta",
    ("swimming", None): "Natação",
    ("training", "strength_training"): "Musculação",
    ("walking", "speed_walking"): "Caminhada",
    ("walking", None): "Caminhada",
}


def friendly_sport(sport: Optional[str], sub_sport: Optional[str]) -> str:
    if (sport, sub_sport) in SPORT_LABELS:
        return SPORT_LABELS[(sport, sub_sport)]
    if (sport, None) in SPORT_LABELS:
        return SPORT_LABELS[(sport, None)]
    if not sport:
        return "Atividade"
    return sport.replace("_", " ").title()


def _semicircles_to_degrees(value: Optional[int]) -> Optional[float]:
    if value is None:
        return None
    return round(value * SEMICIRCLE_TO_DEGREE, 7)


def parse_fit(file_bytes: bytes) -> dict[str, Any]:
    fitfile = fitparse.FitFile(io.BytesIO(file_bytes))

    sessions = list(fitfile.get_messages("session"))
    if not sessions:
        raise ValueError("Arquivo FIT sem mensagem 'session' — não é um arquivo de atividade válido.")
    session = sessions[0]

    sport = session.get_value("sport")
    sub_sport = session.get_value("sub_sport")

    summary = {
        "sport": sport,
        "sub_sport": sub_sport,
        "label": friendly_sport(sport, sub_sport),
        "start_time": session.get_value("start_time"),
        "total_time_s": session.get_value("total_timer_time") or session.get_value("total_elapsed_time"),
        "avg_hr": session.get_value("avg_heart_rate"),
        "min_hr": session.get_value("min_heart_rate"),
        "max_hr": session.get_value("max_heart_rate"),
        "calories": session.get_value("total_calories"),
        "distance_m": session.get_value("total_distance"),
        "total_ascent_m": session.get_value("total_ascent"),
        "total_descent_m": session.get_value("total_descent"),
    }

    track_points = []
    has_gps = False
    for record in fitfile.get_messages("record"):
        lat = _semicircles_to_degrees(record.get_value("position_lat"))
        lon = _semicircles_to_degrees(record.get_value("position_long"))
        if lat is not None and lon is not None:
            has_gps = True

        ts = record.get_value("timestamp")
        point = {
            "t": ts.isoformat() if isinstance(ts, datetime) else None,
            "lat": lat,
            "lon": lon,
            # nem todo dispositivo grava altitude (ex: o Amazfit Active Edge
            # testado não trouxe esse campo mesmo com GPS ativo)
            "alt": record.get_value("enhanced_altitude") or record.get_value("altitude"),
            "hr": record.get_value("heart_rate"),
            "speed": record.get_value("enhanced_speed") or record.get_value("speed"),
            "cadence": record.get_value("cadence"),
        }
        track_points.append(point)

    summary["has_gps"] = has_gps
    summary["track_points"] = track_points
    return summary
