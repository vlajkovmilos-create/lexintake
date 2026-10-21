import json
import re
import unicodedata
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import Prijem, Advokat, Razgovor
from ..services.auth import trenutni_advokat
from ..services.pdf import generisi_pdf
from ..services.placanje import moze_da_prima_prijeme
from ..services import prijem as servis
from ..utils.ogranicenje import ogranici, ip_klijenta

settings = get_settings()

ruter = APIRouter(prefix="/prijem", tags=["Prijem klijenta"])

PORUKA_NE_PRIMA = "Ova advokatska kancelarija trenutno ne prima nove prijeme. Molimo pokušajte kasnije ili kontaktirajte kancelariju direktno."
DOZVOLJENI_STATUSI = ["novi", "na_pregledu", "zakazano", "zatvoreno"]


class PocetakUlaz(BaseModel):
    kod: str = Field(min_length=4, max_length=32)
    saglasnost: bool

class PocetakIzlaz(BaseModel):
    sesija_id: str
    odgovor: str
    naziv_kancelarije: str

class PorukaUlaz(BaseModel):
    sesija_id: str = Field(min_length=36, max_length=36)
    poruka: str = Field(min_length=1, max_length=2000)

class PorukaIzlaz(BaseModel):
    odgovor: str
    sesija_id: str
    zavrseno: bool
    prijem_id: Optional[int] = None

class StatusAzuriranje(BaseModel):
    status: str


def _naziv(advokat: Advokat) -> str:
    return advokat.naziv_kancelarije or advokat.ime


# ── Javne rute (klijent) ──

@ruter.get("/kancelarija/{kod}")
def info_kancelarije(kod: str, db: Session = Depends(get_db)):
    advokat = db.query(Advokat).filter(Advokat.javni_kod == kod).first()
    if not advokat:
        raise HTTPException(status_code=404, detail="Link upitnika nije ispravan.")
    return {"naziv_kancelarije": _naziv(advokat), "prima_prijeme": moze_da_prima_prijeme(db, advokat)}


@ruter.post("/razgovor", response_model=PocetakIzlaz)
def zapocni_razgovor(podaci: PocetakUlaz, request: Request, db: Session = Depends(get_db)):
    if not podaci.saglasnost:
        raise HTTPException(status_code=400, detail="Za nastavak je potrebna saglasnost za obradu podataka.")

    advokat = db.query(Advokat).filter(Advokat.javni_kod == podaci.kod).first()
    if not advokat:
        raise HTTPException(status_code=404, detail="Link upitnika nije ispravan.")
    if not moze_da_prima_prijeme(db, advokat):
        raise HTTPException(status_code=403, detail=PORUKA_NE_PRIMA)

    ogranici(f"razgovor:{ip_klijenta(request)}", settings.max_razgovora_po_ip_na_sat, 3600)

    try:
        razgovor = servis.zapocni_razgovor(db, advokat)
    except servis.GreskaPrijema as g:
        raise HTTPException(status_code=g.status, detail=g.poruka)

    return PocetakIzlaz(sesija_id=razgovor.id, odgovor=razgovor.uvodna_poruka, naziv_kancelarije=_naziv(advokat))


@ruter.get("/razgovor/{sesija_id}")
def vrati_razgovor(sesija_id: str, db: Session = Depends(get_db)):
    """Vraća razgovor za prikaz, npr. posle osvežavanja stranice."""
    razgovor = db.query(Razgovor).filter(Razgovor.id == sesija_id).first()
    if not razgovor:
        raise HTTPException(status_code=404, detail="Razgovor nije pronađen.")
    advokat = db.query(Advokat).filter(Advokat.id == razgovor.advokat_id).first()
    return {
        "sesija_id": razgovor.id,
        "naziv_kancelarije": _naziv(advokat) if advokat else "",
        "zavrseno": bool(razgovor.zavrsen),
        "poruke": servis.transkript(razgovor),
    }


@ruter.post("/poruka", response_model=PorukaIzlaz)
def posalji_poruku(podaci: PorukaUlaz, request: Request, pozadina: BackgroundTasks, db: Session = Depends(get_db)):
    ogranici(f"poruka:{ip_klijenta(request)}", settings.max_poruka_po_ip_u_minutu, 60)

    brava = servis.brava_sesije(podaci.sesija_id)
    if not brava.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Prethodna poruka se još obrađuje.")
    try:
        razgovor = db.query(Razgovor).filter(Razgovor.id == podaci.sesija_id).first()
        if not razgovor:
            raise HTTPException(status_code=404, detail="Razgovor nije pronađen. Osvežite stranicu i počnite ponovo.")

        advokat = db.query(Advokat).filter(Advokat.id == razgovor.advokat_id).first()
        if not advokat or not moze_da_prima_prijeme(db, advokat):
            raise HTTPException(status_code=403, detail=PORUKA_NE_PRIMA)

        try:
            rezultat = servis.obradi_poruku(db, razgovor, podaci.poruka.strip())
        except servis.GreskaPrijema as g:
            raise HTTPException(status_code=g.status, detail=g.poruka)
    finally:
        brava.release()

    if rezultat.prijem_id:
        pozadina.add_task(servis.obradi_analizu, rezultat.prijem_id)

    return PorukaIzlaz(
        odgovor=rezultat.odgovor,
        sesija_id=podaci.sesija_id,
        zavrseno=rezultat.zavrseno,
        prijem_id=rezultat.prijem_id
    )


