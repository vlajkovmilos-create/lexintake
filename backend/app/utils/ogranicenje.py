"""Jednostavno ograničavanje broja zahteva (klizni prozor), u memoriji procesa.

Dovoljno za jednu Render instancu; pri više instanci svaka broji za sebe.
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_zahtevi: dict[str, deque] = defaultdict(deque)
_brava = threading.Lock()

def dozvoli(kljuc: str, limit: int, prozor_sekundi: int) -> bool:
    sada = time.monotonic()
    with _brava:
        red = _zahtevi[kljuc]
        while red and red[0] <= sada - prozor_sekundi:
            red.popleft()
        if len(red) >= limit:
            return False
        red.append(sada)
        return True

def ogranici(kljuc: str, limit: int, prozor_sekundi: int, poruka: str = "Previše zahteva. Pokušajte ponovo malo kasnije."):
    if not dozvoli(kljuc, limit, prozor_sekundi):
        raise HTTPException(status_code=429, detail=poruka)

def ip_klijenta(request: Request) -> str:
    # Render prosleđuje pravu adresu klijenta u X-Forwarded-For
    prosledjeno = request.headers.get("x-forwarded-for")
    if prosledjeno:
        return prosledjeno.split(",")[0].strip()
    return request.client.host if request.client else "nepoznat"

def resetuj():
    """Koristi se u testovima."""
    with _brava:
        _zahtevi.clear()
