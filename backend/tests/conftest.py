import os
import tempfile

# Podešavanja moraju da postoje pre uvoza aplikacije (servisi ih čitaju pri uvozu)
_baza = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_baza}",
    "ANTHROPIC_API_KEY": "test",
    "RESEND_API_KEY": "test",
    "SECRET_KEY": "test-tajni-kljuc-koji-je-dovoljno-dugacak",
    "LEMONSQUEEZY_WEBHOOK_SECRET": "webhook-tajna",
    "MAX_PORUKA_PO_RAZGOVORU": "6",
})

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, engine
from app.services import prijem as servis_prijema
from app.services.ai import OdgovorAsistenta
from app.utils import ogranicenje


@pytest.fixture(autouse=True)
def cista_baza():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    ogranicenje.resetuj()
    yield


@pytest.fixture
def klijent():
    return TestClient(app)


@pytest.fixture
def lazni_ai(monkeypatch):
    """Zamenjuje Claude i Resend lažnim funkcijama i beleži pozive."""
    pozivi = {"razgovor": [], "analiza": 0, "mejl": []}
    odgovori = []

    def nastavi(sistem, poruke):
        pozivi["razgovor"].append(poruke)
        tekst = odgovori.pop(0) if odgovori else "Sledeće pitanje?"
        if tekst is None:
            return OdgovorAsistenta(tekst="", odbijeno=True)
        zavrseno = "RAZGOVOR_ZAVRŠEN:" in tekst
        prikaz = tekst.replace("RAZGOVOR_ZAVRŠEN:", "").strip()
        return OdgovorAsistenta(tekst=prikaz, blokovi=[{"type": "text", "text": tekst}], zavrseno=zavrseno)

    def analiza(transkript_json):
        pozivi["analiza"] += 1
        return {
            "klijent_ime": "Marko Petrović", "klijent_email": "marko@example.com",
            "klijent_telefon": "+381 64 123 4567 ili 011 222 3333 posle 17h",
            "oblast_prava": "Radno pravo", "opis_problema": "Otkaz bez rešenja.",
            "detalji_slucaja": "Gradnja d.o.o.", "dokumenti_napomena": "Ugovor o radu",
            "ai_analiza": "Analiza <b>test</b> & više", "procena_urgentnosti": "visoka",
            "preporuceni_koraci": "- korak 1\n- korak 2",
        }

    def mejl(**kwargs):
        pozivi["mejl"].append(kwargs)
        return True

    monkeypatch.setattr(servis_prijema, "nastavi_razgovor", nastavi)
    monkeypatch.setattr(servis_prijema, "generisi_analizu", analiza)
    monkeypatch.setattr(servis_prijema, "posalji_izvestaj_advokatu", mejl)
    pozivi["odgovori"] = odgovori
    return pozivi


def registruj(klijent, email="a@example.com", **dodatno):
    podaci = {"ime": "Advokat A", "email": email, "lozinka": "lozinka123", "naziv_kancelarije": "Kancelarija A"}
    podaci.update(dodatno)
    odg = klijent.post("/auth/registracija", json=podaci)
    assert odg.status_code == 200, odg.text
    token = odg.json()["token"]
    zaglavlje = {"Authorization": f"Bearer {token}"}
    profil = klijent.get("/auth/ja", headers=zaglavlje).json()
    return zaglavlje, profil
