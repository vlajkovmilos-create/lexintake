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

    prijemi = relationship("Prijem", back_populates="advokat")

    def __repr__(self):
        return f"<Advokat {self.email}>"


class Prijem(Base):
    __tablename__ = "prijemi"

    id = Column(Integer, primary_key=True, index=True)
    advokat_id = Column(Integer, ForeignKey("advokati.id"), nullable=False)

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

    razgovor_json = Column(Text)

    # Status
    status = Column(String(30), default="novi") 
    izvestaj_poslat = Column(Boolean, default=False)

    datum_prijema = Column(DateTime, default=datetime.utcnow)
    datum_azuriranja = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    advokat = relationship("Advokat", back_populates="prijemi")

    def __repr__(self):
        return f"<Prijem {self.klijent_ime} - {self.oblast_prava}>"