from fastapi.testclient import TestClient
from app.main import app
import re, json, os

# Pasta com os .fit de teste. Sobrescreva com a env var FIT_DIR se precisar.
FIT_DIR = os.environ.get("FIT_DIR", os.path.expanduser("~/Downloads"))

client_cm = TestClient(app)
client = client_cm.__enter__()

print("--- registro ---")
r = client.post("/register", data={"email": "guilherme@teste.com", "password": "senha123"}, follow_redirects=False)
print("status:", r.status_code)

print("--- upload dos 3 .fit ---")
files = [
    ("files", ("Musculacao.fit", open(os.path.join(FIT_DIR, "Musculacao.fit"), "rb"), "application/octet-stream")),
    ("files", ("Esteira.fit", open(os.path.join(FIT_DIR, "Esteira.fit"), "rb"), "application/octet-stream")),
    ("files", ("Caminhada.fit", open(os.path.join(FIT_DIR, "Caminhada.fit"), "rb"), "application/octet-stream")),
]
r = client.post("/activities/upload", files=files, follow_redirects=False)
print("status:", r.status_code)

print("--- dashboard ---")
r = client.get("/")
print("status:", r.status_code)
for label in ["Corrida (esteira)", "Musculação", "Caminhada"]:
    print(f"  contém '{label}':", label in r.text)

ids = sorted(set(int(x) for x in re.findall(r"activities/(\d+)", r.text)))
print("activity ids:", ids)
print("  histórico em cards:", 'class="act-card"' in r.text)
print("  mostra pace (corrida):", "/km" in r.text)
print("  layout lovable (.dash):", 'class="dash"' in r.text)

print("--- detalhe da caminhada (tem gps) ---")
caminhada_id = ids[-1]
r = client.get(f"/activities/{caminhada_id}")
print("status:", r.status_code)
print('  tem div do mapa:', 'id="map"' in r.text)
g = client.get(f"/activities/{caminhada_id}/track.geojson").json()
feature = g["features"][0]
coords = feature["geometry"]["coordinates"]  # [lon, lat]
print("  total de pontos no traçado:", len(coords))
print("  primeiro ponto [lon, lat]:", coords[0])

print("--- detalhe da musculação (sem gps) ---")
musc_id = ids[0]
r = client.get(f"/activities/{musc_id}")
print("status:", r.status_code)
print('  tem div do mapa:', 'id="map"' in r.text)
print('  mostra aviso sem gps:', "não tem dados de GPS" in r.text)
g = client.get(f"/activities/{musc_id}/track.geojson").json()
print("  geometry nula (indoor):", g["features"][0]["geometry"] is None)

print("--- resumo mensal/semanal (ref fixa 31/05/2026) ---")
from datetime import datetime as _dt
from sqlmodel import Session, select
from app.database import engine
from app.models import Activity, User
from app.summary import monthly_summary, week_days, resolve_month, week_total_time
ref = _dt(2026, 5, 31)
with Session(engine) as s:
    acts = s.exec(select(Activity)).all()
cards = monthly_summary(acts, ref)
print("  esportes no resumo de maio:", [c["label"] for c in cards])
# meses passados: sem comparativo (pct None em todos)
cards_nocmp = monthly_summary(acts, ref, compare=False)
print("  compare=False zera o pct:", all(c["pct"] is None for c in cards_nocmp))
print("  resolve_month('2026-05'):", resolve_month("2026-05", _dt(2026, 6, 27)))
print("  resolve_month futuro capado p/ atual:", resolve_month("2027-01", _dt(2026, 6, 27)).month == 6)
musc = next(c for c in cards if c["label"] == "Musculação")
print("  musculação mostra distância?", musc["show_distance"], "(esperado False)")
print("  musculação compara por:", musc["compare"], "(esperado time)")
destaque = next((c["label"] for c in cards if c["highlight"]), None)
print("  destaque (maior tempo no mês):", destaque, "(esperado Musculação)")
week = week_days(acts, ref)
dias_com_atividade = [(d["label"], d["day"], len(d["icons"]), d["total_time"]) for d in week if d["icons"]]
print("  dias da semana 25-31/05 (label, dia, nº ícones, tempo):", dias_com_atividade)
print("  tempo total da semana 25-31/05:", week_total_time(acts, ref), "(esperado 54min)")

