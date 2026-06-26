"""Converte um workout do Health Auto Export (JSON) na MESMA estrutura que
`parse_fit` devolve, para reaproveitar toda a criação de Activity.

Formato de entrada (resumo da wiki do HAE), por workout:
  id, name, start/end ("yyyy-MM-dd HH:mm:ss Z"), duration (s),
  distance {qty, units}, activeEnergyBurned {qty, units},
  avgHeartRate/maxHeartRate {qty, units},
  heartRateData: [{date, Min, Avg, Max, units}],
  route: [{latitude, longitude, altitude, timestamp, speed, ...}]

Decisões:
- timestamps do HAE têm offset de fuso; guardamos o horário "de parede" (naïve
  local) para ficar consistente com o resto do app (que exibe sem conversão).
- rota e FC são streams separados no HAE; concatenamos num único track_points
  (pontos de rota com hr=None + pontos de FC com lat/lon=None). Cada consumidor
  já filtra: o mapa usa só pontos com lat/lon, o gráfico só pontos com hr.
"""
import math
import unicodedata
from datetime import datetime
from typing import Any, Optional

from .fit_parser import friendly_sport

# IMPORTANTE: o Health Auto Export manda o `name` do treino no IDIOMA do iPhone
# (ex.: "Treinamento de Força Tradicional", "Ciclismo Interno"). Por isso a
# resolução é por PALAVRA-CHAVE, sem acento e sem depender da ordem — funciona em
# pt e en. Cada tupla é (lista de termos, (sport, sub_sport)); o primeiro que casar vence.
_SPORT_KEYWORDS: list[tuple[tuple[str, ...], tuple[str, Optional[str]]]] = [
    (("ciclis", "cycl", "bike", "pedal", "spinning"), ("cycling", None)),
    (("forca", "strength", "muscula", "funcional", "weight", "resistenc"), ("training", "strength_training")),
    (("corr", "run", "treadmill", "esteira"), ("running", None)),  # corr- pega corrida/correr/correndo
    (("caminh", "walk", "hik", "trilha"), ("walking", None)),
    (("nata", "swim"), ("swimming", None)),
]
_INDOOR_TERMS = ("indoor", "intern", "esteira", "treadmill", "sala", "esteira")


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def resolve_sport(name: Optional[str]) -> tuple[str, Optional[str]]:
    """Mapeia o nome do workout (em qualquer idioma) para (sport, sub_sport)."""
    n = _strip_accents(name or "").lower()
    indoor = any(t in n for t in _INDOOR_TERMS)
    for terms, (sport, sub) in _SPORT_KEYWORDS:
        if any(t in n for t in terms):
            if sport == "cycling" and indoor:
                sub = "indoor_cycling"
            elif sport == "running" and indoor:
                sub = "treadmill"
            return (sport, sub)
    return (n.replace(" ", "_") or "unknown", None)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Aceita 'yyyy-MM-dd HH:mm:ss Z' (com offset) ou ISO; devolve naïve local."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=None)
        except ValueError:
            pass
    try:  # fallback ISO ("2026-06-24T17:50:30-03:00" / com 'Z')
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except ValueError:
        return None


def _iso(value: Optional[str]) -> Optional[str]:
    dt = _parse_dt(value)
    return dt.isoformat() if dt else None


def _qty(obj: Any) -> Optional[float]:
    if isinstance(obj, dict):
        return obj.get("qty")
    if isinstance(obj, (int, float)):
        return obj
    return None


def _distance_m(distance: Any) -> Optional[float]:
    qty = _qty(distance)
    if qty is None:
        return None
    units = (distance.get("units") if isinstance(distance, dict) else "") or ""
    units = units.lower()
    if units == "mi":
        return qty * 1609.344
    if units in ("m", "meter", "meters"):
        return qty
    return qty * 1000  # km (padrão)


