import json
import os
import secrets
from datetime import date, datetime
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, select
from starlette.middleware.sessions import SessionMiddleware

from .auth import get_current_user, get_user_by_email, hash_password, verify_password
from .database import create_db_and_tables, engine, get_session, run_light_migrations
from .analysis import build_run_analysis
from .fit_parser import friendly_sport, parse_fit
from .geo import track_to_geojson
from .hae_parser import parse_hae_workout, resolve_sport
from .metrics import (
    activity_metrics,
    format_date,
    format_distance,
    format_duration,
    format_pace,
    format_speed,
    sport_icon,
)
from .models import Activity, StrengthSet, User
from .strength import EXERCISE_GROUPS, EXERCISES, exercise_label, muscles_for
from .summary import (
    month_name,
    month_param,
    monthly_summary,
    month_activities,
    resolve_month,
    shift_month,
    week_days,
    week_summary,
)

app = FastAPI(title="Stamina")

# Fly injeta FLY_APP_NAME nas máquinas — usamos como sinal de "estou em produção".
IS_PROD = bool(os.getenv("FLY_APP_NAME"))

# Chave que assina o cookie de sessão. Em produção é OBRIGATÓRIO vir do ambiente
# (fly secrets set SECRET_KEY=...). Nunca cair num default fixo: como o repositório
# é público, um default conhecido permitiria forjar a sessão de qualquer usuário.
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    if IS_PROD:
        raise RuntimeError(
            "SECRET_KEY não definido em produção. "
            "Rode: fly secrets set SECRET_KEY=$(python -c \"import secrets;print(secrets.token_hex(32))\")"
        )
    SECRET_KEY = "dev-only-inseguro-nao-usar-em-producao"  # só desenvolvimento local

# Tamanho/quantidade máximos de upload — evita exaurir a memória da máquina (256MB).
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB por arquivo (um .fit real tem < 1 MB)
MAX_FILES_PER_UPLOAD = 25
MAX_INGEST_BYTES = 25 * 1024 * 1024  # 25 MB por payload do Health Auto Export

# Permite fechar o cadastro depois de criar sua conta (ALLOW_REGISTRATION=false).
ALLOW_REGISTRATION = os.getenv("ALLOW_REGISTRATION", "true").lower() != "false"

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    https_only=IS_PROD,          # cookie só trafega por HTTPS em produção
    same_site="lax",             # mitiga CSRF em requisições cross-site
    max_age=60 * 60 * 24 * 14,   # sessão expira em 14 dias
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"  # anti-clickjacking
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


templates.env.filters["duration"] = format_duration
templates.env.filters["distance"] = format_distance
templates.env.filters["datebr"] = format_date
templates.env.filters["pace"] = format_pace
templates.env.filters["speed"] = format_speed
# funções usadas direto no template (decisão por esporte mora em metrics.py)
templates.env.globals["card_metrics"] = activity_metrics
templates.env.globals["sport_icon"] = sport_icon
templates.env.globals["exercise_label"] = exercise_label


KNOWN_SPORTS = {"running", "cycling", "training", "walking", "swimming"}


def normalize_hae_sports() -> None:
    """Conserta atividades do HAE que entraram com `sport` genérico (nome do treino
    veio localizado e não foi reconhecido). Re-deriva pelo rótulo. Idempotente."""
    with Session(engine) as session:
        activities = session.exec(select(Activity).where(Activity.source == "hae")).all()
        changed = 0
        for a in activities:
            if a.sport in KNOWN_SPORTS:
                continue
            sport, sub = resolve_sport(a.label or a.sport)
            if sport in KNOWN_SPORTS:
                a.sport, a.sub_sport, a.label = sport, sub, friendly_sport(sport, sub)
                session.add(a)
                changed += 1
        if changed:
            session.commit()
            print(f"[startup] sports do HAE normalizados: {changed}")


@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    run_light_migrations()
    normalize_hae_sports()


# ---------- auth ----------

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if not ALLOW_REGISTRATION:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("register.html", {"request": request, "error": None})


@app.post("/register")
def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    if not ALLOW_REGISTRATION:
        return RedirectResponse(url="/login", status_code=303)

    def _error(msg: str):
        return templates.TemplateResponse("register.html", {"request": request, "error": msg})

    if len(password) < 8:
        return _error("A senha precisa de ao menos 8 caracteres.")
    if len(password.encode("utf-8")) > 72:
        # bcrypt trunca em 72 bytes silenciosamente — melhor rejeitar.
        return _error("Senha muito longa (máximo 72 caracteres).")
    if get_user_by_email(session, email):
        return _error("Esse e-mail já está cadastrado.")

    user = User(
        email=email,
        hashed_password=hash_password(password),
        ingest_token=secrets.token_urlsafe(32),  # já nasce pronto pra ingestão automática
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    user = get_user_by_email(session, email)
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "E-mail ou senha inválidos."}
        )
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


