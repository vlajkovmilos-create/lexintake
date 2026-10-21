from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Advokat
from ..services.auth import registruj_advokata, prijavi_advokata, kreiraj_token, trenutni_advokat
from ..services.placanje import osvezi_status_pretplate, LIMIT_PRIJEMA_MESECNO
from ..services.prijem import broj_prijema_ovog_meseca
from ..utils.ogranicenje import ogranici, ip_klijenta

ruter = APIRouter(prefix="/auth", tags=["Autentifikacija"])


def _ocisti(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


class RegistracijaUlaz(BaseModel):
    ime: str = Field(min_length=2, max_length=100)
    email: EmailStr
    lozinka: str = Field(min_length=8, max_length=72)
    naziv_kancelarije: Optional[str] = Field(default=None, max_length=200)
    telefon: Optional[str] = Field(default=None, max_length=20)

    _ocisti_polja = field_validator("ime", "naziv_kancelarije", "telefon", mode="before")(_ocisti)

    @field_validator("lozinka")
    @classmethod
    def lozinka_bajtovi(cls, v):
        # bcrypt koristi najviše 72 bajta
        if len(v.encode()) > 72:
            raise ValueError("Lozinka je predugačka")
        return v


class PrijavaUlaz(BaseModel):
    email: EmailStr
    lozinka: str = Field(max_length=200)


class TokenIzlaz(BaseModel):
    token: str
    tip: str = "bearer"
    advokat_id: int
    ime: str
    email: str


class AzuriranjeUlaz(BaseModel):
    ime: Optional[str] = Field(default=None, min_length=2, max_length=100)
    telefon: Optional[str] = Field(default=None, max_length=20)
    naziv_kancelarije: Optional[str] = Field(default=None, max_length=200)

    _ocisti_polja = field_validator("telefon", "naziv_kancelarije", mode="before")(_ocisti)


def _token_za(advokat: Advokat) -> TokenIzlaz:
    token = kreiraj_token({"sub": str(advokat.id), "email": advokat.email})
    return TokenIzlaz(token=token, advokat_id=advokat.id, ime=advokat.ime, email=advokat.email)


def _profil(db: Session, advokat: Advokat) -> dict:
    status_pretplate = osvezi_status_pretplate(db, advokat)
    return {
        "id": advokat.id,
        "ime": advokat.ime,
        "email": advokat.email,
        "naziv_kancelarije": advokat.naziv_kancelarije,
        "telefon": advokat.telefon,
        "javni_kod": advokat.javni_kod,
        "plan": advokat.plan,
        "status_pretplate": status_pretplate,
        "datum_isteka_probe": advokat.datum_isteka_probe.isoformat() if advokat.datum_isteka_probe else None,
        "datum_isteka_pretplate": advokat.datum_isteka_pretplate.isoformat() if advokat.datum_isteka_pretplate else None,
        "prijema_ovog_meseca": broj_prijema_ovog_meseca(db, advokat.id),
        "limit_prijema_mesecno": LIMIT_PRIJEMA_MESECNO.get(advokat.plan),
    }


@ruter.post("/registracija", response_model=TokenIzlaz)
def registracija(podaci: RegistracijaUlaz, request: Request, db: Session = Depends(get_db)):
    ogranici(f"registracija:{ip_klijenta(request)}", 5, 3600)
    try:
        advokat = registruj_advokata(
            db=db,
            ime=podaci.ime,
            email=podaci.email,
            lozinka=podaci.lozinka,
            naziv_kancelarije=podaci.naziv_kancelarije,
            telefon=podaci.telefon
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _token_za(advokat)


@ruter.post("/prijava", response_model=TokenIzlaz)
def prijava(podaci: PrijavaUlaz, request: Request, db: Session = Depends(get_db)):
    poruka = "Previše pokušaja prijave. Pokušajte ponovo za nekoliko minuta."
    ogranici(f"prijava-ip:{ip_klijenta(request)}", 20, 900, poruka)
    ogranici(f"prijava-email:{podaci.email.lower()}", 10, 900, poruka)

    advokat = prijavi_advokata(db=db, email=podaci.email, lozinka=podaci.lozinka)
    if not advokat:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Pogrešan email ili lozinka"
        )

    return _token_za(advokat)


@ruter.get("/ja")
def ko_sam_ja(advokat: Advokat = Depends(trenutni_advokat), db: Session = Depends(get_db)):
    return _profil(db, advokat)


@ruter.patch("/azuriraj")
def azuriraj_advokata(podaci: AzuriranjeUlaz, advokat: Advokat = Depends(trenutni_advokat), db: Session = Depends(get_db)):
    # Menjaju se samo polja koja su poslata
    for polje, vrednost in podaci.model_dump(exclude_unset=True).items():
        if polje == "ime" and not vrednost:
            continue
        setattr(advokat, polje, vrednost)
    db.commit()
    db.refresh(advokat)
    return _profil(db, advokat)