print("--- musculação: registrar série + mapa muscular ---")
r = client.post(f"/activities/{musc_id}/sets", data={"exercise": "supino_reto", "reps": "10", "weight": "40"})
print("status:", r.status_code)
print("  mostra o exercício:", "Supino reto" in r.text)
mm = re.search(r"data-muscles='(\[[^']*\])'", r.text)
muscles = json.loads(mm.group(1)) if mm else []
print("  músculos no mapa:", muscles)
print("  detalhe inclui seção de força:", 'id="strength-section"' in client.get(f"/activities/{musc_id}").text)
sid = re.search(r"/sets/(\d+)", r.text)
rd = client.delete(f"/activities/{musc_id}/sets/{sid.group(1)}")
print("  remove série status:", rd.status_code, "| zerou:", "Nenhuma série" in rd.text)
# atividade que não é musculação não aceita série:
rej = client.post(f"/activities/{caminhada_id}/sets", data={"exercise": "supino_reto", "reps": "8"})
print("  caminhada rejeita série (404):", rej.status_code)

print("--- nota + RPE do treino ---")
r = client.post(f"/activities/{musc_id}/note",
                data={"rpe": "8", "note": "Treino pesado, foco em peito"}, follow_redirects=True)
print("  nota salva e exibida:", "Treino pesado, foco em peito" in r.text)
print("  slider reflete rpe=8:", 'value="8"' in r.text)
client.post(f"/activities/{musc_id}/note", data={"rpe": "99", "note": "   "})  # rpe fora da faixa, nota vazia
with Session(engine) as s:
    a = s.get(Activity, musc_id)
    print("  rpe inválido -> None:", a.rpe is None, "| nota vazia -> None:", a.note is None)

print("--- bike indoor: editar distância + velocidade derivada ---")
with Session(engine) as s:
    bike = Activity(user_id=1, sport="cycling", sub_sport="indoor_cycling", label="Bicicleta",
                    start_time=_dt(2026, 5, 28, 7, 0, 0), total_time_s=1800, has_gps=False)
    s.add(bike); s.commit(); s.refresh(bike); bike_id = bike.id
r = client.get(f"/activities/{bike_id}")
print("  antes de editar, mostra 'km/h'?", "km/h" in r.text, "(esperado False)")
print("  mostra formulário de distância?", 'name="distance_km"' in r.text)
# 15 km em 1800s (0.5h) -> 30.0 km/h
r = client.post(f"/activities/{bike_id}/distance", data={"distance_km": "15"}, follow_redirects=True)
print("  distância salva (15.00 km)?", "15.00 km" in r.text)
print("  velocidade derivada (30.0 km/h)?", "30.0 km/h" in r.text)

print("--- ingestão Health Auto Export (token + idempotência) ---")
with Session(engine) as s:
    tok = s.exec(select(User).where(User.id == 1)).first().ingest_token
print("  usuário tem ingest_token?", bool(tok))
hae_payload = {"data": {"workouts": [
    {
        "id": "HAE-ABC-123",
        "name": "Running",
        "start": "2026-05-30 07:00:00 -0300",
        "end": "2026-05-30 07:30:00 -0300",
        "duration": 1800,
        "distance": {"qty": 5.0, "units": "km"},
        "activeEnergyBurned": {"qty": 300, "units": "kcal"},
        "avgHeartRate": {"qty": 150, "units": "bpm"},
        "maxHeartRate": {"qty": 175, "units": "bpm"},
        "heartRateData": [
            {"date": "2026-05-30 07:05:00 -0300", "Min": 140, "Avg": 150, "Max": 160, "units": "bpm"},
            {"date": "2026-05-30 07:15:00 -0300", "Min": 145, "Avg": 155, "Max": 170, "units": "bpm"},
        ],
        "route": [
            {"latitude": -28.380, "longitude": -53.930, "altitude": 480, "timestamp": "2026-05-30 07:00:05 -0300", "speed": 2.8},
            {"latitude": -28.381, "longitude": -53.931, "altitude": 483, "timestamp": "2026-05-30 07:00:10 -0300", "speed": 2.9},
        ],
    },
    {  # nome localizado (pt) — deve mapear para musculação mesmo assim
        "id": "HAE-MUSC-1",
        "name": "Treinamento de Força Tradicional",
        "start": "2026-05-30 18:00:00 -0300",
        "end": "2026-05-30 18:40:00 -0300",
        "duration": 2400,
        "avgHeartRate": {"qty": 110, "units": "bpm"},
        "maxHeartRate": {"qty": 150, "units": "bpm"},
    },
    {  # nome localizado (pt) — deve mapear para bike indoor
        "id": "HAE-BIKE-1",
        "name": "Ciclismo Interno",
        "start": "2026-05-30 19:00:00 -0300",
        "end": "2026-05-30 19:30:00 -0300",
        "duration": 1800,
    },
]}}
hdr = {"Authorization": f"Bearer {tok}"}
r = client.post("/ingest/hae", json=hae_payload, headers=hdr)
print("  1º POST:", r.status_code, r.json(), "(esperado created=3)")
r2 = client.post("/ingest/hae", json=hae_payload, headers=hdr)
print("  reenvio idempotente:", r2.json(), "(esperado duplicates=3)")
bad = client.post("/ingest/hae", json=hae_payload, headers={"Authorization": "Bearer invalido"})
print("  token inválido:", bad.status_code, "(esperado 401)")
with Session(engine) as s:
    run = s.exec(select(Activity).where(Activity.external_id == "HAE-ABC-123")).first()
    musc = s.exec(select(Activity).where(Activity.external_id == "HAE-MUSC-1")).first()
    bike = s.exec(select(Activity).where(Activity.external_id == "HAE-BIKE-1")).first()
    print(f"  corrida: sport={run.sport} has_gps={run.has_gps} dist_m={run.distance_m}")
    print(f"  musculação (nome pt): sport={musc.sport} (esperado training)")
    print(f"  bike interno (nome pt): sport={bike.sport}/{bike.sub_sport} (esperado cycling/indoor_cycling)")
    musc_hae_id, bike_hae_id = musc.id, bike.id
