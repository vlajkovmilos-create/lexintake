import base64
import hashlib
import io
import logging
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Advokat, Pozivnica, Prijem
from .auth import hashuj_lozinku, nadji_po_emailu
from .email import posalji_pozivnicu
from .placanje import funkcije_plana, moze_da_prima_prijeme

settings = get_settings()
log = logging.getLogger(__name__)

POZIVNICA_TRAJANJE_DANA = 7
MAX_LOGO_BAJTOVA = 200 * 1024
LOGO_REGEX = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$")
BOJA_REGEX = re.compile(r"^#[0-9a-fA-F]{6}$")
API_PREFIKS = "lex_"


class GreskaKancelarije(Exception):
    def __init__(self, status: int, poruka: str):
        self.status = status
        self.poruka = poruka


def _hes(vrednost: str) -> str:
    return hashlib.sha256(vrednost.encode()).hexdigest()


# ── Tim ──

def clanovi(db: Session, vlasnik: Advokat) -> list:
    ostali = db.query(Advokat).filter(Advokat.vlasnik_id == vlasnik.id).order_by(Advokat.id).all()
    return [vlasnik] + ostali


def aktivne_pozivnice(db: Session, vlasnik: Advokat) -> list:
    return db.query(Pozivnica).filter(
        Pozivnica.vlasnik_id == vlasnik.id,
        Pozivnica.prihvacena == False,  # noqa: E712
        Pozivnica.datum_isteka > datetime.utcnow()
    ).order_by(Pozivnica.id).all()


def proveri_mesto_u_timu(db: Session, vlasnik: Advokat):
    max_advokata = funkcije_plana(vlasnik)["max_advokata"]
    if max_advokata is None:
        return
    zauzeto = len(clanovi(db, vlasnik)) + len(aktivne_pozivnice(db, vlasnik))
    if zauzeto >= max_advokata:
        if max_advokata == 1:
            raise GreskaKancelarije(403, "Vaš plan ne uključuje više advokata. Pređite na Pro ili Kancelarija plan.")
        raise GreskaKancelarije(403, f"Vaš plan uključuje najviše {max_advokata} advokata (računajući i poslate pozivnice).")


def posalji_poziv(db: Session, vlasnik: Advokat, email: str) -> Pozivnica:
    email = email.strip().lower()
    if nadji_po_emailu(db, email):
        raise GreskaKancelarije(400, "Nalog sa ovim emailom već postoji. Kolega treba da koristi drugu adresu.")
    if any(p.email == email for p in aktivne_pozivnice(db, vlasnik)):
        raise GreskaKancelarije(400, "Pozivnica za ovaj email je već poslata.")
    proveri_mesto_u_timu(db, vlasnik)

    token = secrets.token_urlsafe(32)
    pozivnica = Pozivnica(
        vlasnik_id=vlasnik.id,
        email=email,
        token_hash=_hes(token),
        datum_isteka=datetime.utcnow() + timedelta(days=POZIVNICA_TRAJANJE_DANA),
    )
    db.add(pozivnica)
    db.commit()
    db.refresh(pozivnica)

    link = f"{settings.frontend_url.rstrip('/')}/pages/pozivnica.html?t={token}"
    if not posalji_pozivnicu(email, vlasnik.naziv_kancelarije or vlasnik.ime, vlasnik.ime, link):
        log.warning("Pozivnica #%s nije poslata mejlom", pozivnica.id)
    return pozivnica


def nadji_pozivnicu(db: Session, token: str) -> Optional[Pozivnica]:
    pozivnica = db.query(Pozivnica).filter(Pozivnica.token_hash == _hes(token)).first()
    if not pozivnica or pozivnica.prihvacena or pozivnica.datum_isteka <= datetime.utcnow():
        return None
    return pozivnica


def prihvati_poziv(db: Session, token: str, ime: str, lozinka: str) -> Advokat:
    pozivnica = nadji_pozivnicu(db, token)
    if not pozivnica:
        raise GreskaKancelarije(404, "Pozivnica nije ispravna ili je istekla.")
    if nadji_po_emailu(db, pozivnica.email):
        raise GreskaKancelarije(400, "Nalog sa ovim emailom već postoji.")

    clan = Advokat(
        ime=ime,
        email=pozivnica.email,
        lozinka_hash=hashuj_lozinku(lozinka),
        vlasnik_id=pozivnica.vlasnik_id,
    )
    pozivnica.prihvacena = True
    db.add(clan)
    db.commit()
    db.refresh(clan)
    return clan