# ---------- dashboard ----------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, m: str = "", session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    statement = (
        select(Activity)
        .where(Activity.user_id == user.id)
        .order_by(Activity.start_time.desc())
    )
    activities = session.exec(statement).all()
    now = datetime.now()

    ref = resolve_month(m, now)  # mês selecionado (dia 1), nunca além do atual
    nxt = shift_month(ref, 1)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            # mensal = só totais do mês (navegável); a comparação vive no semanal
            "month_summary": monthly_summary(activities, ref, compare=False),
            "month_name": month_name(ref),
            "month_prev": month_param(shift_month(ref, -1)),
            "month_next": month_param(nxt) if nxt <= date(now.year, now.month, 1) else None,
            # semanal (topo): calendário + comparação vs semana passada
            "week": week_days(activities, now),
            "week_cmp": week_summary(activities, now),
            # histórico do MÊS selecionado (acompanha a navegação acima)
            "history": month_activities(activities, ref),
        },
    )


HISTORY_PAGE_SIZE = 15


@app.get("/historico", response_class=HTMLResponse)
def history_all(request: Request, page: int = 1, session: Session = Depends(get_session)):
    """Histórico completo, paginado (15 por página)."""
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    total = session.exec(
        select(func.count(Activity.id)).where(Activity.user_id == user.id)
    ).one()
    pages = max(1, (total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
    page = min(max(1, page), pages)
    items = session.exec(
        select(Activity)
        .where(Activity.user_id == user.id)
        .order_by(Activity.start_time.desc())
        .offset((page - 1) * HISTORY_PAGE_SIZE)
        .limit(HISTORY_PAGE_SIZE)
    ).all()
    return templates.TemplateResponse(
        "historico.html",
        {"request": request, "user": user, "activities": items,
         "page": page, "pages": pages, "total": total},
    )


@app.post("/activities/upload")
def upload_activities(
    request: Request,
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
):
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    errors = []
    for upload in files[:MAX_FILES_PER_UPLOAD]:
        try:
            raw = upload.file.read()
            if len(raw) > MAX_UPLOAD_BYTES:
                raise ValueError("arquivo grande demais (máx 10 MB)")
            parsed = parse_fit(raw)
            session.add(_activity_from_parsed(user.id, parsed, source="fit", raw_filename=upload.filename))
        except Exception as exc:  # arquivo inválido/corrompido — não derruba o upload dos outros
            errors.append(f"{upload.filename}: {exc}")
    session.commit()
    return RedirectResponse(url="/", status_code=303)


def _activity_from_parsed(user_id, parsed, *, source, external_id=None, raw_filename=None) -> Activity:
    """Constrói uma Activity a partir do dict que parse_fit / parse_hae_workout devolvem.
    Um único ponto de criação para as duas origens (FIT manual e Health Auto Export)."""
    return Activity(
        user_id=user_id,
        source=source,
        external_id=external_id,
        sport=parsed["sport"] or "unknown",
        sub_sport=parsed["sub_sport"],
        label=parsed["label"],
        start_time=parsed["start_time"] or datetime.utcnow(),
        total_time_s=parsed["total_time_s"] or 0,
        avg_hr=parsed["avg_hr"],
        min_hr=parsed["min_hr"],
        max_hr=parsed["max_hr"],
        calories=parsed["calories"],
        distance_m=parsed["distance_m"],
        total_ascent_m=parsed["total_ascent_m"],
        total_descent_m=parsed["total_descent_m"],
        has_gps=parsed["has_gps"],
        track_points_json=json.dumps(parsed["track_points"]),
        raw_filename=raw_filename,
    )


def _extract_ingest_token(request: Request) -> Optional[str]:
    """Token via Authorization: Bearer, header X-Ingest-Token ou ?token= (nessa ordem)."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-ingest-token") or request.query_params.get("token")


@app.post("/ingest/hae")
async def ingest_hae(request: Request, session: Session = Depends(get_session)):
    """Recebe o payload JSON do Health Auto Export e cria atividades (idempotente).
    Auth por token de usuário — sem cookie de sessão (chamada máquina-a-máquina)."""
    token = _extract_ingest_token(request)
    user = session.exec(select(User).where(User.ingest_token == token)).first() if token else None
    if not user:
        return JSONResponse(status_code=401, content={"detail": "token de ingestão inválido"})

    raw = await request.body()
    if len(raw) > MAX_INGEST_BYTES:
        return JSONResponse(status_code=413, content={"detail": "payload grande demais"})
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "JSON inválido"})

    workouts = ((payload.get("data") or {}).get("workouts")) or []
    created = duplicates = errors = 0
    for w in workouts:
        try:
            ext = str(w.get("id")) if w.get("id") is not None else None
            if ext and session.exec(
                select(Activity).where(
                    Activity.user_id == user.id,
                    Activity.source == "hae",
                    Activity.external_id == ext,
                )
            ).first():
                duplicates += 1  # idempotência: já ingerido, não duplica
                continue
            parsed = parse_hae_workout(w)
            session.add(_activity_from_parsed(user.id, parsed, source="hae", external_id=ext))
            created += 1
        except Exception as exc:  # um workout ruim não derruba os outros
            errors += 1
            print(f"[ingest/hae] erro no workout id={w.get('id')}: {exc}")
    session.commit()
    print(f"[ingest/hae] user={user.id} criados={created} duplicados={duplicates} erros={errors}")
    return {"created": created, "duplicates": duplicates, "errors": errors}


@app.delete("/activities/{activity_id}")
def delete_activity(
    request: Request, activity_id: int, session: Session = Depends(get_session)
):
    user = get_current_user(request, session)
    if not user:
        return HTMLResponse(status_code=401)
    activity = session.get(Activity, activity_id)
    if activity and activity.user_id == user.id:
        # SQLite não faz cascade automático — remove as séries de musculação antes.
        for s in session.exec(select(StrengthSet).where(StrengthSet.activity_id == activity.id)).all():
            session.delete(s)
        session.delete(activity)
        session.commit()
    return HTMLResponse("")  # HTMX remove a linha da tela, não precisa de conteúdo


@app.get("/activities/{activity_id}", response_class=HTMLResponse)
def activity_detail(
    request: Request, activity_id: int, session: Session = Depends(get_session)
):
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    activity = session.get(Activity, activity_id)
    if not activity or activity.user_id != user.id:
        return RedirectResponse(url="/", status_code=303)

    # Os pontos do percurso NÃO vão embutidos no HTML — a página os busca via
    # GET /activities/{id}/track.geojson. Mantém o HTML leve e a geometria
    # cacheável/reutilizável.
    context = {"request": request, "user": user, "activity": activity}
    if activity.sport == "training":  # musculação ganha o registro de séries + mapa muscular
        context.update(_strength_context(activity, session))
    elif activity.sport == "running":
        # Análise comparativa só na corrida MAIS RECENTE (por ora).
        latest_run = session.exec(
            select(Activity)
            .where(Activity.user_id == user.id, Activity.sport == "running")
            .order_by(Activity.start_time.desc())
        ).first()
        if latest_run and latest_run.id == activity.id:
            previous = session.exec(
                select(Activity)
                .where(Activity.user_id == user.id, Activity.sport == "running",
                       Activity.start_time < activity.start_time)
                .order_by(Activity.start_time.desc())
                .limit(5)
            ).all()
            context["analysis"] = build_run_analysis(activity, list(previous))
    return templates.TemplateResponse("activity_detail.html", context)


def _strength_context(activity: Activity, session: Session) -> dict:
    """Monta o contexto da seção de musculação: séries agrupadas por exercício +
    músculos agregados (JSON pro mapa) + catálogo pro <select>."""
    sets = session.exec(
        select(StrengthSet).where(StrengthSet.activity_id == activity.id).order_by(StrengthSet.id)
    ).all()
    grouped: dict[str, list] = {}
    for s in sets:
        grouped.setdefault(s.exercise, []).append(s)
    muscles = sorted(muscles_for(grouped.keys()))
    return {
        "grouped_sets": grouped,
        "muscles_json": json.dumps(muscles),
        "exercise_groups": EXERCISE_GROUPS,
    }


def _strength_partial(activity: Activity, session: Session, request: Request):
    """Renderiza só a seção de musculação (usada nas respostas HTMX de add/remove série)."""
    ctx = {"request": request, "activity": activity}
    ctx.update(_strength_context(activity, session))
    return templates.TemplateResponse("_strength.html", ctx)


@app.post("/activities/{activity_id}/sets", response_class=HTMLResponse)
def add_strength_set(
    request: Request,
    activity_id: int,
    exercise: str = Form(...),
    reps: str = Form(""),
    weight: str = Form(""),
    session: Session = Depends(get_session),
):
    user = get_current_user(request, session)
    if not user:
        return HTMLResponse(status_code=401)
    activity = session.get(Activity, activity_id)
    if not activity or activity.user_id != user.id or activity.sport != "training":
        return HTMLResponse(status_code=404)
    if exercise not in EXERCISES:
        return HTMLResponse(status_code=400)

    def _to_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def _to_float(v):
        try:
            return float(str(v).replace(",", "."))
        except (TypeError, ValueError):
            return None

    session.add(StrengthSet(
        activity_id=activity.id,
        exercise=exercise,
        reps=_to_int(reps),
        weight_kg=_to_float(weight),
    ))
    session.commit()
    return _strength_partial(activity, session, request)


@app.delete("/activities/{activity_id}/sets/{set_id}", response_class=HTMLResponse)
def delete_strength_set(
    request: Request, activity_id: int, set_id: int, session: Session = Depends(get_session)
):
    user = get_current_user(request, session)
    if not user:
        return HTMLResponse(status_code=401)
    activity = session.get(Activity, activity_id)
    if not activity or activity.user_id != user.id:
        return HTMLResponse(status_code=404)
    s = session.get(StrengthSet, set_id)
    if s and s.activity_id == activity.id:
        session.delete(s)
        session.commit()
    return _strength_partial(activity, session, request)


@app.get("/integracao", response_class=HTMLResponse)
def integration_page(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if not user.ingest_token:  # usuário antigo sem token ainda
        user.ingest_token = secrets.token_urlsafe(32)
        session.add(user)
        session.commit()
        session.refresh(user)

    base = str(request.base_url).rstrip("/")
    if "127.0.0.1" not in base and "localhost" not in base:
        base = base.replace("http://", "https://")  # Fly serve HTTPS atrás do proxy
    return templates.TemplateResponse(
        "integracao.html",
        {
            "request": request,
            "user": user,
            "ingest_url": f"{base}/ingest/hae?token={user.ingest_token}",
            "ingest_endpoint": f"{base}/ingest/hae",
            "token": user.ingest_token,
        },
    )


@app.post("/integracao/regenerate")
def integration_regenerate(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    user.ingest_token = secrets.token_urlsafe(32)
    session.add(user)
    session.commit()
    return RedirectResponse(url="/integracao", status_code=303)


@app.post("/activities/{activity_id}/note")
def edit_note(
    request: Request,
    activity_id: int,
    rpe: str = Form(""),
    note: str = Form(""),
    session: Session = Depends(get_session),
):
    """Salva RPE (0–10) e a nota livre do treino."""
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    activity = session.get(Activity, activity_id)
    if not activity or activity.user_id != user.id:
        return RedirectResponse(url="/", status_code=303)

    try:
        r = int(rpe)
        activity.rpe = r if 0 <= r <= 10 else None
    except (TypeError, ValueError):
        activity.rpe = None
    activity.note = note.strip() or None
    session.add(activity)
    session.commit()
    return RedirectResponse(url=f"/activities/{activity_id}", status_code=303)


@app.post("/activities/{activity_id}/distance")
def edit_distance(
    request: Request,
    activity_id: int,
    distance_km: str = Form(""),
    session: Session = Depends(get_session),
):
    """Distância manual para bike indoor (relógio não capta, sem ciclo-computador).
    A velocidade média é derivada de distância/tempo na exibição — não é gravada."""
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    activity = session.get(Activity, activity_id)
    # só faz sentido pra bike indoor (cycling sem GPS)
    if not activity or activity.user_id != user.id or activity.sport != "cycling" or activity.has_gps:
        return RedirectResponse(url="/", status_code=303)

    try:
        km = float(distance_km.replace(",", "."))
        activity.distance_m = km * 1000 if km > 0 else None
    except (TypeError, ValueError):
        activity.distance_m = None
    session.add(activity)
    session.commit()
    return RedirectResponse(url=f"/activities/{activity_id}", status_code=303)


@app.get("/activities/{activity_id}/track.geojson")
def activity_track(
    request: Request, activity_id: int, session: Session = Depends(get_session)
):
    """Geometria + séries da atividade em GeoJSON, consumida pelo mapa/gráfico."""
    user = get_current_user(request, session)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "não autenticado"})
    activity = session.get(Activity, activity_id)
    if not activity or activity.user_id != user.id:
        return JSONResponse(status_code=404, content={"detail": "atividade não encontrada"})

    points = json.loads(activity.track_points_json) if activity.track_points_json else []
    return JSONResponse(track_to_geojson(points))
