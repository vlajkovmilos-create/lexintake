import hashlib
import hmac
import json
from sqlalchemy.orm import Session
from datetime import datetime
from ..models import Advokat
from ..config import get_settings

settings = get_settings()

MAPA_PROIZVODA = {
    "LexIntake Pro": "pro",
    "LexIntake Starter": "starter",
    "LexIntake Kancelarija": "kancelarija",
}

def proveri_potpis(sirovi_sadrzaj: bytes, potpis: str) -> bool:
    """Proverava da li webhook zaista dolazi od Lemon Squeezy-a."""
    if not settings.lemonsqueezy_webhook_secret:
        return False

    izracunati_potpis = hmac.new(
        settings.lemonsqueezy_webhook_secret.encode(),
        sirovi_sadrzaj,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(izracunati_potpis, potpis)


def obradi_webhook(db: Session, dogadjaj: dict) -> bool:
    """Obrađuje webhook događaj od Lemon Squeezy-a i ažurira status advokata."""

    naziv_dogadjaja = dogadjaj.get("meta", {}).get("event_name")
    podaci = dogadjaj.get("data", {}).get("attributes", {})

    email_kupca = podaci.get("user_email") or podaci.get("customer_email")
    naziv_proizvoda = podaci.get("product_name", "")
    status_ls = podaci.get("status")  # active, cancelled, expired, on_trial
    pretplata_id = dogadjaj.get("data", {}).get("id")

    if not email_kupca:
        return False

    advokat = db.query(Advokat).filter(Advokat.email == email_kupca).first()
    if not advokat:
        return False

    plan = MAPA_PROIZVODA.get(naziv_proizvoda, "pro")

    if naziv_dogadjaja == "subscription_created":
        advokat.plan = plan
        advokat.status_pretplate = "aktivna" if status_ls == "active" else "probni_period"
        advokat.lemonsqueezy_id = str(pretplata_id)

    elif naziv_dogadjaja == "subscription_updated":
        advokat.plan = plan
        if status_ls == "active":
            advokat.status_pretplate = "aktivna"
        elif status_ls == "on_trial":
            advokat.status_pretplate = "probni_period"
        elif status_ls == "cancelled":
            advokat.status_pretplate = "otkazana"
        elif status_ls == "expired":
            advokat.status_pretplate = "istekla"

    elif naziv_dogadjaja == "subscription_cancelled":
        advokat.status_pretplate = "otkazana"

    elif naziv_dogadjaja == "subscription_expired":
        advokat.status_pretplate = "istekla"
        advokat.aktivan = False

    db.commit()
    return True