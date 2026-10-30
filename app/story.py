"""Imagem de story (Instagram) de um treino: traçado do percurso (ou ícone, se
indoor) + as métricas do esporte, na paleta do app.

Gerada no servidor com Pillow — sai idêntica em qualquer aparelho, sem depender
de fonte/canvas do navegador. Duas variações (`bg`):

- "dark": 1080×1920 (9:16) com o fundo do app, pronta pra postar como story.
- "transparent": fundo transparente, recortada no conteúdo — é um sticker pra
  colar por cima de uma foto/vídeo no Instagram. Ganha uma sombra suave pra
  continuar legível sobre fotos claras.

E três estilos de traçado (`style`), todos da paleta — nenhum é uma linha laranja
lisa, que lembraria o Strava:

- "gold" (ouro gasto): linha dourada com brilho suave.
- "ember" (brasa): degradê ao longo do percurso, de brasa funda (início) a brasa
  acesa (fim) — mostra o sentido. Nos ícones, o degradê sobe como chama.
- "parchment" (pergaminho em brasa): linha creme com halo vermelho-brasa.

Só dados: sem marca, data ou rótulo. Métrica sem valor não aparece (nunca "—").
Traçado vs ícone é decidido pela existência de GPS, não pelo sub_sport: uma
corrida de rua sem GPS também cai no ícone.
"""
import json
import math
import os
from functools import lru_cache
from io import BytesIO
from typing import Callable, Optional

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
SS = 2  # supersampling do traçado/ícone (Pillow não faz antialias em linhas)

# Mesmos tokens de static/style.css (paleta "cinza de fogueira + brasa").
BG = (21, 23, 26)            # --bg (ash-900)
EMBER = (89, 16, 16)         # --ember (brasa funda)
COPPER = (194, 84, 46)       # --accent-glow (brasa acesa)
GOLD = (168, 145, 92)        # --gold (ouro gasto)
PARCHMENT = (232, 227, 216)  # --text
MUTED = (139, 141, 135)      # --text-muted
EMBER_HALO = (160, 40, 20)   # halo do estilo pergaminho
EMBER_TIP = (240, 170, 110)  # ponta mais acesa do degradê de brasa

FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")
VALUE_FONT = os.path.join(FONTS_DIR, "Fraunces-SemiBold.ttf")    # números (display)
LABEL_FONT = os.path.join(FONTS_DIR, "IBMPlexMono-Medium.ttf")   # rótulos/unidades

STORY_SPORTS = {"running", "walking", "cycling", "swimming"}
BACKGROUNDS = ("dark", "transparent")
# chave -> rótulo exibido no seletor (na ordem do seletor)
STYLES = {"gold": "Ouro gasto", "ember": "Brasa", "parchment": "Pergaminho em brasa"}
DEFAULT_STYLE = "ember"

# Layout (px, na resolução final)
ROUTE_MAX = (860, 760)   # caixa máxima do traçado (mantém a proporção do percurso)
ROUTE_STROKE = 11
GLOW_PAD = 40            # margem em volta do traço pro brilho não ser cortado
ICON_SIZE = 380
VISUAL_GAP = 100         # traçado/ícone → métricas
COL_OFFSET = 250         # centro de cada coluna da grade 2×2, a partir do meio
COL_WIDTH = 470
LABEL_SIZE, VALUE_SIZE, UNIT_SIZE = 30, 112, 40
LABEL_TRACKING = 5       # letter-spacing dos rótulos (mono, caixa alta)
ROW_HEIGHT, ROW_GAP = 168, 56
STICKER_PAD = 48         # respiro em volta do conteúdo no sticker recortado


# ---------- formatação (pt-BR: vírgula decimal, ponto de milhar) ----------

def _num(x: float, decimals: int) -> str:
    return f"{x:,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _clock(seconds: float) -> str:
    """Tempo/pace no formato relógio: 5:12, 52:10, 1:02:45."""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ---------- dados ----------

def _route(activity) -> list[tuple[float, float]]:
    """Pontos (lat, lon) do percurso, já filtrados/suavizados pro desenho."""
    if not activity.has_gps or not activity.track_points_json:
        return []
    pts = [
        (p["lat"], p["lon"])
        for p in json.loads(activity.track_points_json)
        if p.get("lat") is not None and p.get("lon") is not None
    ]
    if activity.sport == "swimming" and len(pts) > 9:
        # GPS de pulso na água oscila muito (perde sinal a cada braçada):
        # média móvel centrada deixa o traçado legível.
        k = 4
        smoothed = []
        for i in range(len(pts)):
            window = pts[max(0, i - k):i + k + 1]
            smoothed.append((
                sum(p[0] for p in window) / len(window),
                sum(p[1] for p in window) / len(window),
            ))
        pts = smoothed
    step = math.ceil(len(pts) / 2000) or 1  # o desenho não precisa de mais que isso
    return pts[::step]