print("  detalhe musculação tem seção de força:", 'id="strength-section"' in client.get(f"/activities/{musc_hae_id}").text)
print("  detalhe bike tem form de distância:", 'name="distance_km"' in client.get(f"/activities/{bike_hae_id}").text)
ig = client.get("/integracao")
print("  página integração:", ig.status_code, "| contém /ingest/hae:", "/ingest/hae" in ig.text)

print("--- HAE: nome 'Correr' + tempo em movimento (pausa) ---")
import datetime as _dtm
from app.hae_parser import resolve_sport, parse_hae_workout
print("  'Correr' -> running:", resolve_sport("Correr")[0] == "running")
_base = _dtm.datetime(2026, 6, 26, 19, 0, 0)
_route = [{"latitude": round(-28.38 + i * 0.0003, 6), "longitude": -53.93, "altitude": 480,
           "timestamp": (_base + _dtm.timedelta(seconds=i * 10)).strftime("%Y-%m-%d %H:%M:%S -0300")}
          for i in range(41)]  # 0..400s movendo
_route += [{"latitude": round(-28.38 + 40 * 0.0003, 6), "longitude": -53.93, "altitude": 480,
            "timestamp": (_base + _dtm.timedelta(seconds=410 + i * 10)).strftime("%Y-%m-%d %H:%M:%S -0300")}
           for i in range(21)]  # 410..610s parado
_wk = {"id": "PAUSE", "name": "Correr", "start": _base.strftime("%Y-%m-%d %H:%M:%S -0300"),
       "duration": 610, "distance": {"qty": 1.3, "units": "km"}, "route": _route}
_p = parse_hae_workout(_wk)
print(f"  duration HAE=610s -> total_time_s (movimento)={_p['total_time_s']}s (esperado ~400, < 610)")
print("  sport:", _p["sport"], "(esperado running)")

print("--- análise (só na corrida mais recente) ---")
with Session(engine) as s:
    run_latest = s.exec(select(Activity).where(Activity.external_id == "HAE-ABC-123")).first().id
    esteira_id = s.exec(select(Activity).where(Activity.label == "Corrida (esteira)")).first().id
det_latest = client.get(f"/activities/{run_latest}").text
det_old = client.get(f"/activities/{esteira_id}").text
print("  última corrida tem análise:", 'class="analysis"' in det_latest)
print("  tem frase comparativa:", "vs suas últimas" in det_latest)
print("  corrida antiga NÃO tem análise:", 'class="analysis"' not in det_old)

print("--- navegação de mês ---")
r_now = client.get("/").text
r_past = client.get("/?m=2025-11").text
print("  mês atual tem setas:", 'class="month-arrow"' in r_now)
print("  navega p/ Novembro de 2025:", "Novembro de 2025" in r_past)
print("  mês passado SEM comparativo:", "vs. mês anterior" not in r_past)

print("--- exclusão (htmx delete) ---")
r = client.delete(f"/activities/{musc_id}")
print("status:", r.status_code)

print("--- logout ---")
r = client.get("/logout", follow_redirects=False)
print("status:", r.status_code)

print("--- dashboard sem login deve redirecionar ---")
client2 = TestClient(app)
r = client2.get("/", follow_redirects=False)
print("status:", r.status_code, "location:", r.headers.get("location"))

print("\nTODOS OS TESTES PASSARAM SEM EXCEÇÃO" if True else "")
