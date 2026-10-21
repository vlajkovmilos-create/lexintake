from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base

class Advokat(Base):
    __tablename__ = "advokati"

    id = Column(Integer, primary_key=True, index=True)
    ime = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, index=True, nullable=False)
    lozinka_hash = Column(String(255), nullable=False)
    naziv_kancelarije = Column(String(200))
    telefon = Column(String(20))
    aktivan = Column(Boolean, default=True)
    datum_registracije = Column(DateTime, default=datetime.utcnow)

    # Javni kod za link upitnika (upitnik.html?k=...), da se ID advokata ne vidi
    javni_kod = Column(String(32), unique=True, index=True)

    # Tim: član kancelarije pokazuje na vlasnika; vlasnik (i advokat bez tima) ima NULL.
    # Pretplata, link upitnika, brending, API ključ i prijemi pripadaju vlasniku.
    vlasnik_id = Column(Integer, ForeignKey("advokati.id"), index=True)
    obavestenja = Column(Boolean, default=True)  # mejl o novom prijemu

    # White-label (plan Kancelarija)
    logo = Column(Text)  # data URL (PNG/JPEG/WebP), najviše ~200 KB
    boja = Column(String(7))  # npr. #0f2744

    # API pristup (plan Kancelarija); čuva se samo heš ključa
    api_kljuc_hash = Column(String(64), index=True)
    api_kljuc_prefiks = Column(String(16))
    api_kljuc_datum = Column(DateTime)

    plan = Column(String(20), default="probni")  # probni / starter / pro / kancelarija
    status_pretplate = Column(String(20), default="probni_period")  # probni_period / aktivna / istekla / otkazana
    lemonsqueezy_id = Column(String(100))  # ID pretplate u Lemon Squeezy
    datum_isteka_probe = Column(DateTime)
    datum_isteka_pretplate = Column(DateTime)  # do kada važi otkazana pretplata

    prijemi = relationship("Prijem", back_populates="advokat", foreign_keys="Prijem.advokat_id")

    @property
    def kancelarija_id(self) -> int:
        return self.vlasnik_id or self.id

    @property
    def je_vlasnik(self) -> bool:
        return self.vlasnik_id is None

    def __repr__(self):
        return f"<Advokat {self.email}>"


class Prijem(Base):
    __tablename__ = "prijemi"

    id = Column(Integer, primary_key=True, index=True)
    advokat_id = Column(Integer, ForeignKey("advokati.id"), nullable=False, index=True)  # vlasnik kancelarije
    dodeljen_id = Column(Integer, ForeignKey("advokati.id"))  # advokat iz tima koji vodi prijem

    klijent_ime = Column(String(100))
    klijent_email = Column(String(150))
    klijent_telefon = Column(String(20))

    oblast_prava = Column(String(100))
    opis_problema = Column(Text)
    detalji_slucaja = Column(Text)
    dokumenti_napomena = Column(Text)

    ai_analiza = Column(Text)
    procena_urgentnosti = Column(String(20))
    preporuceni_koraci = Column(Text)
    analiza_status = Column(String(20), default="u_obradi")  # u_obradi / gotova / neuspesna

    razgovor_json = Column(Text)

    # Status
    status = Column(String(30), default="novi")
    izvestaj_poslat = Column(Boolean, default=False)

    datum_prijema = Column(DateTime, default=datetime.utcnow)
    datum_azuriranja = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    advokat = relationship("Advokat", back_populates="prijemi", foreign_keys=[advokat_id])

    def __repr__(self):
        return f"<Prijem {self.klijent_ime} - {self.oblast_prava}>"


class Razgovor(Base):
    """Razgovor klijenta sa asistentom; istorija se čuva na serveru, ne kod klijenta."""
    __tablename__ = "razgovori"

    id = Column(String(36), primary_key=True)  # sesija_id (uuid4)
    advokat_id = Column(Integer, ForeignKey("advokati.id"), nullable=False, index=True)

    # Poruke tačno u obliku u kom idu ka Claude API-ju (uključujući thinking blokove)
    poruke_json = Column(Text, nullable=False, default="[]")
    uvodna_poruka = Column(Text)
    sistem_poruka = Column(Text)  # zamrznut na početku, da se istorija ne menja tokom razgovora
    broj_poruka_klijenta = Column(Integer, default=0)

    zavrsen = Column(Boolean, default=False)
    prijem_id = Column(Integer, ForeignKey("prijemi.id"))

    datum_saglasnosti = Column(DateTime)
    datum_pocetka = Column(DateTime, default=datetime.utcnow, index=True)
    datum_azuriranja = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Pozivnica(Base):
    """Poziv kolegi da se pridruži kancelariji; token se šalje mejlom, u bazi je samo heš."""
    __tablename__ = "pozivnice"

    id = Column(Integer, primary_key=True)
    vlasnik_id = Column(Integer, ForeignKey("advokati.id"), nullable=False, index=True)
    email = Column(String(150), nullable=False)
    token_hash = Column(String(64), unique=True, nullable=False)
    datum_slanja = Column(DateTime, default=datetime.utcnow)
    datum_isteka = Column(DateTime, nullable=False)
    prihvacena = Column(Boolean, default=False)