def story_metrics(activity, indoor: bool) -> list[tuple[str, str, str]]:
    """(rótulo, número, unidade) na ordem de exibição, conforme o esporte."""
    t, d = activity.total_time_s, activity.distance_m
    out: list[tuple[str, str, str]] = []

    def add(label: str, value, unit: str = "") -> None:
        if value:
            out.append((label, value, unit))

    if activity.sport == "swimming":
        add("Distância", d and _num(d, 0), "m")
        add("Pace", d and t and _clock(t / (d / 100)), "/100m")
        add("Tempo", t and _clock(t))
    elif activity.sport == "cycling":
        add("Distância", d and _num(d / 1000, 2), "km")
        add("Vel. média", d and t and _num((d / 1000) / (t / 3600), 1), "km/h")
        add("Tempo", t and _clock(t))
        if indoor:
            add("FC média", activity.avg_hr and str(activity.avg_hr), "bpm")
        else:
            ascent = round(activity.total_ascent_m or 0)
            add("Elevação", ascent and _num(ascent, 0), "m")
    else:  # corrida / caminhada (rua ou esteira)
        add("Distância", d and _num(d / 1000, 2), "km")
        add("Pace", d and t and _clock(t / (d / 1000)), "/km")
        add("Tempo", t and _clock(t))
        add("FC média", activity.avg_hr and str(activity.avg_hr), "bpm")
    return out


# ---------- desenho: geometria ----------
#
# Traçado e ícones viram um "desenhista" `stroke(draw, width, fill)` que traça a
# geometria numa imagem SS×. Os estilos só decidem com que larguras/cores chamá-lo
# e o que pôr por baixo (brilho/halo) — a geometria é uma só.

Stroke = Callable[[ImageDraw.ImageDraw, float, object], None]


def _round_line(draw: ImageDraw.ImageDraw, pts, width: float, fill) -> None:
    """Polilinha com junções e pontas arredondadas."""
    draw.line(pts, fill=fill, width=round(width), joint="curve")
    r = width / 2
    for x, y in (pts[0], pts[-1]):
        draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def _route_geometry(route) -> Optional[tuple[list[tuple[float, float]], tuple[int, int]]]:
    """Projeta o percurso: (pontos em coordenadas SS×, tamanho final 1×)."""
    if len(route) < 2:
        return None
    # Equiretangular com correção de latitude: suficiente na escala de um treino.
    lat0 = math.radians(sum(p[0] for p in route) / len(route))
    xs = [lon * math.cos(lat0) for _lat, lon in route]
    ys = [lat for lat, _lon in route]
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    pad = ROUTE_STROKE + GLOW_PAD
    scales = [
        (box - 2 * pad) / span
        for box, span in ((ROUTE_MAX[0], span_x), (ROUTE_MAX[1], span_y))
        if span > 1e-9
    ]
    if not scales:  # parado no lugar — nada pra desenhar
        return None
    scale = min(scales)
    size = (round(span_x * scale) + 2 * pad, round(span_y * scale) + 2 * pad)
    pts = [
        ((pad + (x - min(xs)) * scale) * SS, (pad + (max(ys) - y) * scale) * SS)
        for x, y in zip(xs, ys)
    ]
    return pts, size


def _wave(y: float, x0: float = 28, x1: float = 228, amp: float = 9, period: float = 66):
    return [(x, y + amp * math.sin((x - x0) / period * 2 * math.pi)) for x in range(int(x0), int(x1) + 1, 4)]


