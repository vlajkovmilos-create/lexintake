import json
from anthropic import Anthropic
from ..config import get_settings

settings = get_settings()
klijent = Anthropic(api_key=settings.anthropic_api_key)

SISTEM_PORUKA = """Ti si profesionalni asistent advokatske kancelarije. Tvoj zadatak je da vodiš strukturirani razgovor sa potencijalnim klijentom i prikupiš sve relevantne informacije pre prve konsultacije sa advokatom.

VAŽNA PRAVILA:
- Nikada ne daješ pravne savete niti tumačiš zakone
- Uvek si ljubazan, strpljiv i profesionalan
- Pišeš isključivo na srpskom jeziku
- Pitanja postavljaš jedno po jedno, ne pretrpavaj klijenta
- Ako klijent nije siguran u odgovor, prihvati i nastavi dalje

FAZE RAZGOVORA:
1. Pozdrav i prikupljanje kontakt podataka (ime, telefon, email)
2. Opis problema - šta se desilo, kratko i jasno
3. Detalji slučaja - kada, gde, ko je uključen
4. Dokumentacija - da li postoje dokumenti, ugovori, prepiska
5. Urgentnost - da li postoje rokovi ili hitne okolnosti
6. Zaključak - zahvalnost i najava izveštaja

Kada prikupiš sve informacije, završi razgovor rečenicom koja počinje sa: "RAZGOVOR_ZAVRŠEN:"
"""

def nastavi_razgovor(istorija: list, nova_poruka: str) -> str:
    """Prima istoriju razgovora i novu poruku, vraća odgovor asistenta."""
    
    poruke = istorija + [{"role": "user", "content": nova_poruka}]
    
    odgovor = klijent.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SISTEM_PORUKA,
        messages=poruke
    )
    
    return odgovor.content[0].text

def generisi_analizu(razgovor_json: str) -> dict:
    """Na osnovu završenog razgovora generiše strukturiranu AI analizu za advokata."""
    
    prompt = f"""Na osnovu sledećeg razgovora sa klijentom, generiši strukturiranu analizu za advokata.

RAZGOVOR:
{razgovor_json}

Vrati SAMO validan JSON objekat bez ikakvih dodatnih objašnjenja, u sledećem formatu:
{{
    "klijent_ime": "ime i prezime klijenta",
    "klijent_email": "email klijenta ili prazno",
    "klijent_telefon": "telefon klijenta ili prazno",
    "oblast_prava": "npr. Radno pravo, Porodično pravo, Privredno pravo, Krivično pravo, Nekretnine, Nasledno pravo, Ostalo",
    "opis_problema": "kratak opis problema klijentovim rečima, 2-3 rečenice",
    "detalji_slucaja": "ključni detalji slučaja koji su relevantni za advokata",
    "dokumenti_napomena": "koje dokumente klijent poseduje ili treba da pribavi",
    "ai_analiza": "stručna analiza slučaja za advokata, relevantni zakoni i propisi, 3-5 rečenica",
    "procena_urgentnosti": "niska ili srednja ili visoka",
    "preporuceni_koraci": "konkretni preporučeni koraci za advokata, 2-4 tačke"
}}"""

    odgovor = klijent.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )
    
    tekst = odgovor.content[0].text.strip()
    
    if tekst.startswith("```"):
        linije = tekst.split("\n")
        tekst = "\n".join(linije[1:-1])
    
    return json.loads(tekst)