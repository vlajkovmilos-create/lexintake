import json
import logging
import threading
import uuid
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import SessionLocal
from ..models import Advokat, Prijem, Razgovor
from .ai import OZNAKA_KRAJA, nastavi_razgovor, generisi_analizu, sistem_poruka
from .email import posalji_izvestaj_advokatu
from .placanje import LIMIT_PRIJEMA_MESECNO

settings = get_settings()
log = logging.getLogger(__name__)

ZAVRSNA_PORUKA_LIMIT = (
    "Hvala vam na odgovorima. Dostigli smo maksimalnu dužinu razgovora, pa sam prikupljene "
    "informacije prosledio advokatu koji će vas uskoro kontaktirati."
)
PORUKA_ODBIJENO = (
    "Izvinite, na to ne mogu da odgovorim. Molim vas da nastavimo sa opisom vašeg pravnog problema."
)

# Dve poruke iste sesije ne smeju da se obrađuju istovremeno (dupli klik, dva taba)
_brave = [threading.Lock() for _ in range(64)]

def brava_sesije(sesija_id: str) -> threading.Lock:
    return _brave[zlib.crc32(sesija_id.encode()) % len(_brave)]


class GreskaPrijema(Exception):
    def __init__(self, status: int, poruka: str):
        self.status = status
        self.poruka = poruka


@dataclass
class RezultatPoruke:
    odgovor: str
    zavrseno: bool
    prijem_id: Optional[int] = None


def uvodna_poruka(advokat: Advokat) -> str:
    return (
        f"Dobrodošli! Ja sam AI asistent koji u ime kancelarije {advokat.naziv_kancelarije or advokat.ime} "
        "prikuplja osnovne informacije o vašem slučaju pre konsultacije sa advokatom. "
        "Kako se zovete i koji je vaš kontakt telefon ili email?"
    )


def broj_prijema_ovog_meseca(db: Session, advokat_id: int) -> int:
    pocetak_meseca = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return db.query(Prijem).filter(
        Prijem.advokat_id == advokat_id,
        Prijem.datum_prijema >= pocetak_meseca
    ).count()


def proveri_limite_advokata(db: Session, advokat: Advokat):
    limit = LIMIT_PRIJEMA_MESECNO.get(advokat.plan)
    if limit is not None and broj_prijema_ovog_meseca(db, advokat.id) >= limit:
        raise GreskaPrijema(403, "Kancelarija je ovog meseca dostigla maksimalan broj prijema. Molimo kontaktirajte kancelariju direktno.")

    pre_24h = datetime.utcnow() - timedelta(hours=24)
    broj_danas = db.query(Razgovor).filter(
        Razgovor.advokat_id == advokat.id,
        Razgovor.datum_pocetka >= pre_24h
    ).count()
    if broj_danas >= settings.max_razgovora_po_advokatu_dnevno:
        raise GreskaPrijema(429, "Kancelarija trenutno ne može da primi nove upite. Pokušajte ponovo kasnije.")


def obrisi_stare_razgovore(db: Session):
    granica = datetime.utcnow() - timedelta(days=settings.dana_cuvanja_nedovrsenih)
    db.query(Razgovor).filter(Razgovor.zavrsen == False, Razgovor.datum_pocetka < granica).delete()  # noqa: E712
    db.commit()


def obrisi_prijem(db: Session, prijem: Prijem):
    db.query(Razgovor).filter(Razgovor.prijem_id == prijem.id).delete()
    db.delete(prijem)
    db.commit()


def zapocni_razgovor(db: Session, advokat: Advokat) -> Razgovor:
    proveri_limite_advokata(db, advokat)
    obrisi_stare_razgovore(db)
    uvodna = uvodna_poruka(advokat)
    razgovor = Razgovor(
        id=str(uuid.uuid4()),
        advokat_id=advokat.id,
        poruke_json="[]",
        uvodna_poruka=uvodna,
        sistem_poruka=sistem_poruka(
            advokat.naziv_kancelarije or advokat.ime, uvodna,
            engleski=advokat.plan in ("probni", "pro", "kancelarija")
        ),
        broj_poruka_klijenta=0,
        datum_saglasnosti=datetime.utcnow(),
    )
    db.add(razgovor)
    db.commit()
    db.refresh(razgovor)
    return razgovor


def _tekst_poruke(sadrzaj) -> str:
    if isinstance(sadrzaj, str):
        return sadrzaj
    return "\n".join(b.get("text", "") for b in sadrzaj if b.get("type") == "text")


def transkript(razgovor: Razgovor) -> list:
    """Razgovor u obliku za prikaz: [{"role": ..., "content": tekst}], uključujući pozdrav."""
    poruke = [{"role": "assistant", "content": razgovor.uvodna_poruka or ""}]
    for p in json.loads(razgovor.poruke_json or "[]"):
        tekst = _tekst_poruke(p["content"]).replace(OZNAKA_KRAJA, "").strip()
        if tekst:
            poruke.append({"role": p["role"], "content": tekst})
    return poruke