# Ícones lineares num grid 256×256 (mesma convenção do Phosphor, usado no app),
# traço "light". Primitivas: ("line", pontos) · ("circle", cx, cy, r) ·
# ("arc", cx, cy, r, início°, fim°) · ("rect", x0, y0, x1, y1, raio).
ICON_STROKE = 11
ICONS = {
    "treadmill": [
        ("rect", 20, 190, 236, 222, 16),               # lona
        ("line", [(206, 190), (184, 64)]),             # coluna do painel
        ("line", [(158, 72), (208, 56)]),              # painel
        ("line", [(194, 124), (124, 124)]),            # corrimão
        ("line", [(80, 222), (80, 236)]),              # pés
        ("line", [(186, 222), (186, 236)]),
    ],
    "indoor_bike": [
        ("line", [(44, 222), (212, 222)]),             # base
        ("line", [(78, 222), (104, 100)]),             # tubo do selim
        ("line", [(80, 94), (128, 94)]),               # selim
        ("line", [(96, 150), (172, 166)]),             # quadro → volante
        ("circle", 172, 166, 38),                      # volante de inércia
        ("line", [(158, 130), (150, 66)]),             # coluna do guidão
        ("line", [(134, 62), (186, 62)]),              # guidão
        ("line", [(172, 204), (172, 222)]),            # pé dianteiro
    ],
    "pool": [
        ("arc", 86, 70, 18, 180, 360),                 # corrimão esquerdo (curva)
        ("line", [(68, 70), (68, 88)]),
        ("line", [(104, 70), (104, 168)]),
        ("arc", 152, 70, 18, 180, 360),                # corrimão direito
        ("line", [(134, 70), (134, 88)]),
        ("line", [(170, 70), (170, 168)]),
        ("line", [(104, 108), (170, 108)]),            # degraus
        ("line", [(104, 140), (170, 140)]),
        ("line", _wave(196)),                          # água
        ("line", _wave(230)),
    ],
}


def _indoor_icon(sport: str) -> str:
    return {"cycling": "indoor_bike", "swimming": "pool"}.get(sport, "treadmill")


def _icon_stroke(name: str) -> tuple[Stroke, tuple[int, int]]:
    """Desenhista do ícone + tamanho final 1× (ícone + margem do brilho)."""
    k = ICON_SIZE * SS / 256
    off = GLOW_PAD * SS

    def stroke(draw, width, fill):
        half = width / 2

        def bbox(x0, y0, x1, y1):  # contorno centrado no caminho (Pillow desenha pra dentro)
            return (off + x0 * k - half, off + y0 * k - half, off + x1 * k + half, off + y1 * k + half)

        for prim in ICONS[name]:
            kind = prim[0]
            if kind == "line":
                _round_line(draw, [(off + x * k, off + y * k) for x, y in prim[1]], width, fill)
            elif kind == "circle":
                _, cx, cy, r = prim
                draw.ellipse(bbox(cx - r, cy - r, cx + r, cy + r), outline=fill, width=round(width))
            elif kind == "arc":
                _, cx, cy, r, start, end = prim
                draw.arc(bbox(cx - r, cy - r, cx + r, cy + r), start, end, fill=fill, width=round(width))
            elif kind == "rect":
                _, x0, y0, x1, y1, rad = prim
                draw.rounded_rectangle(bbox(x0, y0, x1, y1), radius=rad * k + half,
                                       outline=fill, width=round(width))

    side = ICON_SIZE + 2 * GLOW_PAD
    return stroke, (side, side)


# ---------- desenho: estilos ----------

def _ember_color(t: float) -> tuple[int, int, int]:
    """Degradê de brasa: funda (0) → acesa (0,55) → ponta clara (1)."""
    stops = [(0.0, EMBER), (0.55, COPPER), (1.0, EMBER_TIP)]
    t = min(max(t, 0.0), 1.0)
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0)
            return tuple(round(a + (b - a) * f) for a, b in zip(c0, c1))
    return stops[-1][1]


def _mask(stroke: Stroke, size_ss: tuple[int, int], width: float) -> Image.Image:
    mask = Image.new("L", size_ss, 0)
    stroke(ImageDraw.Draw(mask), width, 255)
    return mask


