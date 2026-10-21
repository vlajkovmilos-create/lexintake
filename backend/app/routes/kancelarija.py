from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Advokat
from ..services.auth import trenutni_advokat, vlasnik_kancelarije, kreiraj_token
from ..services import kancelarija as servis
from ..utils.ogranicenje import ogranici, ip_klijenta
from .auth import TokenIzlaz, RegistracijaUlaz

ruter = APIRouter(prefix="/kancelarija", tags=["Kancelarija"])


class PozivnicaUlaz(BaseModel):
    email: EmailStr

class PrihvatanjeUlaz(BaseModel):
    token: str = Field(min_length=20, max_length=100)
    ime: str = Field(min_length=2, max_length=100)
    lozinka: str = RegistracijaUlaz.model_fields["lozinka"]

class BrendingUlaz(BaseModel):
    logo: Optional[str] = Field(default=None, max_length=400_000)
    boja: Optional[str] = Field(default=None, max_length=7)


def samo_vlasnik(advokat: Advokat = Depends(trenutni_advokat)) -> Advokat:
    if not advokat.je_vlasnik:
        raise HTTPException(status_code=403, detail="Ovo može da menja samo vlasnik naloga kancelarije.")
    return advokat


def _izvrsi(funkcija, *args):
    try:
        return funkcija(*args)
    except servis.GreskaKancelarije as g:
        raise HTTPException(status_code=g.status, detail=g.poruka)


# ── Tim ──

@ruter.get("/tim")
def tim(advokat: Advokat = Depends(trenutni_advokat), db: Session = Depends(get_db)):
    vlasnik = vlasnik_kancelarije(db, advokat)
    return {
        "clanovi": [
            {"id": a.id, "ime": a.ime, "email": a.email, "je_vlasnik": a.je_vlasnik}
            for a in servis.clanovi(db, vlasnik)
        ],
        "pozivnice": [
            {"id": p.id, "email": p.email, "datum_isteka": p.datum_isteka.isoformat()}
            for p in servis.aktivne_pozivnice(db, vlasnik)
        ] if advokat.je_vlasnik else [],
    }


@ruter.post("/pozivnica")
def posalji_pozivnicu(podaci: PozivnicaUlaz, vlasnik: Advokat = Depends(samo_vlasnik), db: Session = Depends(get_db)):
    ogranici(f"pozivnica:{vlasnik.id}", 20, 86400)
    pozivnica = _izvrsi(servis.posalji_poziv, db, vlasnik, podaci.email)
    return {"poruka": f"Pozivnica je poslata na {pozivnica.email}", "id": pozivnica.id}


@ruter.delete("/pozivnica/{pozivnica_id}")
def otkazi_pozivnicu(pozivnica_id: int, vlasnik: Advokat = Depends(samo_vlasnik), db: Session = Depends(get_db)):
    _izvrsi(servis.otkazi_poziv, db, vlasnik, pozivnica_id)
    return {"poruka": "Pozivnica je otkazana"}


@ruter.delete("/clan/{clan_id}")
def ukloni_clana(clan_id: int, vlasnik: Advokat = Depends(samo_vlasnik), db: Session = Depends(get_db)):
    _izvrsi(servis.ukloni_clana, db, vlasnik, clan_id)
    return {"poruka": "Član tima je uklonjen"}


@ruter.get("/pozivnica/{token}")
def info_pozivnice(token: str, request: Request, db: Session = Depends(get_db)):
    ogranici(f"pozivnica-info:{ip_klijenta(request)}", 30, 3600)
    pozivnica = servis.nadji_pozivnicu(db, token)
    if not pozivnica:
        raise HTTPException(status_code=404, detail="Pozivnica nije ispravna ili je istekla.")
    vlasnik = db.query(Advokat).filter(Advokat.id == pozivnica.vlasnik_id).first()
    return {"email": pozivnica.email, "naziv_kancelarije": vlasnik.naziv_kancelarije or vlasnik.ime}


@ruter.post("/pozivnica/prihvati", response_model=TokenIzlaz)
def prihvati_pozivnicu(podaci: PrihvatanjeUlaz, request: Request, db: Session = Depends(get_db)):
    ogranici(f"pozivnica-prihvati:{ip_klijenta(request)}", 10, 3600)
    clan = _izvrsi(servis.prihvati_poziv, db, podaci.token, podaci.ime.strip(), podaci.lozinka)
    token = kreiraj_token({"sub": str(clan.id), "email": clan.email})
    return TokenIzlaz(token=token, advokat_id=clan.id, ime=clan.ime, email=clan.email)


# ── White-label ──

@ruter.put("/brending")
def sacuvaj_brending(podaci: BrendingUlaz, vlasnik: Advokat = Depends(samo_vlasnik), db: Session = Depends(get_db)):
    _izvrsi(servis.sacuvaj_brending, db, vlasnik, podaci.logo, podaci.boja)
    return {"poruka": "Brending je sačuvan", "logo": vlasnik.logo, "boja": vlasnik.boja}


# ── API ključ ──

@ruter.post("/api-kljuc")
def napravi_api_kljuc(vlasnik: Advokat = Depends(samo_vlasnik), db: Session = Depends(get_db)):
    kljuc = _izvrsi(servis.napravi_api_kljuc, db, vlasnik)
    return {"api_kljuc": kljuc, "poruka": "Sačuvajte ključ - neće biti ponovo prikazan."}


@ruter.delete("/api-kljuc")
def obrisi_api_kljuc(vlasnik: Advokat = Depends(samo_vlasnik), db: Session = Depends(get_db)):
    servis.obrisi_api_kljuc(db, vlasnik)
    return {"poruka": "API ključ je opozvan"}
