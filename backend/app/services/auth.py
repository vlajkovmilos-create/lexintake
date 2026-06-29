from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from ..models import Advokat
from ..config import get_settings

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITAM = "HS256"
TOKEN_TRAJANJE_SATI = 24

def hashuj_lozinku(lozinka: str) -> str:
    return pwd_context.hash(lozinka)

def proveri_lozinku(lozinka: str, hash: str) -> bool:
    return pwd_context.verify(lozinka, hash)

def kreiraj_token(podaci: dict) -> str:
    kopija = podaci.copy()
    istice = datetime.utcnow() + timedelta(hours=TOKEN_TRAJANJE_SATI)
    kopija.update({"exp": istice})
    return jwt.encode(kopija, settings.secret_key, algorithm=ALGORITAM)

def dekoduj_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITAM])
    except JWTError:
        return None

def registruj_advokata(db: Session, ime: str, email: str, lozinka: str, naziv_kancelarije: str = None, telefon: str = None) -> Advokat:
    postoji = db.query(Advokat).filter(Advokat.email == email).first()
    if postoji:
        raise ValueError("Advokat sa ovim emailom već postoji")

    advokat = Advokat(
        ime=ime,
        email=email,
        lozinka_hash=hashuj_lozinku(lozinka),
        naziv_kancelarije=naziv_kancelarije,
        telefon=telefon
    )
    db.add(advokat)
    db.commit()
    db.refresh(advokat)
    return advokat

def prijavi_advokata(db: Session, email: str, lozinka: str) -> Optional[Advokat]:
    advokat = db.query(Advokat).filter(Advokat.email == email).first()
    if not advokat:
        return None
    if not proveri_lozinku(lozinka, advokat.lozinka_hash):
        return None
    return advokat