def _route_ember_line(pts, size_ss, width: float) -> Image.Image:
    """Traço colorido pelo progresso no percurso (trechos curtos, cada um numa cor)."""
    img = Image.new("RGBA", size_ss, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    chunks = 120
    step = max(1, len(pts) // chunks)
    for i in range(0, len(pts) - 1, step):
        # começa em 0,12 (não no vermelho mais fundo) pra o início não sumir no fundo escuro
        _round_line(draw, pts[i:i + step + 1], width, _ember_color(0.12 + 0.88 * i / (len(pts) - 1)) + (255,))
    return img


def _vertical_ember(mask: Image.Image) -> Image.Image:
    """Ícones: degradê de brasa de baixo (funda) pra cima (acesa), como chama."""
    _, y0, _, y1 = mask.getbbox() or (0, 0, 0, mask.height)
    column = Image.new("RGB", (1, mask.height))
    for y in range(mask.height):
        # base em 0,3: a parte de baixo do ícone (ondas, base) continua legível
        column.putpixel((0, y), _ember_color(0.3 + 0.7 * (y1 - y) / max(1, y1 - y0)))
    img = column.resize(mask.size, Image.NEAREST).convert("RGBA")
    img.putalpha(mask)
    return img


def _styled_visual(stroke: Stroke, size: tuple[int, int], width: float, style: str,
                   ember_line: Optional[Callable[[float], Image.Image]] = None) -> Image.Image:
    """Traçado/ícone renderizado no estilo, em RGBA 1× recortado no que aparece."""
    size_ss = (size[0] * SS, size[1] * SS)
    w = width * SS
    out = Image.new("RGBA", size_ss, (0, 0, 0, 0))
    base = _mask(stroke, size_ss, w)
    if style == "gold":
        out.alpha_composite(_layer(base.filter(ImageFilter.GaussianBlur(12 * SS)), GOLD, 0.35))
        out.alpha_composite(_layer(base, GOLD))
    elif style == "ember":
        out.alpha_composite(_layer(base.filter(ImageFilter.GaussianBlur(14 * SS)), COPPER, 0.55))
        out.alpha_composite(ember_line(w) if ember_line else _vertical_ember(base))
    else:  # parchment: halo = traço mais grosso desfocado; linha creme mais fina por cima
        halo = _mask(stroke, size_ss, w * 2).filter(ImageFilter.GaussianBlur(10 * SS))
        out.alpha_composite(_layer(halo, EMBER_HALO, 0.9))
        out.alpha_composite(_layer(_mask(stroke, size_ss, w * 0.7), PARCHMENT))
    # reduz em alfa pré-multiplicado (sem franja escura nas bordas semitransparentes)
    out = out.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")
    # recorta pelo que é visível (o rabo do brilho, quase transparente, não conta)
    visible = out.getchannel("A").point(lambda v: 255 if v > 12 else 0).getbbox()
    return out.crop(visible) if visible else out


def _visual(activity, style: str) -> tuple[Image.Image, bool]:
    """(traçado ou ícone já estilizado, é indoor?)."""
    geometry = _route_geometry(_route(activity))
    if geometry:
        pts, size = geometry
        stroke = lambda draw, width, fill: _round_line(draw, pts, width, fill)  # noqa: E731
        ember = lambda width: _route_ember_line(pts, (size[0] * SS, size[1] * SS), width)  # noqa: E731
        return _styled_visual(stroke, size, ROUTE_STROKE, style, ember), False
    stroke, size = _icon_stroke(_indoor_icon(activity.sport))
    return _styled_visual(stroke, size, ICON_STROKE * ICON_SIZE / 256, style), True


# ---------- desenho: texto ----------

@lru_cache(maxsize=16)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _draw_label(draw: ImageDraw.ImageDraw, cx: float, baseline: float, text: str) -> None:
    """Rótulo mono em caixa alta com letter-spacing (Pillow não tem tracking nativo)."""
    font = _font(LABEL_FONT, LABEL_SIZE)
    text = text.upper()
    widths = [font.getlength(c) for c in text]
    x = cx - (sum(widths) + LABEL_TRACKING * (len(text) - 1)) / 2
    for c, w in zip(text, widths):
        draw.text((x, baseline), c, font=font, fill=255, anchor="ls")
        x += w + LABEL_TRACKING


def _draw_value(value_draw, unit_draw, cx: float, baseline: float, number: str, unit: str, max_w: float) -> None:
    """Número grande (Fraunces) + unidade menor (mono), alinhados pela linha de base."""
    size, unit_size = VALUE_SIZE, UNIT_SIZE
    while True:  # encolhe até caber na coluna (ex.: tempos de 1:02:45)
        vf, uf = _font(VALUE_FONT, size), _font(LABEL_FONT, unit_size)
        gap = 12 if unit else 0
        num_w, unit_w = vf.getlength(number), (uf.getlength(unit) if unit else 0)
        if num_w + gap + unit_w <= max_w or size <= 60:
            break
        size, unit_size = size - 6, max(24, unit_size - 2)
    x = cx - (num_w + gap + unit_w) / 2
    value_draw.text((x, baseline), number, font=vf, fill=255, anchor="ls")
    if unit:
        unit_draw.text((x + num_w + gap, baseline), unit, font=uf, fill=255, anchor="ls")


# ---------- composição ----------

def _layer(mask: Image.Image, color: tuple[int, int, int], opacity: float = 1.0) -> Image.Image:
    """Camada RGBA de cor sólida com a máscara como alfa (composição sem franja escura)."""
    layer = Image.new("RGBA", mask.size, color + (0,))
    layer.putalpha(mask if opacity >= 1 else mask.point(lambda v: round(v * opacity)))
    return layer


def render_story(activity, bg: str = "dark", style: str = DEFAULT_STYLE) -> bytes:
    """PNG do story. `bg`: "dark" (9:16 com fundo) ou "transparent" (sticker);
    `style`: estilo do traçado (ver STYLES)."""
    if activity.sport not in STORY_SPORTS:
        raise ValueError(f"esporte sem story: {activity.sport}")
    if bg not in BACKGROUNDS:
        raise ValueError(f"fundo inválido: {bg}")
    if style not in STYLES:
        raise ValueError(f"estilo inválido: {style}")

    visual, indoor = _visual(activity, style)
    metrics = story_metrics(activity, indoor)

    rows = math.ceil(len(metrics) / 2)
    grid_h = rows * ROW_HEIGHT + max(0, rows - 1) * ROW_GAP
    total_h = visual.height + (VISUAL_GAP + grid_h if metrics else 0)
    top = (H - total_h) // 2
    visual_pos = ((W - visual.width) // 2, top)

    # Números e rótulos/unidades em máscaras separadas, compostas no fim: a mesma
    # geometria serve pras duas variações e pra sombra do sticker.
    values = Image.new("L", (W, H), 0)
    labels = Image.new("L", (W, H), 0)
    vdraw, ldraw = ImageDraw.Draw(values), ImageDraw.Draw(labels)

    grid_top = top + visual.height + VISUAL_GAP
    for i, (label, number, unit) in enumerate(metrics):
        row, col = divmod(i, 2)
        last_alone = i == len(metrics) - 1 and len(metrics) % 2 == 1
        cx = W / 2 if last_alone else W / 2 + (COL_OFFSET if col else -COL_OFFSET)
        max_w = 2 * COL_WIDTH if last_alone else COL_WIDTH
        y = grid_top + row * (ROW_HEIGHT + ROW_GAP)
        _draw_label(ldraw, cx, y + LABEL_SIZE, label)
        _draw_value(vdraw, ldraw, cx, y + LABEL_SIZE + VALUE_SIZE, number, unit, max_w)

    if bg == "dark":
        canvas = Image.new("RGBA", (W, H), BG + (255,))
        label_color, label_opacity = MUTED, 1.0
    else:
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        label_color, label_opacity = PARCHMENT, 0.8  # cinza some sobre foto
        # Sombra em duas camadas: um halo escuro justo (dilata + desfoca pouco),
        # que segura o contraste sobre foto clara, e uma sombra larga e suave.
        visual_alpha = Image.new("L", (W, H), 0)
        visual_alpha.paste(visual.getchannel("A"), visual_pos)
        union = ImageChops.lighter(visual_alpha, ImageChops.lighter(values, labels))
        halo = union.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(3))
        soft = ImageChops.offset(union.filter(ImageFilter.GaussianBlur(14)), 0, 4)
        canvas.alpha_composite(_layer(soft, (0, 0, 0), 0.45))
        canvas.alpha_composite(_layer(halo, (0, 0, 0), 0.6))

    canvas.alpha_composite(visual, dest=visual_pos)
    canvas.alpha_composite(_layer(labels, label_color, label_opacity))
    canvas.alpha_composite(_layer(values, PARCHMENT))

    if bg == "transparent":
        x0, y0, x1, y1 = canvas.getbbox() or (0, 0, W, H)
        canvas = canvas.crop((
            max(0, x0 - STICKER_PAD), max(0, y0 - STICKER_PAD),
            min(W, x1 + STICKER_PAD), min(H, y1 + STICKER_PAD),
        ))

    out = BytesIO()
    canvas.save(out, "PNG")
    return out.getvalue()


def story_filename(activity, bg: str, style: str = DEFAULT_STYLE) -> str:
    kind = "sticker" if bg == "transparent" else "story"
    return f"treino-{activity.start_time:%Y-%m-%d}-{kind}-{style}.png"
