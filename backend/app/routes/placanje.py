import json
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.placanje import proveri_potpis, obradi_webhook

ruter = APIRouter(prefix="/placanje", tags=["Plaćanje"])

@ruter.post("/webhook")
async def lemonsqueezy_webhook(request: Request, db: Session = Depends(get_db)):
    sirovi_sadrzaj = await request.body()
    potpis = request.headers.get("X-Signature", "")

    if not proveri_potpis(sirovi_sadrzaj, potpis):
        raise HTTPException(status_code=401, detail="Neispravan potpis webhook-a")

    try:
        dogadjaj = json.loads(sirovi_sadrzaj)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Neispravan JSON format")

    uspeh = obradi_webhook(db, dogadjaj)

    return {"primljeno": True, "obradjeno": uspeh}