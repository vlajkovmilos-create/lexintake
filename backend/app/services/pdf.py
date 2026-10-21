import io
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor, white
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image
from ..models import Prijem, Advokat

# Fontovi su u repou jer standardni PDF fontovi nemaju č, ć, đ
FONT_DIR = Path(__file__).resolve().parent.parent / "fonti"

pdfmetrics.registerFont(TTFont('DejaVu', str(FONT_DIR / 'DejaVuSans.ttf')))
pdfmetrics.registerFont(TTFont('DejaVu-Bold', str(FONT_DIR / 'DejaVuSans-Bold.ttf')))
pdfmetrics.registerFontFamily('DejaVu', normal='DejaVu', bold='DejaVu-Bold', italic='DejaVu', boldItalic='DejaVu-Bold')

NAVY = HexColor('#0f2744')
KREM = HexColor('#f5f0e8')
ZLATO = HexColor('#c9a84c')
SIVA = HexColor('#8a8070')
SVETLO_PLAVA = HexColor('#eef3f8')
POZADINA = HexColor('#fafaf8')
IVICA = HexColor('#ede7d9')

def boja_urgentnosti(u):
    return {
        "visoka": HexColor('#dc2626'),
        "srednja": HexColor('#d97706'),
        "niska": HexColor('#16a34a')
    }.get(u, HexColor('#6b7280'))

def tekst_urgentnosti(u):
    return {
        "visoka": "Visoka",
        "srednja": "Srednja",
        "niska": "Niska"
    }.get(u, "Nije određena")

def _t(vrednost) -> str:
    """Escape-uje tekst za ReportLab Paragraph i čuva prelome redova."""
    return escape(str(vrednost or "")).replace("\n", "<br/>")

def _transkript(razgovor_json: str) -> list:
    try:
        poruke = json.loads(razgovor_json or "[]")
    except json.JSONDecodeError:
        return []
    rezultat = []
    for p in poruke:
        sadrzaj = p.get("content", "")
        if isinstance(sadrzaj, list):
            sadrzaj = "\n".join(b.get("text", "") for b in sadrzaj if isinstance(b, dict) and b.get("type") == "text")
        sadrzaj = sadrzaj.replace("RAZGOVOR_ZAVRŠEN:", "").strip()
        if sadrzaj:
            rezultat.append((p.get("role"), sadrzaj))
    return rezultat

def _stil(ime, **kwargs) -> ParagraphStyle:
    osnovno = dict(fontName='DejaVu', fontSize=11, textColor=HexColor('#1a1610'), leading=16)
    osnovno.update(kwargs)
    return ParagraphStyle(ime, **osnovno)

def _kutija(sadrzaj, pozadina=POZADINA, levo=None) -> Table:
    t = Table([[sadrzaj]], colWidths=[17*cm])
    stil = [
        ('BACKGROUND', (0, 0), (-1, -1), pozadina),
        ('PADDING', (0, 0), (-1, -1), 10),
    ]
    if levo:
        stil.append(('LINEBEFORE', (0, 0), (0, -1), 3, levo))
    else:
        stil.append(('BOX', (0, 0), (-1, -1), 0.5, IVICA))
    t.setStyle(TableStyle(stil))
    return t

def _logo(brend: dict):
    from .kancelarija import logo_bajtovi
    bajtovi = logo_bajtovi(brend.get("logo"))
    if not bajtovi:
        return None
    try:
        slika = Image(io.BytesIO(bajtovi))
        # Najviše 4 x 1.4 cm, uz očuvanje proporcija
        odnos = min(4*cm / slika.imageWidth, 1.4*cm / slika.imageHeight)
        slika.drawWidth = slika.imageWidth * odnos
        slika.drawHeight = slika.imageHeight * odnos
        slika.hAlign = 'LEFT'
        return slika
    except Exception:
        return None

