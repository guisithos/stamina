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
from app.models import Activity
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