def ukloni_clana(db: Session, vlasnik: Advokat, clan_id: int):
    clan = db.query(Advokat).filter(Advokat.id == clan_id, Advokat.vlasnik_id == vlasnik.id).first()
    if not clan:
        raise GreskaKancelarije(404, "Član tima nije pronađen.")
    db.query(Prijem).filter(Prijem.dodeljen_id == clan.id).update({Prijem.dodeljen_id: None})
    db.delete(clan)
    db.commit()


def otkazi_poziv(db: Session, vlasnik: Advokat, pozivnica_id: int):
    pozivnica = db.query(Pozivnica).filter(Pozivnica.id == pozivnica_id, Pozivnica.vlasnik_id == vlasnik.id).first()
    if not pozivnica:
        raise GreskaKancelarije(404, "Pozivnica nije pronađena.")
    db.delete(pozivnica)
    db.commit()


# ── White-label ──

def ima_white_label(db: Session, vlasnik: Advokat) -> bool:
    return funkcije_plana(vlasnik)["white_label"] and moze_da_prima_prijeme(db, vlasnik)


def brending(db: Session, vlasnik: Advokat) -> dict:
    """Brending za upitnik i PDF; prazan ako plan ne uključuje white-label."""
    if not ima_white_label(db, vlasnik):
        return {"logo": None, "boja": None, "bez_lexintake": False}
    return {"logo": vlasnik.logo, "boja": vlasnik.boja, "bez_lexintake": True}


def logo_bajtovi(logo: Optional[str]) -> Optional[bytes]:
    if not logo:
        return None
    pogodak = LOGO_REGEX.match(logo)
    if not pogodak:
        return None
    try:
        return base64.b64decode(pogodak.group(2), validate=True)
    except ValueError:
        return None


def sacuvaj_brending(db: Session, vlasnik: Advokat, logo: Optional[str], boja: Optional[str]):
    if not funkcije_plana(vlasnik)["white_label"]:
        raise GreskaKancelarije(403, "Sopstveni brending je deo plana Kancelarija.")

    if boja and not BOJA_REGEX.match(boja):
        raise GreskaKancelarije(400, "Boja mora biti u formatu #RRGGBB.")

    if logo:
        bajtovi = logo_bajtovi(logo)
        if bajtovi is None:
            raise GreskaKancelarije(400, "Logo mora biti PNG, JPEG ili WebP slika.")
        if len(bajtovi) > MAX_LOGO_BAJTOVA:
            raise GreskaKancelarije(400, "Logo je prevelik (najviše 200 KB).")
        try:
            from PIL import Image
            with Image.open(io.BytesIO(bajtovi)) as slika:
                slika.verify()
        except Exception:
            raise GreskaKancelarije(400, "Fajl nije ispravna slika.")

    vlasnik.logo = logo or None
    vlasnik.boja = boja.lower() if boja else None
    db.commit()


# ── API ključ ──

def napravi_api_kljuc(db: Session, vlasnik: Advokat) -> str:
    if not funkcije_plana(vlasnik)["api"]:
        raise GreskaKancelarije(403, "API pristup je deo plana Kancelarija.")
    kljuc = API_PREFIKS + secrets.token_urlsafe(32)
    vlasnik.api_kljuc_hash = _hes(kljuc)
    vlasnik.api_kljuc_prefiks = kljuc[:10]
    vlasnik.api_kljuc_datum = datetime.utcnow()
    db.commit()
    return kljuc


def obrisi_api_kljuc(db: Session, vlasnik: Advokat):
    vlasnik.api_kljuc_hash = None
    vlasnik.api_kljuc_prefiks = None
    vlasnik.api_kljuc_datum = None
    db.commit()


def vlasnik_po_api_kljucu(db: Session, kljuc: str) -> Optional[Advokat]:
    if not kljuc or not kljuc.startswith(API_PREFIKS):
        return None
    return db.query(Advokat).filter(Advokat.api_kljuc_hash == _hes(kljuc), Advokat.vlasnik_id == None).first()  # noqa: E711
