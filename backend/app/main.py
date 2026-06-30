from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings
from .database import engine, Base
from .routes import auth, prijem, placanje

Base.metadata.create_all(bind=engine)

from sqlalchemy import text, inspect

def migriraj_bazu():
    inspector = inspect(engine)
    kolone = [k["name"] for k in inspector.get_columns("advokati")]
    
    nove_kolone = {
        "plan": "VARCHAR(20) DEFAULT 'probni'",
        "status_pretplate": "VARCHAR(20) DEFAULT 'probni_period'",
        "lemonsqueezy_id": "VARCHAR(100)",
        "datum_isteka_probe": "DATETIME"
    }
    
    with engine.connect() as konekcija:
        for naziv, tip in nove_kolone.items():
            if naziv not in kolone:
                konekcija.execute(text(f"ALTER TABLE advokati ADD COLUMN {naziv} {tip}"))
                konekcija.commit()

migriraj_bazu()

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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