def generisi_pdf(prijem: Prijem, advokat: Advokat, brend: dict = None) -> bytes:
    """advokat je vlasnik kancelarije; brend dolazi iz kancelarija.brending (white-label)."""
    brend = brend or {}
    bez_lexintake = brend.get("bez_lexintake", False)
    boja_zaglavlja = HexColor(brend["boja"]) if brend.get("boja") else NAVY
    # Na svetloj boji zaglavlja tekst je taman, da ostane čitljiv
    svetla = (0.299*boja_zaglavlja.red + 0.587*boja_zaglavlja.green + 0.114*boja_zaglavlja.blue) > 0.6
    boja_teksta_zaglavlja = NAVY if svetla else KREM
    naziv = advokat.naziv_kancelarije or advokat.ime
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm,
        title=f"Prijem #{prijem.id}",
        author=naziv if bez_lexintake else "LexIntake"
    )

    elementi = []

    stil_naslov = _stil('Naslov', fontName='DejaVu-Bold', fontSize=20, textColor=NAVY, spaceAfter=4, leading=24)
    stil_podnaslov = _stil('Podnaslov', fontSize=10, textColor=SIVA, spaceAfter=16)
    stil_sekcija = _stil('Sekcija', fontName='DejaVu-Bold', fontSize=9, textColor=SIVA, spaceBefore=16, spaceAfter=8, keepWithNext=1)
    stil_vrednost = _stil('Vrednost', spaceAfter=4)
    stil_ai = _stil('AI', textColor=NAVY, leading=17)
    stil_napomena = _stil('Napomena', fontSize=8, textColor=SIVA, leading=11, spaceBefore=4)
    stil_polje = _stil('Polje')
    stil_klijent = _stil('Klijent', fontSize=10, leading=14, spaceAfter=6)
    stil_asistent = _stil('Asistent', fontSize=10, leading=14, spaceAfter=6, textColor=HexColor('#3d3830'), leftIndent=12)
    stil_podnozje = _stil('Podnozje', fontSize=9, textColor=SIVA, leading=12)

    datum = prijem.datum_prijema.strftime("%d.%m.%Y. u %H:%M")

    logo = _logo(brend) if bez_lexintake else None
    if logo:
        elementi.append(logo)
        elementi.append(Spacer(1, 0.3*cm))

    tabela_zaglavlje = Table([[
        Paragraph(f'<b>{_t(naziv) if bez_lexintake else "LexIntake"}</b>', _stil('Logo', fontSize=16, leading=20, textColor=boja_teksta_zaglavlja)),
        Paragraph(
            f'Urgentnost: <b>{tekst_urgentnosti(prijem.procena_urgentnosti)}</b>',
            _stil('Urg', fontSize=9, leading=12, textColor=NAVY if svetla else white, alignment=2)
        )
    ]], colWidths=[11*cm, 6*cm])
    tabela_zaglavlje.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), boja_zaglavlja),
        ('PADDING', (0, 0), (-1, -1), 14),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROUNDEDCORNERS', [6, 6, 6, 6]),
    ]))
    elementi.append(tabela_zaglavlje)
    elementi.append(Spacer(1, 0.5*cm))

    elementi.append(Paragraph(_t(prijem.klijent_ime or 'Nepoznat klijent'), stil_naslov))
    elementi.append(Paragraph(
        f'Prijem #{prijem.id} · {datum} · {_t(naziv)}',
        stil_podnaslov
    ))
    elementi.append(HRFlowable(width="100%", thickness=0.5, color=HexColor('#e0d8cc')))

    elementi.append(Paragraph('KONTAKT PODACI', stil_sekcija))

    def polje(oznaka, vrednost, bold=False):
        tekst = f'<font size="8" color="#8a8070"><b>{oznaka.upper()}</b></font><br/>'
        vrednost = _t(vrednost or '—')
        tekst += f'<b><font color="#0f2744">{vrednost}</font></b>' if bold else vrednost
        return Paragraph(tekst, stil_polje)

    tabela_kontakt = Table([
        [polje('Ime i prezime', prijem.klijent_ime), polje('Telefon', prijem.klijent_telefon)],
        [polje('Email', prijem.klijent_email), polje('Oblast prava', prijem.oblast_prava, bold=True)],
    ], colWidths=[8.5*cm, 8.5*cm], hAlign='LEFT')
    tabela_kontakt.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), POZADINA),
        ('PADDING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, IVICA),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elementi.append(tabela_kontakt)

    elementi.append(Paragraph('OPIS SLUČAJA', stil_sekcija))

    for oznaka, vrednost in [
        ('Opis problema', prijem.opis_problema),
        ('Detalji slučaja', prijem.detalji_slucaja),
        ('Dokumenti', prijem.dokumenti_napomena),
    ]:
        if vrednost:
            elementi.append(_kutija(Paragraph(f'<b>{oznaka}</b><br/>{_t(vrednost)}', stil_vrednost)))
            elementi.append(Spacer(1, 0.2*cm))

    elementi.append(Paragraph('AI ANALIZA', stil_sekcija))
    elementi.append(_kutija(
        Paragraph(_t(prijem.ai_analiza or 'Analiza nije dostupna.'), stil_ai),
        pozadina=SVETLO_PLAVA, levo=NAVY
    ))
    elementi.append(Paragraph(
        'Analizu je generisao AI model na osnovu razgovora sa klijentom. Predlog je informativan i treba ga proveriti; nije pravni savet.',
        stil_napomena
    ))
    elementi.append(Spacer(1, 0.3*cm))

    if prijem.preporuceni_koraci:
        elementi.append(_kutija(Paragraph(f'<b>Preporučeni koraci</b><br/>{_t(prijem.preporuceni_koraci)}', stil_vrednost)))

    elementi.append(Spacer(1, 0.3*cm))
    urg_boja = boja_urgentnosti(prijem.procena_urgentnosti)
    elementi.append(Paragraph(
        f'Procena urgentnosti: <font color="#{urg_boja.hexval()[2:]}"><b>{tekst_urgentnosti(prijem.procena_urgentnosti)}</b></font>',
        _stil('Urg2', textColor=SIVA)
    ))

    transkript = _transkript(prijem.razgovor_json)
    if transkript:
        elementi.append(Paragraph('TRANSKRIPT RAZGOVORA', stil_sekcija))
        for uloga, tekst in transkript:
            if uloga == "user":
                elementi.append(Paragraph(f'<b>Klijent:</b> {_t(tekst)}', stil_klijent))
            else:
                elementi.append(Paragraph(f'<b>Asistent:</b> {_t(tekst)}', stil_asistent))

    elementi.append(Spacer(1, 0.5*cm))
    elementi.append(HRFlowable(width="100%", thickness=0.5, color=HexColor('#e0d8cc')))
    elementi.append(Spacer(1, 0.2*cm))
    tabela_podnozje = Table([[
        Paragraph(f'{_t(naziv) if bez_lexintake else "LexIntake"} · Automatski generisan izveštaj · Poverljivo', stil_podnozje),
        Paragraph(f'Prijem #{prijem.id} · {datum}', _stil('Podnozje2', fontSize=9, textColor=SIVA, leading=12, alignment=2))
    ]], colWidths=[10*cm, 7*cm])
    tabela_podnozje.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    elementi.append(tabela_podnozje)

    doc.build(elementi)
    return buffer.getvalue()
