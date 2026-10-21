import logging
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text, inspect

from .config import get_settings
from .database import engine, Base
from .routes import auth, prijem, placanje
from .services.auth import generisi_javni_kod, PROBNI_PERIOD_DANA

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lexintake")

Base.metadata.create_all(bind=engine)

def migriraj_bazu():
    """Dodaje kolone koje create_all ne dodaje u postojeće tabele.

    Tipovi moraju da rade i na SQLite-u i na PostgreSQL-u (npr. TIMESTAMP, ne DATETIME).
    """
    inspector = inspect(engine)

    nove_kolone = {
        "advokati": {
            "plan": "VARCHAR(20) DEFAULT 'probni'",
            "status_pretplate": "VARCHAR(20) DEFAULT 'probni_period'",
            "lemonsqueezy_id": "VARCHAR(100)",
            "datum_isteka_probe": "TIMESTAMP",
            "javni_kod": "VARCHAR(32)",
            "datum_isteka_pretplate": "TIMESTAMP",
        },
        "prijemi": {
            "analiza_status": "VARCHAR(20)",
        },
    }

    with engine.connect() as konekcija:
        for tabela, kolone_tabele in nove_kolone.items():
            postojece = [k["name"] for k in inspector.get_columns(tabela)]
            for naziv, tip in kolone_tabele.items():
                if naziv not in postojece:
                    log.info("Migracija: dodajem %s.%s", tabela, naziv)
                    konekcija.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {naziv} {tip}"))
                    konekcija.commit()

        konekcija.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_advokati_javni_kod ON advokati (javni_kod)"))

        # Postojeći advokati dobijaju javni kod za link upitnika
        bez_koda = konekcija.execute(text("SELECT id FROM advokati WHERE javni_kod IS NULL")).fetchall()
        for (advokat_id,) in bez_koda:
            konekcija.execute(
                text("UPDATE advokati SET javni_kod = :kod WHERE id = :id"),
                {"kod": generisi_javni_kod(), "id": advokat_id}
            )

        # Probni period bez datuma isteka (stari nalozi) dobija pun probni period od danas
        konekcija.execute(
            text("UPDATE advokati SET datum_isteka_probe = :datum WHERE status_pretplate = 'probni_period' AND datum_isteka_probe IS NULL"),
            {"datum": datetime.utcnow() + timedelta(days=PROBNI_PERIOD_DANA)}
        )

        konekcija.execute(text(
            "UPDATE prijemi SET analiza_status = CASE WHEN ai_analiza IS NULL THEN 'neuspesna' ELSE 'gotova' END "
            "WHERE analiza_status IS NULL"
        ))
        konekcija.commit()

migriraj_bazu()

settings = get_settings()

if len(settings.secret_key) < 32:
    log.warning("SECRET_KEY je kraći od 32 znaka - koristite dugačak nasumičan ključ u produkciji")

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origini.split(",") if o.strip()],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

NAZIVI_POLJA = {
    "ime": "ime",
    "email": "email",
    "lozinka": "lozinka",
    "naziv_kancelarije": "naziv kancelarije",
    "telefon": "telefon",
    "poruka": "poruka",
    "kod": "kod upitnika",
}

@app.exception_handler(RequestValidationError)
async def greska_validacije(request: Request, greska: RequestValidationError):
    """Vraća jednu čitljivu poruku na srpskom umesto Pydantic liste grešaka."""
    prva = greska.errors()[0] if greska.errors() else {}
    polje = next((str(d) for d in reversed(prva.get("loc", [])) if isinstance(d, str) and d != "body"), "")
    naziv = NAZIVI_POLJA.get(polje, polje)
    tip = prva.get("type", "")
    ogranicenja = prva.get("ctx", {}) or {}

    if polje == "lozinka" and tip == "string_too_short":
        poruka = f"Lozinka mora imati najmanje {ogranicenja.get('min_length', 8)} karaktera."
    elif polje == "email":
        poruka = "Unesite ispravnu email adresu."
    elif polje == "poruka" and tip == "string_too_long":
        poruka = f"Poruka je predugačka (najviše {ogranicenja.get('max_length')} karaktera)."
    elif tip == "string_too_short":
        poruka = f"Polje '{naziv}' je prekratko."
    elif tip == "string_too_long":
        poruka = f"Polje '{naziv}' je predugačko."
    elif tip == "missing":
        poruka = f"Polje '{naziv}' je obavezno."
    else:
        poruka = f"Proverite polje '{naziv}'." if naziv else "Neispravan zahtev."

    return JSONResponse(status_code=422, content={"detail": poruka})

app.include_router(auth.ruter)
app.include_router(prijem.ruter)
app.include_router(placanje.ruter)

@app.get("/")
def root():
    return {
        "aplikacija": settings.app_name,
        "verzija": settings.app_version,
        "status": "aktivan"
    }

@app.get("/zdravlje")
def zdravlje():
    return {"status": "OK"}
