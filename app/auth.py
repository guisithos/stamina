from typing import Optional

import bcrypt
from fastapi import Request
from sqlmodel import Session, select

from .models import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def get_current_user(request: Request, session: Session) -> Optional[User]:
    """Lê o user_id guardado na sessão (cookie assinado) e busca o usuário.
    Retorna None se não estiver logado — quem chama decide o que fazer
    (normalmente redirecionar pra /login)."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return session.get(User, user_id)


def get_user_by_email(session: Session, email: str) -> Optional[User]:
    statement = select(User).where(User.email == email)
    return session.exec(statement).first()
