import json
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import Advokat, Prijem
from tests.conftest import registruj


def zapocni(klijent, kod):
    odg = klijent.post("/prijem/razgovor", json={"kod": kod, "saglasnost": True})
    assert odg.status_code == 200, odg.text
    return odg.json()["sesija_id"]


def test_ceo_tok_razgovora(klijent, lazni_ai):
    zaglavlje, profil = registruj(klijent)
    lazni_ai["odgovori"].extend(["Opišite problem.", "Hvala. RAZGOVOR_ZAVRŠEN: Advokat će vas kontaktirati."])

    info = klijent.get(f"/prijem/kancelarija/{profil['javni_kod']}").json()
    assert info == {"naziv_kancelarije": "Kancelarija A", "prima_prijeme": True}

    sesija = zapocni(klijent, profil["javni_kod"])
    odg = klijent.post("/prijem/poruka", json={"sesija_id": sesija, "poruka": "Marko, 064123"}).json()
    assert odg["zavrseno"] is False

    odg = klijent.post("/prijem/poruka", json={"sesija_id": sesija, "poruka": "Dobio sam otkaz."}).json()
    assert odg["zavrseno"] is True
    assert "RAZGOVOR_ZAVRŠEN" not in odg["odgovor"]
    prijem_id = odg["prijem_id"]

    # Istorija ide modelu sa servera: prva poruka je klijentova, ne pozdrav
    druga = lazni_ai["razgovor"][1]
    assert druga[0] == {"role": "user", "content": "Marko, 064123"}
    assert len(druga) == 3

    # Analiza i mejl su odrađeni u pozadini
    assert lazni_ai["analiza"] == 1
    assert len(lazni_ai["mejl"]) == 1
    assert lazni_ai["mejl"][0]["klijent_email"] == "marko@example.com"

    detalji = klijent.get(f"/prijem/detalji/{prijem_id}", headers=zaglavlje).json()
    assert detalji["analiza_status"] == "gotova"
    assert detalji["klijent_telefon"] == "+381 64 123 4567 ili"  # skraćeno na 20 znakova
    assert detalji["razgovor"][0]["role"] == "assistant"
    assert "RAZGOVOR_ZAVRŠEN" not in json.dumps(detalji["razgovor"], ensure_ascii=False)

    # Završen razgovor ne prima nove poruke
    odg = klijent.post("/prijem/poruka", json={"sesija_id": sesija, "poruka": "Još nešto"})
    assert odg.status_code == 409

    # Obnova razgovora posle osvežavanja
    obnova = klijent.get(f"/prijem/razgovor/{sesija}").json()
    assert obnova["zavrseno"] is True
    assert [p["role"] for p in obnova["poruke"]] == ["assistant", "user", "assistant", "user", "assistant"]

    pdf = klijent.get(f"/prijem/pdf/{prijem_id}", headers=zaglavlje)
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")


def test_advokat_ne_vidi_tudje_prijeme(klijent, lazni_ai):
    zaglavlje_a, profil_a = registruj(klijent, email="a@example.com")
    zaglavlje_b, _ = registruj(klijent, email="b@example.com")
    lazni_ai["odgovori"].append("RAZGOVOR_ZAVRŠEN: Hvala.")

    sesija = zapocni(klijent, profil_a["javni_kod"])
    prijem_id = klijent.post("/prijem/poruka", json={"sesija_id": sesija, "poruka": "Zdravo"}).json()["prijem_id"]

    assert klijent.get("/prijem/lista", headers=zaglavlje_b).json() == []
    assert klijent.get(f"/prijem/detalji/{prijem_id}", headers=zaglavlje_b).status_code == 404
    assert klijent.get(f"/prijem/pdf/{prijem_id}", headers=zaglavlje_b).status_code == 404
    assert klijent.patch(f"/prijem/status/{prijem_id}", json={"status": "zatvoreno"}, headers=zaglavlje_b).status_code == 404

    assert len(klijent.get("/prijem/lista", headers=zaglavlje_a).json()) == 1
    assert klijent.patch(f"/prijem/status/{prijem_id}", json={"status": "zatvoreno"}, headers=zaglavlje_a).status_code == 200


