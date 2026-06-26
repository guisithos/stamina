"""Agregações por período para o painel-resumo do dashboard (mês e semana).

Lógica de negócio separada das rotas: recebe a lista de atividades já carregada
e devolve estruturas prontas pro template. A data de referência é injetada
(`ref_date`) — a rota passa `datetime.now()`, os testes passam uma data fixa.
"""
from datetime import date, datetime, timedelta

from .metrics import format_distance, sport_icon

# Esportes do resumo mensal: rótulo, se mostra distância e qual valor dirige a
# comparação percentual com o mês anterior.
MONTH_SPORTS = [
    {"sport": "running", "label": "Corrida", "show_distance": True, "compare": "distance"},
    {"sport": "training", "label": "Musculação", "show_distance": False, "compare": "time"},
    {"sport": "cycling", "label": "Bicicleta", "show_distance": True, "compare": "distance"},
    {"sport": "swimming", "label": "Natação", "show_distance": True, "compare": "distance"},
]

WEEKDAYS_PT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MONTHS_PT = [
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def _as_date(ref_date) -> date:
    return ref_date.date() if isinstance(ref_date, datetime) else ref_date


def _month_bounds(ref: date) -> tuple[date, date]:
    """Primeiro dia do mês de `ref` e primeiro dia do mês seguinte (intervalo [a, b))."""
    start = ref.replace(day=1)
    if start.month == 12:
        nxt = start.replace(year=start.year + 1, month=1)
    else:
        nxt = start.replace(month=start.month + 1)
    return start, nxt


def _totals(activities, sport, start: date, end: date) -> tuple[float, float]:
    """Soma (distância_m, tempo_s) das atividades do esporte no intervalo [start, end)."""
    dist = secs = 0.0
    for a in activities:
        if a.sport != sport:
            continue
        d = a.start_time.date()
        if start <= d < end:
            dist += a.distance_m or 0
            secs += a.total_time_s or 0
    return dist, secs


def _pct(current: float, previous: float):
    """Variação percentual; None quando não há base de comparação (esporte novo no mês)."""
    if previous and previous > 0:
        return (current - previous) / previous * 100
    return None


def _fmt_hm(seconds: float) -> str:
    """Tempo curto pra tira semanal: 1h40, 2h, 45min."""
    if not seconds:
        return ""
    h, m = divmod(int(seconds) // 60, 60)
    if h and m:
        return f"{h}h{m:02d}"
    if h:
        return f"{h}h"
    return f"{m}min"


def month_name(ref_date) -> str:
    ref = _as_date(ref_date)
    return f"{MONTHS_PT[ref.month]} de {ref.year}"


def monthly_summary(activities, ref_date) -> list[dict]:
    ref = _as_date(ref_date)
    cur_start, cur_end = _month_bounds(ref)
    prev_start, prev_end = _month_bounds(cur_start - timedelta(days=1))

    cards = []
    for cfg in MONTH_SPORTS:
        cur_dist, cur_secs = _totals(activities, cfg["sport"], cur_start, cur_end)
        prev_dist, prev_secs = _totals(activities, cfg["sport"], prev_start, prev_end)

        if cur_dist == 0 and cur_secs == 0:  # só mostra esporte praticado neste mês
            continue

        if cfg["compare"] == "distance":
            pct = _pct(cur_dist, prev_dist)
        else:
            pct = _pct(cur_secs, prev_secs)

        cards.append({
            "label": cfg["label"],
            "icon": sport_icon(cfg["sport"]),
            "show_distance": cfg["show_distance"],
            "distance": format_distance(cur_dist),
            "time": _fmt_hm(cur_secs),  # compacto (1h59 / 38min) — total do mês não precisa de seg.
            "pct": pct,
            "compare": cfg["compare"],
            "secs": cur_secs,      # volume (tempo total) p/ escolher o destaque
            "highlight": False,
        })

    # Destaca o esporte de MAIOR volume no mês (tempo total) — denominador comum
    # justo entre esportes (musculação não tem distância). Empate: o primeiro.
    if cards:
        max(cards, key=lambda c: c["secs"])["highlight"] = True
    return cards


def week_days(activities, ref_date) -> list[dict]:
    ref = _as_date(ref_date)
    monday = ref - timedelta(days=ref.weekday())  # weekday(): segunda = 0

    days = []
    for i in range(7):
        d = monday + timedelta(days=i)
        icons, seen, total_s = [], set(), 0.0
        for a in activities:
            if a.start_time.date() != d:
                continue
            total_s += a.total_time_s or 0
            if a.sport not in seen:  # um ícone por esporte/dia
                seen.add(a.sport)
                icons.append(sport_icon(a.sport))
        days.append({
            "label": WEEKDAYS_PT[i],
            "day": d.day,
            "is_today": d == ref,
            "is_future": d > ref,
            "icons": icons,
            "total_time": _fmt_hm(total_s),
        })
    return days
