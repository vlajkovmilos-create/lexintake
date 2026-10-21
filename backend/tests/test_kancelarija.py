import base64
import io
import re

from PIL import Image

from app.database import SessionLocal
from app.models import Advokat
from app.services import kancelarija as servis_kancelarije
from tests.conftest import registruj


def postavi_plan(advokat_id, plan, status="aktivna"):
    db = SessionLocal()
    advokat = db.get(Advokat, advokat_id)
    advokat.plan = plan
    advokat.status_pretplate = status
    db.commit()
    db.close()


def pozovi(klijent, zaglavlje, email, monkeypatch):
    linkovi = []
    monkeypatch.setattr(servis_kancelarije, "posalji_pozivnicu", lambda email, naziv, ime, link: linkovi.append(link) or True)
    odg = klijent.post("/kancelarija/pozivnica", json={"email": email}, headers=zaglavlje)
    return odg, (re.search(r"t=([\w-]+)", linkovi[0]).group(1) if linkovi else None)


def prihvati(klijent, token, ime="Kolega"):
    odg = klijent.post("/kancelarija/pozivnica/prihvati", json={"token": token, "ime": ime, "lozinka": "lozinka123"})
    assert odg.status_code == 200, odg.text
    return {"Authorization": f"Bearer {odg.json()['token']}"}


def test_pozivnica_i_zajednicki_prijemi(klijent, lazni_ai, monkeypatch):
    zaglavlje_v, profil_v = registruj(klijent)
    odg, token = pozovi(klijent, zaglavlje_v, "Kolega@Example.com", monkeypatch)
    assert odg.status_code == 200

    info = klijent.get(f"/kancelarija/pozivnica/{token}").json()
    assert info == {"email": "kolega@example.com", "naziv_kancelarije": "Kancelarija A"}
    zaglavlje_c = prihvati(klijent, token)
    assert klijent.get(f"/kancelarija/pozivnica/{token}").status_code == 404  # jednokratna

    ja = klijent.get("/auth/ja", headers=zaglavlje_c).json()
    assert ja["je_vlasnik"] is False and ja["javni_kod"] == profil_v["javni_kod"]

    # Prijem stigao vlasniku vidi i član tima, i može da ga preuzme
    lazni_ai["odgovori"].append("RAZGOVOR_ZAVRŠEN: Hvala.")
    sesija = klijent.post("/prijem/razgovor", json={"kod": profil_v["javni_kod"], "saglasnost": True}).json()["sesija_id"]
    prijem_id = klijent.post("/prijem/poruka", json={"sesija_id": sesija, "poruka": "Zdravo"}).json()["prijem_id"]
    assert len(klijent.get("/prijem/lista", headers=zaglavlje_c).json()) == 1
    assert {m["advokat_email"] for m in lazni_ai["mejl"]} == {"a@example.com", "kolega@example.com"}

    odg = klijent.patch(f"/prijem/dodeli/{prijem_id}", json={"advokat_id": ja["id"]}, headers=zaglavlje_c)
    assert odg.status_code == 200
    lista = klijent.get("/prijem/lista", headers=zaglavlje_v).json()
    assert lista[0]["dodeljen_ime"] == "Kolega"

    # Član ne upravlja timom ni nazivom kancelarije
    assert klijent.post("/kancelarija/pozivnica", json={"email": "x@example.com"}, headers=zaglavlje_c).status_code == 403
    klijent.patch("/auth/azuriraj", json={"naziv_kancelarije": "Moja"}, headers=zaglavlje_c)
    assert klijent.get("/auth/ja", headers=zaglavlje_v).json()["naziv_kancelarije"] == "Kancelarija A"

    # Uklonjen član gubi pristup
    assert klijent.delete(f"/kancelarija/clan/{ja['id']}", headers=zaglavlje_v).status_code == 200
    assert klijent.get("/prijem/lista", headers=zaglavlje_c).status_code == 401


def test_obavestenja_mogu_da_se_iskljuce(klijent, lazni_ai):
    zaglavlje, profil = registruj(klijent)
    klijent.patch("/auth/azuriraj", json={"obavestenja": False}, headers=zaglavlje)
    lazni_ai["odgovori"].append("RAZGOVOR_ZAVRŠEN: Hvala.")
    sesija = klijent.post("/prijem/razgovor", json={"kod": profil["javni_kod"], "saglasnost": True}).json()["sesija_id"]
    klijent.post("/prijem/poruka", json={"sesija_id": sesija, "poruka": "Zdravo"})
    assert lazni_ai["mejl"] == []


