from fastapi.responses import Response
from ..services.pdf import generisi_pdf
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from ..models import Prijem, Advokat
from ..services.ai import nastavi_razgovor, generisi_analizu
from ..services.email import posalji_izvestaj_advokatu

ruter = APIRouter(prefix="/prijem", tags=["Prijem klijenta"])

class PorukaUlaz(BaseModel):
    advokat_id: int
    sesija_id: Optional[str] = None
    poruka: str
    istorija: list = []

class PorukaIzlaz(BaseModel):
    odgovor: str
    sesija_id: str
    istorija: list
    zavrseno: bool
    prijem_id: Optional[int] = None

class StatusAzuriranje(BaseModel):
    status: str

@ruter.post("/poruka", response_model=PorukaIzlaz)
def posalji_poruku(podaci: PorukaUlaz, db: Session = Depends(get_db)):
    advokat = db.query(Advokat).filter(Advokat.id == podaci.advokat_id).first()
    if not advokat:
        raise HTTPException(status_code=404, detail="Advokat nije pronađen")

    dozvoljeni_statusi = ["probni_period", "aktivna"]
    if advokat.status_pretplate not in dozvoljeni_statusi:
        raise HTTPException(
            status_code=403,
            detail="Ova advokatska kancelarija trenutno ne prima nove prijeme. Molimo pokušajte kasnije ili kontaktirajte kancelariju direktno."
        )

    istorija = podaci.istorija
    if not istorija:
        uvodna = (
            f"Dobrodošli u advokatsku kancelariju {advokat.naziv_kancelarije or advokat.ime}. "
            "Ja sam AI asistent koji će prikupiti osnovne informacije o vašem slučaju pre konsultacije sa advokatom. "
            "Sve što navedete je poverljivo. Kako se zovete i koji je vaš kontakt telefon ili email?"
        )
        istorija = [{"role": "assistant", "content": uvodna}]
        return PorukaIzlaz(
            odgovor=uvodna,
            sesija_id=podaci.sesija_id or _generisi_sesiju(),
            istorija=istorija,
            zavrseno=False
        )

    odgovor = nastavi_razgovor(istorija, podaci.poruka)

    nova_istorija = istorija + [
        {"role": "user", "content": podaci.poruka},
        {"role": "assistant", "content": odgovor}
    ]

    zavrseno = "RAZGOVOR_ZAVRŠEN:" in odgovor
    prijem_id = None

    if zavrseno:
        prijem_id = _sacuvaj_prijem(
            db=db,
            advokat_id=podaci.advokat_id,
            istorija_json=json.dumps(nova_istorija, ensure_ascii=False)
        )

    return PorukaIzlaz(
        odgovor=odgovor,
        sesija_id=podaci.sesija_id or _generisi_sesiju(),
        istorija=nova_istorija,
        zavrseno=zavrseno,
        prijem_id=prijem_id
    )

@ruter.get("/lista/{advokat_id}")
def lista_prijema(advokat_id: int, db: Session = Depends(get_db)):
    prijemi = db.query(Prijem).filter(
        Prijem.advokat_id == advokat_id
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
            "datum_prijema": p.datum_prijema.isoformat()
        }
        for p in prijemi
    ]

@ruter.get("/detalji/{prijem_id}")
def detalji_prijema(prijem_id: int, db: Session = Depends(get_db)):
    prijem = db.query(Prijem).filter(Prijem.id == prijem_id).first()
    if not prijem:
        raise HTTPException(status_code=404, detail="Prijem nije pronađen")

    return {
        "id": prijem.id,
        "advokat_id": prijem.advokat_id,
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
        "status": prijem.status,
        "datum_prijema": prijem.datum_prijema.isoformat()
    }

@ruter.patch("/status/{prijem_id}")
def azuriraj_status(prijem_id: int, podaci: StatusAzuriranje, db: Session = Depends(get_db)):
    dozvoljeni_statusi = ["novi", "na_pregledu", "zakazano", "zatvoreno"]
    if podaci.status not in dozvoljeni_statusi:
        raise HTTPException(status_code=400, detail=f"Dozvoljeni statusi: {dozvoljeni_statusi}")

    prijem = db.query(Prijem).filter(Prijem.id == prijem_id).first()
    if not prijem:
        raise HTTPException(status_code=404, detail="Prijem nije pronađen")

    prijem.status = podaci.status
    db.commit()
    return {"poruka": "Status uspešno ažuriran", "status": podaci.status}


def _generisi_sesiju() -> str:
    import uuid
    return str(uuid.uuid4())

def _sacuvaj_prijem(db: Session, advokat_id: int, istorija_json: str) -> int:
    try:
        analiza = generisi_analizu(istorija_json)
    except Exception:
        analiza = {}

    prijem = Prijem(
        advokat_id=advokat_id,
        klijent_ime=analiza.get("klijent_ime"),
        klijent_email=analiza.get("klijent_email"),
        klijent_telefon=analiza.get("klijent_telefon"),
        oblast_prava=analiza.get("oblast_prava"),
        opis_problema=analiza.get("opis_problema"),
        detalji_slucaja=analiza.get("detalji_slucaja"),
        dokumenti_napomena=analiza.get("dokumenti_napomena"),
        ai_analiza=analiza.get("ai_analiza"),
        procena_urgentnosti=analiza.get("procena_urgentnosti"),
        preporuceni_koraci=analiza.get("preporuceni_koraci"),
        razgovor_json=istorija_json,
        status="novi"
    )
    db.add(prijem)
    db.commit()
    db.refresh(prijem)
    try:
        advokat = db.query(Advokat).filter(Advokat.id == advokat_id).first()
        if advokat:
            posalji_izvestaj_advokatu(
                advokat_email=advokat.email,
                advokat_ime=advokat.ime,
                klijent_ime=analiza.get("klijent_ime", "Nepoznat"),
                oblast_prava=analiza.get("oblast_prava", "Nije određena"),
                opis_problema=analiza.get("opis_problema", ""),
                ai_analiza=analiza.get("ai_analiza", ""),
                procena_urgentnosti=analiza.get("procena_urgentnosti", "srednja"),
                preporuceni_koraci=analiza.get("preporuceni_koraci", ""),
                prijem_id=prijem.id
            )
    except Exception as e:
        print(f"Email nije poslat: {e}")
    return prijem.id

@ruter.get("/pdf/{prijem_id}")
def preuzmi_pdf(prijem_id: int, db: Session = Depends(get_db)):
    prijem = db.query(Prijem).filter(Prijem.id == prijem_id).first()
    if not prijem:
        raise HTTPException(status_code=404, detail="Prijem nije pronađen")

    advokat = db.query(Advokat).filter(Advokat.id == prijem.advokat_id).first()

    pdf = generisi_pdf(prijem, advokat)

    ime_fajla = f"prijem_{prijem_id}_{prijem.klijent_ime or 'klijent'}.pdf".replace(" ", "_")

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={ime_fajla}"}
    )