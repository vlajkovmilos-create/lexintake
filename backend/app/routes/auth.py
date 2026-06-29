from fastapi import Header
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from ..database import get_db
from ..services.auth import registruj_advokata, prijavi_advokata, kreiraj_token
from fastapi import Header
from ..services.auth import dekoduj_token
from ..models import Advokat

ruter = APIRouter(prefix="/auth", tags=["Autentifikacija"])

class RegistracijaUlaz(BaseModel):
    ime: str
    email: EmailStr
    lozinka: str
    naziv_kancelarije: str = None
    telefon: str = None

class PrijavaUlaz(BaseModel):
    email: EmailStr
    lozinka: str

class TokenIzlaz(BaseModel):
    token: str
    tip: str = "bearer"
    ime: str
    email: str

@ruter.post("/registracija", response_model=TokenIzlaz)
def registracija(podaci: RegistracijaUlaz, db: Session = Depends(get_db)):
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

    token = kreiraj_token({"sub": str(advokat.id), "email": advokat.email})
    return TokenIzlaz(token=token, ime=advokat.ime, email=advokat.email)

@ruter.post("/prijava", response_model=TokenIzlaz)
def prijava(podaci: PrijavaUlaz, db: Session = Depends(get_db)):
    advokat = prijavi_advokata(db=db, email=podaci.email, lozinka=podaci.lozinka)
    if not advokat:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Pogrešan email ili lozinka"
        )

    token = kreiraj_token({"sub": str(advokat.id), "email": advokat.email})
    return TokenIzlaz(token=token, ime=advokat.ime, email=advokat.email)


@ruter.get("/ja")
def ko_sam_ja(authorization: str = Header(...), db: Session = Depends(get_db)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Neispravan token format")
    
    token = authorization.split(" ")[1]
    podaci = dekoduj_token(token)
    
    if not podaci:
        raise HTTPException(status_code=401, detail="Neispravan ili istekao token")
    
    advokat = db.query(Advokat).filter(Advokat.id == int(podaci["sub"])).first()
    if not advokat:
        raise HTTPException(status_code=404, detail="Advokat nije pronađen")
    
    return {
        "id": advokat.id,
        "ime": advokat.ime,
        "email": advokat.email,
        "naziv_kancelarije": advokat.naziv_kancelarije,
        "telefon": advokat.telefon
    }

class AzuriranjeUlaz(BaseModel):
    ime: str = None
    telefon: str = None
    naziv_kancelarije: str = None

@ruter.patch("/azuriraj/{advokat_id}")
def azuriraj_advokata(advokat_id: int, podaci: AzuriranjeUlaz, db: Session = Depends(get_db)):
    advokat = db.query(Advokat).filter(Advokat.id == advokat_id).first()
    if not advokat:
        raise HTTPException(status_code=404, detail="Advokat nije pronađen")

    if podaci.ime:
        advokat.ime = podaci.ime
    advokat.telefon = podaci.telefon
    advokat.naziv_kancelarije = podaci.naziv_kancelarije
    db.commit()
    db.refresh(advokat)

    return {
        "id": advokat.id,
        "ime": advokat.ime,
        "email": advokat.email,
        "naziv_kancelarije": advokat.naziv_kancelarije,
        "telefon": advokat.telefon
    }