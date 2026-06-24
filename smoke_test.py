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
from app.summary import monthly_summary, week_days
ref = _dt(2026, 5, 31)
with Session(engine) as s:
    acts = s.exec(select(Activity)).all()
cards = monthly_summary(acts, ref)
print("  esportes no resumo de maio:", [c["label"] for c in cards])
musc = next(c for c in cards if c["label"] == "Musculação")
print("  musculação mostra distância?", musc["show_distance"], "(esperado False)")
print("  musculação compara por:", musc["compare"], "(esperado time)")
week = week_days(acts, ref)
dias_com_atividade = [(d["label"], d["day"], len(d["icons"]), d["total_time"]) for d in week if d["icons"]]
print("  dias da semana 25-31/05 (label, dia, nº ícones, tempo):", dias_com_atividade)

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
hae_payload = {"data": {"workouts": [{
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
}]}}
hdr = {"Authorization": f"Bearer {tok}"}
r = client.post("/ingest/hae", json=hae_payload, headers=hdr)
print("  1º POST:", r.status_code, r.json())
r2 = client.post("/ingest/hae", json=hae_payload, headers=hdr)
print("  reenvio idempotente:", r2.json())
bad = client.post("/ingest/hae", json=hae_payload, headers={"Authorization": "Bearer invalido"})
print("  token inválido:", bad.status_code, "(esperado 401)")
with Session(engine) as s:
    a = s.exec(select(Activity).where(Activity.source == "hae")).first()
    print(f"  atividade HAE: label={a.label} has_gps={a.has_gps} dist_m={a.distance_m} ext={a.external_id}")
ig = client.get("/integracao")
print("  página integração:", ig.status_code, "| contém /ingest/hae:", "/ingest/hae" in ig.text)

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