def obradi_poruku(db: Session, razgovor: Razgovor, poruka: str) -> RezultatPoruke:
    if razgovor.zavrsen:
        raise GreskaPrijema(409, "Ovaj razgovor je već završen.")

    poruke = json.loads(razgovor.poruke_json or "[]")

    # Tvrdi limit dužine razgovora - zatvaramo bez dodatnog poziva modela
    if (razgovor.broj_poruka_klijenta or 0) + 1 >= settings.max_poruka_po_razgovoru:
        poruke.append({"role": "user", "content": poruka})
        poruke.append({"role": "assistant", "content": ZAVRSNA_PORUKA_LIMIT})
        razgovor.poruke_json = json.dumps(poruke, ensure_ascii=False)
        razgovor.broj_poruka_klijenta = (razgovor.broj_poruka_klijenta or 0) + 1
        prijem_id = sacuvaj_prijem(db, razgovor)
        return RezultatPoruke(odgovor=ZAVRSNA_PORUKA_LIMIT, zavrseno=True, prijem_id=prijem_id)

    odgovor = nastavi_razgovor(razgovor.sistem_poruka, poruke + [{"role": "user", "content": poruka}])

    if odgovor.odbijeno or not odgovor.tekst:
        # Ne upisujemo ni poruku ni odgovor - istorija ostaje kakva je bila
        return RezultatPoruke(odgovor=PORUKA_ODBIJENO, zavrseno=False)

    poruke.append({"role": "user", "content": poruka})
    poruke.append({"role": "assistant", "content": odgovor.blokovi})
    razgovor.poruke_json = json.dumps(poruke, ensure_ascii=False)
    razgovor.broj_poruka_klijenta = (razgovor.broj_poruka_klijenta or 0) + 1

    prijem_id = None
    if odgovor.zavrseno:
        prijem_id = sacuvaj_prijem(db, razgovor)
    else:
        db.commit()

    return RezultatPoruke(odgovor=odgovor.tekst, zavrseno=odgovor.zavrseno, prijem_id=prijem_id)


def sacuvaj_prijem(db: Session, razgovor: Razgovor) -> int:
    """Odmah čuva prijem sa razgovorom; analiza i mejl idu u pozadini (obradi_analizu)."""
    prijem = Prijem(
        advokat_id=razgovor.advokat_id,
        razgovor_json=json.dumps(transkript(razgovor), ensure_ascii=False),
        status="novi",
        analiza_status="u_obradi",
    )
    db.add(prijem)
    db.flush()
    razgovor.zavrsen = True
    razgovor.prijem_id = prijem.id
    db.commit()
    return prijem.id


def _skrati(vrednost, duzina: int) -> Optional[str]:
    if vrednost is None:
        return None
    vrednost = str(vrednost).strip()
    return vrednost[:duzina] if vrednost else None


def obradi_analizu(prijem_id: int):
    """Pozadinski posao: AI analiza prijema, pa mejl advokatu. Otvara sopstvenu sesiju baze."""
    db = SessionLocal()
    try:
        prijem = db.query(Prijem).filter(Prijem.id == prijem_id).first()
        if not prijem:
            return

        try:
            analiza = generisi_analizu(prijem.razgovor_json)
        except Exception:
            log.exception("Analiza prijema #%s nije uspela", prijem_id)
            prijem.analiza_status = "neuspesna"
            db.commit()
            analiza = None

        if analiza is not None:
            # Dužine prate kolone - PostgreSQL odbija predugačke vrednosti
            prijem.klijent_ime = _skrati(analiza.get("klijent_ime"), 100)
            prijem.klijent_email = _skrati(analiza.get("klijent_email"), 150)
            prijem.klijent_telefon = _skrati(analiza.get("klijent_telefon"), 20)
            prijem.oblast_prava = _skrati(analiza.get("oblast_prava"), 100)
            prijem.opis_problema = _skrati(analiza.get("opis_problema"), 10000)
            prijem.detalji_slucaja = _skrati(analiza.get("detalji_slucaja"), 10000)
            prijem.dokumenti_napomena = _skrati(analiza.get("dokumenti_napomena"), 10000)
            prijem.ai_analiza = _skrati(analiza.get("ai_analiza"), 10000)
            urgentnost = analiza.get("procena_urgentnosti")
            prijem.procena_urgentnosti = urgentnost if urgentnost in ("niska", "srednja", "visoka") else None
            prijem.preporuceni_koraci = _skrati(analiza.get("preporuceni_koraci"), 10000)
            prijem.analiza_status = "gotova"
            db.commit()

        if prijem.izvestaj_poslat:
            return

        # Mejl dobijaju svi advokati kancelarije koji nisu isključili obaveštenja
        primaoci = db.query(Advokat).filter(
            or_(Advokat.id == prijem.advokat_id, Advokat.vlasnik_id == prijem.advokat_id),
            or_(Advokat.obavestenja == True, Advokat.obavestenja == None)  # noqa: E711,E712
        ).all()
        poslat = False
        for advokat in primaoci:
            poslat = posalji_izvestaj_advokatu(
                advokat_email=advokat.email,
                advokat_ime=advokat.ime,
                klijent_ime=prijem.klijent_ime or "Nepoznat",
                klijent_email=prijem.klijent_email,
                oblast_prava=prijem.oblast_prava or "Nije određena",
                opis_problema=prijem.opis_problema or "Analiza nije uspela - pogledajte transkript u kontrolnoj tabli.",
                ai_analiza=prijem.ai_analiza or "",
                procena_urgentnosti=prijem.procena_urgentnosti or "srednja",
                preporuceni_koraci=prijem.preporuceni_koraci or "",
                prijem_id=prijem.id
            ) or poslat
        if poslat:
            prijem.izvestaj_poslat = True
            db.commit()
    except Exception:
        log.exception("Neočekivana greška pri obradi prijema #%s", prijem_id)
    finally:
        db.close()