def test_limit_tima_po_planu(klijent, monkeypatch):
    zaglavlje, profil = registruj(klijent)
    postavi_plan(profil["id"], "starter")
    odg, _ = pozovi(klijent, zaglavlje, "k1@example.com", monkeypatch)
    assert odg.status_code == 403

    postavi_plan(profil["id"], "pro")
    for i in range(4):
        odg, _ = pozovi(klijent, zaglavlje, f"k{i}@example.com", monkeypatch)
        assert odg.status_code == 200
    odg, _ = pozovi(klijent, zaglavlje, "k9@example.com", monkeypatch)
    assert odg.status_code == 403 and "najviše 5" in odg.json()["detail"]


def _png(boja=(200, 30, 30)):
    bafer = io.BytesIO()
    Image.new("RGB", (120, 40), boja).save(bafer, "PNG")
    return "data:image/png;base64," + base64.b64encode(bafer.getvalue()).decode()


def test_brending(klijent, lazni_ai):
    zaglavlje, profil = registruj(klijent)
    postavi_plan(profil["id"], "pro")
    assert klijent.put("/kancelarija/brending", json={"logo": _png(), "boja": "#AA0000"}, headers=zaglavlje).status_code == 403

    postavi_plan(profil["id"], "kancelarija")
    assert klijent.put("/kancelarija/brending", json={"boja": "crvena"}, headers=zaglavlje).status_code == 400
    lazni = "data:image/png;base64," + base64.b64encode(b"nije slika").decode()
    assert klijent.put("/kancelarija/brending", json={"logo": lazni}, headers=zaglavlje).status_code == 400
    assert klijent.put("/kancelarija/brending", json={"logo": _png(), "boja": "#AA0000"}, headers=zaglavlje).status_code == 200

    info = klijent.get(f"/prijem/kancelarija/{profil['javni_kod']}").json()
    assert info["boja"] == "#aa0000" and info["logo"].startswith("data:image/png") and info["bez_lexintake"]

    lazni_ai["odgovori"].append("RAZGOVOR_ZAVRŠEN: Hvala.")
    sesija = klijent.post("/prijem/razgovor", json={"kod": profil["javni_kod"], "saglasnost": True}).json()["sesija_id"]
    prijem_id = klijent.post("/prijem/poruka", json={"sesija_id": sesija, "poruka": "Zdravo"}).json()["prijem_id"]
    pdf = klijent.get(f"/prijem/pdf/{prijem_id}", headers=zaglavlje)
    assert pdf.status_code == 200 and b"/Subtype /Image" in pdf.content


def test_api_kljuc(klijent, lazni_ai):
    zaglavlje, profil = registruj(klijent)
    postavi_plan(profil["id"], "pro")
    assert klijent.post("/kancelarija/api-kljuc", headers=zaglavlje).status_code == 403

    postavi_plan(profil["id"], "kancelarija")
    kljuc = klijent.post("/kancelarija/api-kljuc", headers=zaglavlje).json()["api_kljuc"]
    api = {"Authorization": f"Bearer {kljuc}"}

    lazni_ai["odgovori"].append("RAZGOVOR_ZAVRŠEN: Hvala.")
    sesija = klijent.post("/prijem/razgovor", json={"kod": profil["javni_kod"], "saglasnost": True}).json()["sesija_id"]
    prijem_id = klijent.post("/prijem/poruka", json={"sesija_id": sesija, "poruka": "Zdravo"}).json()["prijem_id"]

    prijemi = klijent.get("/api/v1/prijemi", headers=api).json()["prijemi"]
    assert [p["id"] for p in prijemi] == [prijem_id]
    assert klijent.get("/api/v1/prijemi?od=2099-01-01T00:00:00Z", headers=api).json()["prijemi"] == []
    assert klijent.get(f"/api/v1/prijemi/{prijem_id}", headers=api).json()["klijent_ime"] == "Marko Petrović"

    # JWT advokata nije API ključ, a opozvan ključ više ne radi
    assert klijent.get("/api/v1/prijemi", headers=zaglavlje).status_code == 401
    klijent.delete("/kancelarija/api-kljuc", headers=zaglavlje)
    assert klijent.get("/api/v1/prijemi", headers=api).status_code == 401

    # Kad pretplata istekne, API se gasi
    kljuc = klijent.post("/kancelarija/api-kljuc", headers=zaglavlje).json()["api_kljuc"]
    postavi_plan(profil["id"], "kancelarija", status="istekla")
    assert klijent.get("/api/v1/prijemi", headers={"Authorization": f"Bearer {kljuc}"}).status_code == 403
