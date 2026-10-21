import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Advokat
from ..config import get_settings
from .auth import nadji_po_emailu

settings = get_settings()
log = logging.getLogger(__name__)

MAPA_PROIZVODA = {
    "LexIntake Pro": "pro",
    "LexIntake Starter": "starter",
    "LexIntake Kancelarija": "kancelarija",
}

# Mesečni limit prijema po planu (None = neograničeno)
LIMIT_PRIJEMA_MESECNO = {
    "starter": 30,
}

# Lemon Squeezy status pretplate -> naš status_pretplate
MAPA_STATUSA = {
    "active": "aktivna",
    "on_trial": "aktivna",
    "past_due": "aktivna",  # LS još pokušava naplatu; ne gasimo odmah
    "cancelled": "otkazana",  # važi do ends_at
    "paused": "istekla",
    "unpaid": "istekla",
    "expired": "istekla",
}

DOGADJAJI_PRETPLATE = {
    "subscription_created",
    "subscription_updated",
    "subscription_cancelled",
    "subscription_resumed",
    "subscription_expired",
    "subscription_paused",
    "subscription_unpaused",
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


def osvezi_status_pretplate(db: Session, advokat: Advokat) -> str:
    """Prevodi istekli probni period / otkazanu pretplatu u 'istekla' i vraća trenutni status."""
    sada = datetime.utcnow()
    novi_status = advokat.status_pretplate

    if advokat.status_pretplate == "probni_period":
        if advokat.datum_isteka_probe is None or advokat.datum_isteka_probe <= sada:
            novi_status = "istekla"
    elif advokat.status_pretplate == "otkazana":
        if advokat.datum_isteka_pretplate is None or advokat.datum_isteka_pretplate <= sada:
            novi_status = "istekla"

    if novi_status != advokat.status_pretplate:
        advokat.status_pretplate = novi_status
        db.commit()
    return novi_status


def moze_da_prima_prijeme(db: Session, advokat: Advokat) -> bool:
    return osvezi_status_pretplate(db, advokat) in ("probni_period", "aktivna", "otkazana")


def _parsiraj_datum(vrednost: Optional[str]) -> Optional[datetime]:
    if not vrednost:
        return None
    try:
        datum = datetime.fromisoformat(vrednost.replace("Z", "+00:00"))
    except ValueError:
        return None
    if datum.tzinfo:
        datum = datum.astimezone(timezone.utc).replace(tzinfo=None)
    return datum


def _nadji_advokata(db: Session, dogadjaj: dict, email_kupca: Optional[str]) -> Optional[Advokat]:
    # Prvo po ID-ju iz checkout linka (checkout[custom][advokat_id]), pa po emailu
    custom = dogadjaj.get("meta", {}).get("custom_data") or {}
    advokat_id = str(custom.get("advokat_id", "")).strip()
    if advokat_id.isdigit():
        advokat = db.query(Advokat).filter(Advokat.id == int(advokat_id)).first()
        if advokat:
            return advokat
    if email_kupca:
        return nadji_po_emailu(db, email_kupca)
    return None


def obradi_webhook(db: Session, dogadjaj: dict) -> bool:
    """Obrađuje webhook događaj od Lemon Squeezy-a i ažurira status advokata."""

    naziv_dogadjaja = dogadjaj.get("meta", {}).get("event_name")
    if naziv_dogadjaja not in DOGADJAJI_PRETPLATE:
        return False

    podaci = dogadjaj.get("data", {}).get("attributes", {})
    email_kupca = podaci.get("user_email") or podaci.get("customer_email")

    advokat = _nadji_advokata(db, dogadjaj, email_kupca)
    if not advokat:
        log.warning("Webhook %s: advokat nije pronađen (email=%s)", naziv_dogadjaja, email_kupca)
        return False

    status_ls = podaci.get("status")
    if naziv_dogadjaja == "subscription_expired":
        status_ls = "expired"

    novi_status = MAPA_STATUSA.get(status_ls)
    if novi_status:
        advokat.status_pretplate = novi_status

    naziv_proizvoda = podaci.get("product_name", "")
    if naziv_proizvoda in MAPA_PROIZVODA:
        advokat.plan = MAPA_PROIZVODA[naziv_proizvoda]
    elif naziv_proizvoda:
        log.warning("Nepoznat proizvod u webhook-u: %s", naziv_proizvoda)

    pretplata_id = dogadjaj.get("data", {}).get("id")
    if pretplata_id:
        advokat.lemonsqueezy_id = str(pretplata_id)

    advokat.datum_isteka_pretplate = _parsiraj_datum(podaci.get("ends_at") or podaci.get("renews_at"))

    db.commit()
    log.info("Webhook %s: advokat %s -> %s / %s", naziv_dogadjaja, advokat.id, advokat.plan, advokat.status_pretplate)
    return True
