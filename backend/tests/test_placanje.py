import hashlib
import hmac
import json

from tests.conftest import registruj


def posalji(klijent, dogadjaj):
    telo = json.dumps(dogadjaj).encode()
    potpis = hmac.new(b"webhook-tajna", telo, hashlib.sha256).hexdigest()
    return klijent.post("/placanje/webhook", content=telo, headers={"X-Signature": potpis})


def dogadjaj(ime, status, email="drugi@example.com", advokat_id=None, ends_at=None, proizvod="LexIntake Pro"):
    meta = {"event_name": ime}
    if advokat_id:
        meta["custom_data"] = {"advokat_id": str(advokat_id)}
    return {"meta": meta, "data": {"id": "123", "attributes": {
        "user_email": email, "status": status, "product_name": proizvod, "ends_at": ends_at}}}


def test_neispravan_potpis(klijent):
    odg = klijent.post("/placanje/webhook", content=b"{}", headers={"X-Signature": "losa"})
    assert odg.status_code == 401


def test_pretplata_preko_custom_data(klijent):
    zaglavlje, profil = registruj(klijent)
    odg = posalji(klijent, dogadjaj("subscription_created", "active", advokat_id=profil["id"]))
    assert odg.json()["obradjeno"] is True
    ja = klijent.get("/auth/ja", headers=zaglavlje).json()
    assert ja["plan"] == "pro" and ja["status_pretplate"] == "aktivna"


def test_otkazana_vazi_do_kraja_perioda(klijent):
    zaglavlje, profil = registruj(klijent)
    posalji(klijent, dogadjaj("subscription_created", "active", email="A@example.com"))
    posalji(klijent, dogadjaj("subscription_cancelled", "cancelled", email="a@example.com", ends_at="2099-01-01T00:00:00.000000Z"))
    assert klijent.get("/auth/ja", headers=zaglavlje).json()["status_pretplate"] == "otkazana"
    odg = klijent.post("/prijem/razgovor", json={"kod": profil["javni_kod"], "saglasnost": True})
    assert odg.status_code == 200

    posalji(klijent, dogadjaj("subscription_expired", "expired", email="a@example.com"))
    assert klijent.get("/auth/ja", headers=zaglavlje).json()["status_pretplate"] == "istekla"
    odg = klijent.post("/prijem/razgovor", json={"kod": profil["javni_kod"], "saglasnost": True})
    assert odg.status_code == 403


def test_dogadjaji_faktura_se_ignorisu(klijent):
    zaglavlje, _ = registruj(klijent)
    odg = posalji(klijent, dogadjaj("subscription_payment_success", "paid", email="a@example.com"))
    assert odg.json()["obradjeno"] is False
    assert klijent.get("/auth/ja", headers=zaglavlje).json()["status_pretplate"] == "probni_period"
