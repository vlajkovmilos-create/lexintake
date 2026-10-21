import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Advokat
from ..config import get_settings

settings = get_settings()

ALGORITAM = "HS256"
TOKEN_TRAJANJE_SATI = 24
PROBNI_PERIOD_DANA = 14

_bearer = HTTPBearer(auto_error=False)

def hashuj_lozinku(lozinka: str) -> str:
    return bcrypt.hashpw(lozinka.encode(), bcrypt.gensalt()).decode()

def proveri_lozinku(lozinka: str, hash: str) -> bool:
    try:
        return bcrypt.checkpw(lozinka.encode(), hash.encode())
    except ValueError:
        return False

def kreiraj_token(podaci: dict) -> str:
    kopija = podaci.copy()
    istice = datetime.utcnow() + timedelta(hours=TOKEN_TRAJANJE_SATI)
    kopija.update({"exp": istice})
    return jwt.encode(kopija, settings.secret_key, algorithm=ALGORITAM)

def kreiraj_kratki_token(podaci: dict, sekundi: int) -> str:
    """Token za jednu namenu (npr. link za PDF); ne važi kao token za prijavu jer ima 'svrha'."""
    kopija = podaci.copy()
    kopija.update({"exp": datetime.utcnow() + timedelta(seconds=sekundi)})
    return jwt.encode(kopija, settings.secret_key, algorithm=ALGORITAM)

def dekoduj_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITAM])
    except jwt.PyJWTError:
        return None

def generisi_javni_kod() -> str:
    return secrets.token_urlsafe(9)

def nadji_po_emailu(db: Session, email: str) -> Optional[Advokat]:
    return db.query(Advokat).filter(func.lower(Advokat.email) == email.strip().lower()).first()

def trenutni_advokat(
    kredencijali: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db)
) -> Advokat:
    """Zavisnost za sve rute advokata: vraća advokata iz JWT tokena ili 401."""
    if not kredencijali or kredencijali.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Niste prijavljeni")

    podaci = dekoduj_token(kredencijali.credentials)
    if not podaci or "svrha" in podaci or not str(podaci.get("sub", "")).isdigit():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Neispravan ili istekao token")

    advokat = db.query(Advokat).filter(Advokat.id == int(podaci["sub"])).first()
    if not advokat:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Advokat nije pronađen")
    return advokat

def vlasnik_kancelarije(db: Session, advokat: Advokat) -> Advokat:
    """Vraća nalog vlasnika kancelarije (za vlasnika i advokata bez tima to je on sam)."""
    if advokat.vlasnik_id is None:
        return advokat
    return db.query(Advokat).filter(Advokat.id == advokat.vlasnik_id).first() or advokat

def registruj_advokata(db: Session, ime: str, email: str, lozinka: str, naziv_kancelarije: str = None, telefon: str = None) -> Advokat:
    email = email.strip().lower()
    if nadji_po_emailu(db, email):
        raise ValueError("Advokat sa ovim emailom već postoji")

    advokat = Advokat(
        ime=ime,
        email=email,
        lozinka_hash=hashuj_lozinku(lozinka),
        naziv_kancelarije=naziv_kancelarije,
        telefon=telefon,
        javni_kod=generisi_javni_kod(),
        plan="probni",
        status_pretplate="probni_period",
        datum_isteka_probe=datetime.utcnow() + timedelta(days=PROBNI_PERIOD_DANA)
    )
    db.add(advokat)
    db.commit()
    db.refresh(advokat)
    return advokat

def prijavi_advokata(db: Session, email: str, lozinka: str) -> Optional[Advokat]:
    advokat = nadji_po_emailu(db, email)
    if not advokat:
        return None
    if not proveri_lozinku(lozinka, advokat.lozinka_hash):
        return None
    return advokat
