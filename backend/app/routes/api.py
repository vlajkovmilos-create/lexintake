"""Javni REST API za kancelarije (plan Kancelarija). Autentifikacija: Authorization: Bearer lex_..."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Advokat, Prijem
from ..services.kancelarija import vlasnik_po_api_kljucu
from ..services.placanje import funkcije_plana, moze_da_prima_prijeme
from ..utils.ogranicenje import ogranici

ruter = APIRouter(prefix="/api/v1", tags=["API za kancelarije"])

_bearer = HTTPBearer(auto_error=False)


def kancelarija_iz_kljuca(
    kredencijali: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db)
) -> Advokat:
    vlasnik = vlasnik_po_api_kljucu(db, kredencijali.credentials if kredencijali else "")
    if not vlasnik:
        raise HTTPException(status_code=401, detail="Neispravan API ključ")
    if not funkcije_plana(vlasnik)["api"] or not moze_da_prima_prijeme(db, vlasnik):
        raise HTTPException(status_code=403, detail="API pristup zahteva aktivan plan Kancelarija")
    ogranici(f"api:{vlasnik.id}", 120, 60)
    return vlasnik


def _prijem_api(p: Prijem) -> dict:
    return {
        "id": p.id,
        "datum_prijema": p.datum_prijema.isoformat() + "Z",
        "status": p.status,
        "analiza_status": p.analiza_status,
        "klijent_ime": p.klijent_ime,
        "klijent_email": p.klijent_email,
        "klijent_telefon": p.klijent_telefon,
        "oblast_prava": p.oblast_prava,
        "procena_urgentnosti": p.procena_urgentnosti,
        "opis_problema": p.opis_problema,
        "detalji_slucaja": p.detalji_slucaja,
        "dokumenti_napomena": p.dokumenti_napomena,
        "ai_analiza": p.ai_analiza,
        "preporuceni_koraci": p.preporuceni_koraci,
        "dodeljen_id": p.dodeljen_id,
    }


@ruter.get("/prijemi")
def lista_prijema(
    od: Optional[datetime] = Query(default=None, description="Samo prijemi posle ovog trenutka (ISO 8601, UTC)"),
    limit: int = Query(default=50, ge=1, le=200),
    vlasnik: Advokat = Depends(kancelarija_iz_kljuca),
    db: Session = Depends(get_db)
):
    upit = db.query(Prijem).filter(Prijem.advokat_id == vlasnik.id)
    if od:
        if od.tzinfo:
            od = od.astimezone(timezone.utc).replace(tzinfo=None)
        upit = upit.filter(Prijem.datum_prijema > od)
    prijemi = upit.order_by(Prijem.datum_prijema.desc()).limit(limit).all()
    return {"prijemi": [_prijem_api(p) for p in prijemi]}


@ruter.get("/prijemi/{prijem_id}")
def jedan_prijem(prijem_id: int, vlasnik: Advokat = Depends(kancelarija_iz_kljuca), db: Session = Depends(get_db)):
    prijem = db.query(Prijem).filter(Prijem.id == prijem_id, Prijem.advokat_id == vlasnik.id).first()
    if not prijem:
        raise HTTPException(status_code=404, detail="Prijem nije pronađen")
    return _prijem_api(prijem)
