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
from datetime import datetime
from typing import Any, Optional

from .fit_parser import friendly_sport

# Nome do workout no Apple Health/HAE -> (sport, sub_sport) no nosso vocabulário.
HAE_SPORT_MAP: dict[str, tuple[str, Optional[str]]] = {
    "Running": ("running", None),
    "Walking": ("walking", None),
    "Hiking": ("walking", None),
    "Cycling": ("cycling", None),
    "Indoor Cycling": ("cycling", "indoor_cycling"),
    "Traditional Strength Training": ("training", "strength_training"),
    "Functional Strength Training": ("training", "strength_training"),
    "Core Training": ("training", "strength_training"),
    "Swimming": ("swimming", None),
    "Pool Swimming": ("swimming", None),
    "Open Water Swimming": ("swimming", None),
}


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
    sport, sub_sport = HAE_SPORT_MAP.get(name, (name.lower().replace(" ", "_") or "unknown", None))

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

    return {
        "sport": sport,
        "sub_sport": sub_sport,
        "label": friendly_sport(sport, sub_sport),
        "start_time": _parse_dt(w.get("start")),
        "total_time_s": w.get("duration"),
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