def test_neispravan_kod_i_saglasnost(klijent):
    _, profil = registruj(klijent)
    assert klijent.get("/prijem/kancelarija/nepostojeci").status_code == 404
    assert klijent.post("/prijem/razgovor", json={"kod": "nepostojeci", "saglasnost": True}).status_code == 404
    odg = klijent.post("/prijem/razgovor", json={"kod": profil["javni_kod"], "saglasnost": False})
    assert odg.status_code == 400


def test_istekao_probni_period(klijent):
    zaglavlje, profil = registruj(klijent)
    db = SessionLocal()
    advokat = db.get(Advokat, profil["id"])
    advokat.datum_isteka_probe = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    db.close()

    odg = klijent.post("/prijem/razgovor", json={"kod": profil["javni_kod"], "saglasnost": True})
    assert odg.status_code == 403
    assert klijent.get("/auth/ja", headers=zaglavlje).json()["status_pretplate"] == "istekla"


def test_odbijen_odgovor_ne_menja_istoriju(klijent, lazni_ai):
    _, profil = registruj(klijent)
    lazni_ai["odgovori"].extend([None, "Opišite problem."])
    sesija = zapocni(klijent, profil["javni_kod"])

    odg = klijent.post("/prijem/poruka", json={"sesija_id": sesija, "poruka": "nešto čudno"}).json()
    assert odg["zavrseno"] is False
    odg = klijent.post("/prijem/poruka", json={"sesija_id": sesija, "poruka": "Zovem se Ana"}).json()
    assert lazni_ai["razgovor"][1] == [{"role": "user", "content": "Zovem se Ana"}]


def test_limit_poruka_zatvara_razgovor(klijent, lazni_ai):
    _, profil = registruj(klijent)
    sesija = zapocni(klijent, profil["javni_kod"])
    for i in range(5):
        odg = klijent.post("/prijem/poruka", json={"sesija_id": sesija, "poruka": f"poruka {i}"}).json()
        assert odg["zavrseno"] is False
    odg = klijent.post("/prijem/poruka", json={"sesija_id": sesija, "poruka": "poslednja"}).json()
    assert odg["zavrseno"] is True and odg["prijem_id"]
    assert len(lazni_ai["razgovor"]) == 5  # poslednja poruka ne ide modelu


def test_preduga_poruka(klijent, lazni_ai):
    _, profil = registruj(klijent)
    sesija = zapocni(klijent, profil["javni_kod"])
    odg = klijent.post("/prijem/poruka", json={"sesija_id": sesija, "poruka": "a" * 2001})
    assert odg.status_code == 422
    assert "predugačka" in odg.json()["detail"]


def test_starter_mesecni_limit(klijent):
    _, profil = registruj(klijent)
    db = SessionLocal()
    advokat = db.get(Advokat, profil["id"])
    advokat.plan = "starter"
    advokat.status_pretplate = "aktivna"
    for _ in range(30):
        db.add(Prijem(advokat_id=advokat.id, status="novi"))
    db.commit()
    db.close()
    odg = klijent.post("/prijem/razgovor", json={"kod": profil["javni_kod"], "saglasnost": True})
    assert odg.status_code == 403


def test_brisanje_prijema(klijent, lazni_ai):
    zaglavlje_a, profil_a = registruj(klijent, email="a@example.com")
    zaglavlje_b, _ = registruj(klijent, email="b@example.com")
    lazni_ai["odgovori"].append("RAZGOVOR_ZAVRŠEN: Hvala.")
    sesija = zapocni(klijent, profil_a["javni_kod"])
    prijem_id = klijent.post("/prijem/poruka", json={"sesija_id": sesija, "poruka": "Zdravo"}).json()["prijem_id"]

    assert klijent.delete(f"/prijem/{prijem_id}", headers=zaglavlje_b).status_code == 404
    assert klijent.delete(f"/prijem/{prijem_id}", headers=zaglavlje_a).status_code == 200
    assert klijent.get("/prijem/lista", headers=zaglavlje_a).json() == []
    assert klijent.get(f"/prijem/razgovor/{sesija}").status_code == 404


def test_stari_nedovrseni_razgovori_se_brisu(klijent):
    from app.models import Razgovor
    _, profil = registruj(klijent)
    stara = zapocni(klijent, profil["javni_kod"])
    db = SessionLocal()
    db.get(Razgovor, stara).datum_pocetka = datetime.utcnow() - timedelta(days=31)
    db.commit()
    db.close()
    zapocni(klijent, profil["javni_kod"])
    assert klijent.get(f"/prijem/razgovor/{stara}").status_code == 404