# ── Rute advokata (zahtevaju prijavu) ──

def _prijem_advokata(db: Session, prijem_id: int, advokat: Advokat) -> Prijem:
    prijem = db.query(Prijem).filter(Prijem.id == prijem_id, Prijem.advokat_id == advokat.id).first()
    if not prijem:
        raise HTTPException(status_code=404, detail="Prijem nije pronađen")
    return prijem


@ruter.get("/lista")
def lista_prijema(advokat: Advokat = Depends(trenutni_advokat), db: Session = Depends(get_db)):
    prijemi = db.query(Prijem).filter(
        Prijem.advokat_id == advokat.id
    ).order_by(Prijem.datum_prijema.desc()).all()

    return [
        {
            "id": p.id,
            "klijent_ime": p.klijent_ime or "Nepoznat",
            "klijent_email": p.klijent_email,
            "klijent_telefon": p.klijent_telefon,
            "oblast_prava": p.oblast_prava,
            "status": p.status,
            "procena_urgentnosti": p.procena_urgentnosti,
            "analiza_status": p.analiza_status,
            "datum_prijema": p.datum_prijema.isoformat()
        }
        for p in prijemi
    ]


@ruter.get("/detalji/{prijem_id}")
def detalji_prijema(prijem_id: int, advokat: Advokat = Depends(trenutni_advokat), db: Session = Depends(get_db)):
    prijem = _prijem_advokata(db, prijem_id, advokat)
    try:
        razgovor = json.loads(prijem.razgovor_json or "[]")
    except json.JSONDecodeError:
        razgovor = []

    return {
        "id": prijem.id,
        "klijent_ime": prijem.klijent_ime,
        "klijent_email": prijem.klijent_email,
        "klijent_telefon": prijem.klijent_telefon,
        "oblast_prava": prijem.oblast_prava,
        "opis_problema": prijem.opis_problema,
        "detalji_slucaja": prijem.detalji_slucaja,
        "dokumenti_napomena": prijem.dokumenti_napomena,
        "ai_analiza": prijem.ai_analiza,
        "procena_urgentnosti": prijem.procena_urgentnosti,
        "preporuceni_koraci": prijem.preporuceni_koraci,
        "analiza_status": prijem.analiza_status,
        "status": prijem.status,
        "datum_prijema": prijem.datum_prijema.isoformat(),
        "razgovor": [
            {"role": p.get("role"), "content": p.get("content")}
            for p in razgovor if isinstance(p.get("content"), str)
        ],
    }


@ruter.patch("/status/{prijem_id}")
def azuriraj_status(prijem_id: int, podaci: StatusAzuriranje, advokat: Advokat = Depends(trenutni_advokat), db: Session = Depends(get_db)):
    if podaci.status not in DOZVOLJENI_STATUSI:
        raise HTTPException(status_code=400, detail=f"Dozvoljeni statusi: {', '.join(DOZVOLJENI_STATUSI)}")

    prijem = _prijem_advokata(db, prijem_id, advokat)
    prijem.status = podaci.status
    db.commit()
    return {"poruka": "Status uspešno ažuriran", "status": podaci.status}


@ruter.delete("/{prijem_id}")
def obrisi_prijem(prijem_id: int, advokat: Advokat = Depends(trenutni_advokat), db: Session = Depends(get_db)):
    prijem = _prijem_advokata(db, prijem_id, advokat)
    servis.obrisi_prijem(db, prijem)
    return {"poruka": "Prijem je obrisan"}


@ruter.post("/analiza/{prijem_id}")
def ponovi_analizu(prijem_id: int, pozadina: BackgroundTasks, advokat: Advokat = Depends(trenutni_advokat), db: Session = Depends(get_db)):
    prijem = _prijem_advokata(db, prijem_id, advokat)
    if prijem.analiza_status == "u_obradi":
        raise HTTPException(status_code=409, detail="Analiza je već u toku.")
    ogranici(f"analiza:{advokat.id}", 10, 3600)
    prijem.analiza_status = "u_obradi"
    db.commit()
    pozadina.add_task(servis.obradi_analizu, prijem.id)
    return {"poruka": "Analiza je pokrenuta", "analiza_status": "u_obradi"}


def _ocisti_ime_fajla(tekst: str) -> str:
    tekst = unicodedata.normalize('NFKD', tekst)
    tekst = tekst.encode('ascii', 'ignore').decode('ascii')
    tekst = re.sub(r'[^\w\s-]', '', tekst)
    return tekst.replace(' ', '_')


@ruter.get("/pdf/{prijem_id}")
def preuzmi_pdf(prijem_id: int, advokat: Advokat = Depends(trenutni_advokat), db: Session = Depends(get_db)):
    prijem = _prijem_advokata(db, prijem_id, advokat)

    pdf = generisi_pdf(prijem, advokat)

    ime_fajla = f"prijem_{prijem_id}_{_ocisti_ime_fajla(prijem.klijent_ime or 'klijent')}.pdf"

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{ime_fajla}"'}
    )
