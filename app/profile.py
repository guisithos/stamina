"""Agregações da página de perfil: totais dos últimos 3 meses (por esporte) e
o heatmap anual estilo GitHub ("quadradinhos" de atividade por dia).

Mesma filosofia de `summary.py`: recebe a lista de atividades já carregada +
uma data de referência injetada, devolve estruturas prontas pro template. Sem
tocar no banco — testável com datas fixas.
"""
import calendar
from datetime import date, datetime, timedelta

from .metrics import format_distance, format_duration, sport_icon

# Rótulo + se faz sentido mostrar distância, por esporte. Ordem = prioridade de
# exibição nos cards de resumo. Esportes fora dessa lista caem no fim, em ordem
# alfabética, usando o próprio nome como rótulo.
SPORT_LABELS = {
    "running": "Corrida",
    "training": "Musculação",
    "cycling": "Bicicleta",
    "swimming": "Natação",
    "walking": "Caminhada",
}
SHOW_DISTANCE = {"running", "cycling", "swimming", "walking"}
SPORT_ORDER = ["running", "training", "cycling", "swimming", "walking"]

MONTHS_ABBR_PT = [
    "", "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
]


def _as_date(ref_date) -> date:
    return ref_date.date() if isinstance(ref_date, datetime) else ref_date


def username_from_email(email: str) -> str:
    """Nome de exibição derivado do e-mail: o pedaço antes do @.
    Ex.: 'gui.souzat@gmail.com' -> 'gui.souzat'."""
    return (email or "").split("@")[0] or "atleta"


def _shift_months_back(d: date, n: int) -> date:
    """Subtrai `n` meses de `d`, encaixando o dia no último dia válido do mês."""
    idx = d.year * 12 + (d.month - 1) - n
    y, m = idx // 12, idx % 12 + 1
    last_day = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last_day))


def three_month_totals(activities, ref_date, months: int = 3) -> dict:
    """Totais dos últimos `months` meses, somados por esporte.

    Devolve {'cards': [...], 'total_count': N, 'total_time': 'Xh', 'window': '...'}.
    Cada card: label, icon, count, time, distance, show_distance."""
    ref = _as_date(ref_date)
    cutoff = _shift_months_back(ref, months)  # janela [cutoff, ref]

    agg: dict[str, dict] = {}
    total_count = 0
    total_secs = 0.0
    for a in activities:
        d = a.start_time.date()
        if not (cutoff <= d <= ref):
            continue
        e = agg.setdefault(a.sport, {"count": 0, "secs": 0.0, "dist": 0.0})
        e["count"] += 1
        e["secs"] += a.total_time_s or 0
        e["dist"] += a.distance_m or 0
        total_count += 1
        total_secs += a.total_time_s or 0

    # ordena: primeiro os esportes conhecidos (SPORT_ORDER), depois o resto A→Z
    def _rank(sport: str) -> tuple[int, str]:
        return (SPORT_ORDER.index(sport) if sport in SPORT_ORDER else len(SPORT_ORDER), sport)

    cards = []
    for sport in sorted(agg, key=_rank):
        e = agg[sport]
        show_dist = sport in SHOW_DISTANCE and e["dist"] > 0
        cards.append({
            "sport": sport,
            "label": SPORT_LABELS.get(sport, sport.capitalize()),
            "icon": sport_icon(sport),
            "count": e["count"],
            "time": format_duration(e["secs"]),
            "distance": format_distance(e["dist"]) if show_dist else None,
            "show_distance": show_dist,
        })

    return {
        "cards": cards,
        "total_count": total_count,
        "total_time": format_duration(total_secs),
    }


def _level(count: int) -> int:
    """Intensidade do dia (0–4) pelo nº de atividades — escala dos quadradinhos."""
    if count <= 0:
        return 0
    return min(count, 4)


def activity_heatmap(activities, ref_date, weeks: int = 53) -> dict:
    """Grade estilo GitHub das atividades no último ano.

    Colunas = semanas (segunda→domingo), 7 linhas = dias. Devolve:
    - 'weeks': lista de colunas; cada coluna é uma lista de 7 dicts de dia
    - 'months': rótulo do mês por coluna (só quando um mês novo começa; senão '')
    - 'total': total de atividades no período
    - 'active_days': dias distintos com ao menos uma atividade
    """
    ref = _as_date(ref_date)

    counts: dict[date, int] = {}
    for a in activities:
        d = a.start_time.date()
        counts[d] = counts.get(d, 0) + 1

    # última coluna = semana atual (segunda→domingo); recua `weeks-1` semanas.
    monday = ref - timedelta(days=ref.weekday())  # weekday(): segunda = 0
    start = monday - timedelta(weeks=weeks - 1)

    week_cols: list[list[dict]] = []
    months: list[str] = []
    total = 0
    active_days = 0
    prev_month = None

    day = start
    while day <= monday + timedelta(days=6):
        col = []
        for i in range(7):
            d = day + timedelta(days=i)
            c = counts.get(d, 0)
            if c:
                total += c
                active_days += 1
            col.append({
                "iso": d.isoformat(),
                "day": d.day,
                "count": c,
                "level": _level(c),
                "is_future": d > ref,
            })
        week_cols.append(col)

        # rótulo do mês: mostra a abreviação quando a semana estreia um mês novo
        col_month = col[0]["iso"][5:7]  # 'MM' do primeiro dia (segunda) da coluna
        month_num = int(col_month)
        if month_num != prev_month:
            months.append(MONTHS_ABBR_PT[month_num])
            prev_month = month_num
        else:
            months.append("")

        day += timedelta(days=7)

    return {
        "weeks": week_cols,
        "months": months,
        "total": total,
        "active_days": active_days,
    }
