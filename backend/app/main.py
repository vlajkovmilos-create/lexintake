from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings
from .database import engine, Base
from .routes import auth, prijem

Base.metadata.create_all(bind=engine)

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