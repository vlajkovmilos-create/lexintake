from tests.conftest import registruj


def test_registracija_i_prijava(klijent):
    zaglavlje, profil = registruj(klijent, email="Mika@Example.com")
    assert profil["email"] == "mika@example.com"
    assert profil["status_pretplate"] == "probni_period"
    assert len(profil["javni_kod"]) >= 8

    odg = klijent.post("/auth/prijava", json={"email": "MIKA@example.com", "lozinka": "lozinka123"})
    assert odg.status_code == 200
    assert odg.json()["advokat_id"] == profil["id"]


def test_validacija_na_srpskom(klijent):
    odg = klijent.post("/auth/registracija", json={"ime": "Ana", "email": "ana@example.com", "lozinka": "x"})
    assert odg.status_code == 422
    assert odg.json()["detail"] == "Lozinka mora imati najmanje 8 karaktera."

    odg = klijent.post("/auth/registracija", json={"ime": "Ana", "email": "nije-email", "lozinka": "lozinka123"})
    assert odg.json()["detail"] == "Unesite ispravnu email adresu."


def test_pogresna_lozinka_i_ogranicenje(klijent):
    registruj(klijent)
    for _ in range(10):
        odg = klijent.post("/auth/prijava", json={"email": "a@example.com", "lozinka": "pogresna1"})
        assert odg.status_code == 401
    odg = klijent.post("/auth/prijava", json={"email": "a@example.com", "lozinka": "lozinka123"})
    assert odg.status_code == 429


def test_rute_bez_tokena_vracaju_401(klijent):
    for metod, putanja in [
        ("get", "/auth/ja"), ("patch", "/auth/azuriraj"), ("get", "/prijem/lista"),
        ("get", "/prijem/detalji/1"), ("patch", "/prijem/status/1"), ("get", "/prijem/pdf/1"),
        ("post", "/prijem/analiza/1"),
    ]:
        odg = klijent.request(metod.upper(), putanja, json={})
        assert odg.status_code == 401, putanja

    odg = klijent.get("/prijem/lista", headers={"Authorization": "Bearer lazni.token.xyz"})
    assert odg.status_code == 401


def test_azuriranje_menja_samo_poslata_polja(klijent):
    zaglavlje, _ = registruj(klijent, telefon="0641112222")
    odg = klijent.patch("/auth/azuriraj", json={"ime": "Novo Ime"}, headers=zaglavlje)
    assert odg.status_code == 200
    assert odg.json()["ime"] == "Novo Ime"
    assert odg.json()["telefon"] == "0641112222"
    assert odg.json()["naziv_kancelarije"] == "Kancelarija A"
