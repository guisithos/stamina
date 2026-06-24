import json
import os
from datetime import datetime

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from starlette.middleware.sessions import SessionMiddleware

from .auth import get_current_user, get_user_by_email, hash_password, verify_password
from .database import create_db_and_tables, get_session
from .fit_parser import parse_fit
from .geo import track_to_geojson
from .metrics import (
    activity_metrics,
    format_date,
    format_distance,
    format_duration,
    format_pace,
    sport_icon,
)
from .models import Activity, User
from .summary import month_name, monthly_summary, week_days

app = FastAPI(title="Stamina")

SECRET_KEY = os.getenv("SECRET_KEY", "troque-essa-chave-antes-de-ir-pra-produção")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


templates.env.filters["duration"] = format_duration
templates.env.filters["distance"] = format_distance
templates.env.filters["datebr"] = format_date
templates.env.filters["pace"] = format_pace
# funções usadas direto no template (decisão por esporte mora em metrics.py)
templates.env.globals["card_metrics"] = activity_metrics
templates.env.globals["sport_icon"] = sport_icon


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


# ---------- auth ----------

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "error": None})


@app.post("/register")
def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    if get_user_by_email(session, email):
        return templates.TemplateResponse(
            "register.html", {"request": request, "error": "Esse e-mail já está cadastrado."}
        )
    user = User(email=email, hashed_password=hash_password(password))
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
def dashboard(request: Request, session: Session = Depends(get_session)):
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
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "activities": activities,
            "month_summary": monthly_summary(activities, now),
            "month_name": month_name(now),
            "week": week_days(activities, now),
        },
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
    for upload in files:
        try:
            raw = upload.file.read()
            parsed = parse_fit(raw)
            activity = Activity(
                user_id=user.id,
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
                raw_filename=upload.filename,
            )
            session.add(activity)
        except Exception as exc:  # arquivo inválido/corrompido — não derruba o upload dos outros
            errors.append(f"{upload.filename}: {exc}")
    session.commit()
    return RedirectResponse(url="/", status_code=303)


@app.delete("/activities/{activity_id}")
def delete_activity(
    request: Request, activity_id: int, session: Session = Depends(get_session)
):
    user = get_current_user(request, session)
    if not user:
        return HTMLResponse(status_code=401)
    activity = session.get(Activity, activity_id)
    if activity and activity.user_id == user.id:
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
    return templates.TemplateResponse(
        "activity_detail.html",
        {"request": request, "user": user, "activity": activity},
    )


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
