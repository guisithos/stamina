"""Análise comparativa de corrida — estatística descritiva + 3 fórmulas clássicas,
sem dependência externa, determinística e explicável.

- Efficiency Factor (EF) = velocidade ÷ FC média. Maior = mais condicionado.
- Desacoplamento aeróbico (Pa:HR): EF da 1ª metade vs 2ª metade. <5% = boa
  resistência. Sem GPS (esteira), vira deriva de FC (FC 2ª metade vs 1ª).
- Comparação vs as últimas N corridas: distância, pace, FC e EF, com frase pronta.

Tudo a partir do que já guardamos na Activity (resumo + track_points).
"""
import json
import math
from datetime import datetime
from statistics import mean
from typing import Any, Optional

from .metrics import format_pace

EARTH_R = 6371000  # m


def _haversine(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def _parse_dt(s) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None


def efficiency_factor(distance_m, time_s, avg_hr) -> Optional[float]:
    """Velocidade (m/min) ÷ FC média. Unidade arbitrária, o que importa é comparar."""
    if not distance_m or not time_s or not avg_hr:
        return None
    speed_m_min = distance_m / (time_s / 60)
    return speed_m_min / avg_hr


def aerobic_decoupling(track_points: list[dict], total_time_s) -> Optional[dict]:
    """Compara a 1ª com a 2ª metade do treino. Retorna {value: %, kind}."""
    pts = []
    for p in track_points:
        t = _parse_dt(p.get("t"))
        if t is not None:
            pts.append((t, p.get("lat"), p.get("lon"), p.get("hr")))
    if len(pts) < 4:
        return None
    pts.sort(key=lambda x: x[0])
    t_start, t_end = pts[0][0], pts[-1][0]
    if (t_end - t_start).total_seconds() <= 0:
        return None
    t_mid = t_start + (t_end - t_start) / 2

    def half_stats(half):
        if len(half) < 2:
            return None
        dist = 0.0
        last = None
        hrs = []
        for (_t, lat, lon, hr) in half:
            if hr is not None:
                hrs.append(hr)
            if lat is not None and lon is not None:
                if last is not None:
                    dist += _haversine(last[0], last[1], lat, lon)
                last = (lat, lon)
        secs = (half[-1][0] - half[0][0]).total_seconds()
        return dist, secs, (mean(hrs) if hrs else None)

    h1 = half_stats([p for p in pts if p[0] <= t_mid])
    h2 = half_stats([p for p in pts if p[0] > t_mid])
    if not h1 or not h2:
        return None
    d1, s1, hr1 = h1
    d2, s2, hr2 = h2

    # Pa:HR (com GPS): EF de cada metade
    if d1 > 0 and d2 > 0 and s1 > 0 and s2 > 0 and hr1 and hr2:
        ef1 = (d1 / (s1 / 60)) / hr1
        ef2 = (d2 / (s2 / 60)) / hr2
        if ef1 > 0:
            return {"value": round((ef1 - ef2) / ef1 * 100, 1), "kind": "decoupling"}
    # fallback: deriva de FC (esteira / sem distância por trecho)
    if hr1 and hr2:
        return {"value": round((hr2 - hr1) / hr1 * 100, 1), "kind": "hr_drift"}
    return None


# ---------- formatação pt-BR ----------

def _km1(m) -> str:
    return f"{m / 1000:.1f}".replace(".", ",")


def _sign(x, suffix="", decimals=0) -> str:
    s = "+" if x >= 0 else "−"
    v = abs(round(x, decimals)) if decimals else abs(round(x))
    txt = f"{v:.{decimals}f}".replace(".", ",") if decimals else f"{int(v)}"
    return f"{s}{txt}{suffix}"


def _decoupling_view(decoup: dict) -> dict:
    v = decoup["value"]
    kind = decoup["kind"]
    base = "Desacoplamento" if kind == "decoupling" else "Deriva de FC"
    if v < 5:
        return {"text": f"{base} de {v:.1f}% — boa resistência aeróbica (segurou o ritmo).",
                "tone": "good", "icon": "seal-check"}
    if v <= 10:
        return {"text": f"{base} de {v:.1f}% — leve perda de eficiência na 2ª metade.",
                "tone": "neutral", "icon": "trend-up"}
    return {"text": f"{base} de {v:.1f}% — você desacelerou ou a FC subiu bastante no fim.",
            "tone": "bad", "icon": "warning"}


def _avg_cadence(points) -> Optional[int]:
    vals = [p["cadence"] for p in points if p.get("cadence")]
    return round(mean(vals)) if vals else None


def run_metrics(activity, *, full: bool = False) -> dict:
    """Métricas de UMA corrida. `full=True` (a atual) inclui desacoplamento e
    cadência (mais pesado: parseia os track_points); as anteriores vão resumidas."""
    dist, time_s, hr = activity.distance_m, activity.total_time_s, activity.avg_hr
    ef = efficiency_factor(dist, time_s, hr)
    m = {
        "data": activity.start_time.strftime("%Y-%m-%d"),
        "distancia_km": round(dist / 1000, 2) if dist else None,
        "duracao_min": round(time_s / 60, 1) if time_s else None,
        "pace": format_pace(time_s, dist) if (time_s and dist) else None,
        "fc_media": hr,
        "fc_max": activity.max_hr,
        "ef": round(ef, 3) if ef else None,
        "rpe": activity.rpe,
        "ganho_elevacao_m": round(activity.total_ascent_m) if activity.total_ascent_m else None,
        "calorias": activity.calories,
    }
    if full:
        points = json.loads(activity.track_points_json) if activity.track_points_json else []
        decoup = aerobic_decoupling(points, time_s)
        m["desacoplamento_pct"] = decoup["value"] if decoup else None
        m["desacoplamento_tipo"] = decoup["kind"] if decoup else None
        m["cadencia_media"] = _avg_cadence(points)
    return m


def build_run_dataset(activity, previous_runs: list) -> dict:
    """Dataset pra IA: a corrida atual (completa) + as últimas N anteriores (resumidas),
    da mais recente pra mais antiga. É a base do comparativo."""
    return {
        "atual": run_metrics(activity, full=True),
        "anteriores": [run_metrics(r) for r in previous_runs],
    }


def build_run_analysis(activity, previous_runs: list) -> Optional[dict]:
    """Monta a análise da corrida vs as últimas N corridas (já filtradas)."""
    dist, time_s, hr = activity.distance_m, activity.total_time_s, activity.avg_hr
    if not dist or not time_s:
        return None

    pace_fmt = format_pace(time_s, dist)
    pace_s = time_s / (dist / 1000)
    ef = efficiency_factor(dist, time_s, hr)

    points = json.loads(activity.track_points_json) if activity.track_points_json else []
    decoup = aerobic_decoupling(points, time_s)
    decoup_view = _decoupling_view(decoup) if decoup else None

    base = [r for r in previous_runs if r.distance_m and r.total_time_s]
    if not base:
        head = f"{_km1(dist)} km a {pace_fmt}" + (f", FC {hr}" if hr else "")
        return {
            "baseline_n": 0,
            "summary": f"{head}. Primeira corrida com dados suficientes — as próximas vão ganhar comparação.",
            "verdict": None,
            "deltas": [],
            "decoupling": decoup_view,
        }

    n = len(base)
    avg_dist = mean(r.distance_m for r in base)
    avg_pace = mean(r.total_time_s / (r.distance_m / 1000) for r in base)
    hrs = [r.avg_hr for r in base if r.avg_hr]
    avg_hr = mean(hrs) if hrs else None
    efs = [e for e in (efficiency_factor(r.distance_m, r.total_time_s, r.avg_hr) for r in base) if e]
    avg_ef = mean(efs) if efs else None

    deltas = []

    # Distância
    dd = dist - avg_dist
    deltas.append({"label": "Distância", "value": f"{_km1(dist)} km",
                   "delta": ("≈ igual" if abs(dd) < 100 else _sign(dd / 1000, " km", 1)),
                   "tone": "neutral"})

    # Pace
    pd = pace_s - avg_pace
    if abs(pd) < 5:
        deltas.append({"label": "Pace", "value": pace_fmt, "delta": "≈ igual", "tone": "neutral"})
    else:
        deltas.append({"label": "Pace", "value": pace_fmt,
                       "delta": _sign(pd, " s/km"), "tone": "good" if pd < 0 else "bad"})

    # FC média
    if hr and avg_hr:
        hd = hr - avg_hr
        if abs(hd) < 2:
            deltas.append({"label": "FC média", "value": str(hr), "delta": "≈ igual", "tone": "neutral"})
        else:
            deltas.append({"label": "FC média", "value": str(hr),
                           "delta": _sign(hd, " bpm"), "tone": "good" if hd < 0 else "bad"})

    # Efficiency Factor
    verdict = None
    if ef and avg_ef:
        ef_pct = (ef - avg_ef) / avg_ef * 100
        deltas.append({"label": "Eficiência (EF)", "value": f"{ef:.2f}",
                       "delta": _sign(ef_pct, "%"), "tone": "good" if ef_pct >= 0 else "bad"})
        if ef_pct >= 3:
            verdict = f"Eficiência {_sign(ef_pct, '%')} acima da sua média — sinal de melhora de condicionamento."
        elif ef_pct <= -3:
            verdict = f"Eficiência {_sign(ef_pct, '%')} vs média — pode ser fadiga, calor ou um esforço maior."
        else:
            verdict = "Eficiência em linha com a sua média recente."

    # frase comparativa (estilo do pedido)
    dist_phrase = "mesma distância" if abs(dd) < 100 else f"{_sign(dd / 1000, ' km', 1)}"
    if abs(pd) < 5:
        pace_phrase = "pace igual"
    else:
        pace_phrase = f"{abs(round(pd))} s/km mais {'rápido' if pd < 0 else 'lento'}"
    hr_phrase = ""
    if hr and avg_hr:
        hr_phrase = ", FC igual" if abs(hr - avg_hr) < 2 else f", FC {_sign(hr - avg_hr, ' bpm')}"
    head = f"{_km1(dist)} km a {pace_fmt}" + (f", FC {hr}" if hr else "")
    summary = f"{head} — vs suas últimas {n}: {dist_phrase}, {pace_phrase}{hr_phrase}."

    return {
        "baseline_n": n,
        "summary": summary,
        "verdict": verdict,
        "deltas": deltas,
        "decoupling": decoup_view,
    }