def _haversine(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def _moving_time_s(route, min_speed: float = 0.5, max_dt: float = 30) -> float:
    """Tempo em movimento a partir do GPS (estilo Strava): soma os intervalos em que
    houve deslocamento real, descartando paradas (água/banheiro) e gaps. O HAE manda
    `duration` = tempo total (com pausa); isso reconstrói o tempo de relógio em movimento."""
    pts = []
    for p in route or []:
        t = _parse_dt(p.get("timestamp"))
        lat, lon = p.get("latitude"), p.get("longitude")
        if t and lat is not None and lon is not None:
            pts.append((t, lat, lon))
    pts.sort(key=lambda x: x[0])
    moving = 0.0
    for (t1, la1, lo1), (t2, la2, lo2) in zip(pts, pts[1:]):
        dt = (t2 - t1).total_seconds()
        if dt <= 0:
            continue
        d = _haversine(la1, lo1, la2, lo2)
        if dt <= max_dt and d / dt >= min_speed:  # movendo, sem gap grande
            moving += dt
    return moving


def _calories(energy: Any) -> Optional[int]:
    qty = _qty(energy)
    if qty is None:
        return None
    units = (energy.get("units") if isinstance(energy, dict) else "") or ""
    if units.lower() in ("kj", "kilojoule", "kilojoules"):
        return round(qty / 4.184)
    return round(qty)


def parse_hae_workout(w: dict[str, Any]) -> dict[str, Any]:
    name = w.get("name") or ""
    sport, sub_sport = resolve_sport(name)

    # --- pontos do percurso: rota (lat/lon) + FC (hr), streams separados ---
    track_points: list[dict[str, Any]] = []
    has_gps = False
    altitudes: list[float] = []

    for p in (w.get("route") or []):
        lat, lon = p.get("latitude"), p.get("longitude")
        if lat is not None and lon is not None:
            has_gps = True
        alt = p.get("altitude")
        if isinstance(alt, (int, float)):
            altitudes.append(alt)
        track_points.append({
            "t": _iso(p.get("timestamp")),
            "lat": lat, "lon": lon, "alt": alt,
            "hr": None, "speed": p.get("speed"), "cadence": None,
        })

    hr_values: list[int] = []
    for h in (w.get("heartRateData") or []):
        avg = h.get("Avg")
        hr = round(avg) if isinstance(avg, (int, float)) else None
        if hr is not None:
            hr_values.append(hr)
        track_points.append({
            "t": _iso(h.get("date")),
            "lat": None, "lon": None, "alt": None,
            "hr": hr, "speed": None, "cadence": None,
        })

    # --- ganho/perda de elevação a partir das altitudes da rota (limiar anti-ruído) ---
    ascent = descent = 0.0
    for a, b in zip(altitudes, altitudes[1:]):
        d = b - a
        if d > 1:
            ascent += d
        elif d < -1:
            descent += -d

    avg_hr = _qty(w.get("avgHeartRate"))
    max_hr = _qty(w.get("maxHeartRate"))
    min_hr = min(hr_values) if hr_values else None

    # Tempo: usa o `duration` do HAE, mas se houver GPS e o tempo em movimento for
    # claramente menor (pausas), usa o de movimento — pra o pace bater com o relógio.
    duration = w.get("duration")
    total_time_s = duration
    if has_gps and duration:
        mv = _moving_time_s(w.get("route"))
        if mv and 0.5 * duration <= mv < 0.98 * duration:
            total_time_s = round(mv)

    return {
        "sport": sport,
        "sub_sport": sub_sport,
        "label": friendly_sport(sport, sub_sport),
        "start_time": _parse_dt(w.get("start")),
        "total_time_s": total_time_s,
        "avg_hr": round(avg_hr) if avg_hr is not None else None,
        "min_hr": min_hr,
        "max_hr": round(max_hr) if max_hr is not None else None,
        "calories": _calories(w.get("activeEnergyBurned")),
        "distance_m": _distance_m(w.get("distance")),
        "total_ascent_m": round(ascent) if ascent else None,
        "total_descent_m": round(descent) if descent else None,
        "has_gps": has_gps,
        "track_points": track_points,
        "external_id": str(w["id"]) if w.get("id") is not None else None,
    }
