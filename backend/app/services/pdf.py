import io
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = '/usr/share/fonts/truetype/dejavu/'

pdfmetrics.registerFont(TTFont('DejaVu', FONT_DIR + 'DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DejaVu-Bold', FONT_DIR + 'DejaVuSans-Bold.ttf'))
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from ..models import Prijem, Advokat

NAVY = HexColor('#0f2744')
KREM = HexColor('#f5f0e8')
ZLATO = HexColor('#c9a84c')
SIVA = HexColor('#8a8070')
SVETLO_PLAVA = HexColor('#eef3f8')
POZADINA = HexColor('#fafaf8')

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

def generisi_pdf(prijem: Prijem, advokat: Advokat) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    stilovi = getSampleStyleSheet()
    elementi = []

    stil_naslov = ParagraphStyle(
        'Naslov',
        fontName='DejaVu-Bold',
        fontSize=20,
        textColor=NAVY,
        spaceAfter=4,
        leading=24
    )

    stil_podnaslov = ParagraphStyle(
        'Podnaslov',
        fontName='DejaVu',
        fontSize=10,
        textColor=SIVA,
        spaceAfter=16
    )

    stil_sekcija = ParagraphStyle(
        'Sekcija',
        fontName='DejaVu-Bold',
        fontSize=9,
        textColor=SIVA,
        spaceBefore=16,
        spaceAfter=8,
        textTransform='uppercase',
        letterSpacing=1
    )

    stil_oznaka = ParagraphStyle(
        'Oznaka',
        fontName='DejaVu-Bold',
        fontSize=9,
        textColor=SIVA,
        spaceAfter=2
    )

    stil_vrednost = ParagraphStyle(
        'Vrednost',
        fontName='DejaVu',
        fontSize=11,
        textColor=HexColor('#1a1610'),
        spaceAfter=4,
        leading=16
    )

    stil_ai = ParagraphStyle(
        'AI',
        fontName='DejaVu',
        fontSize=11,
        textColor=NAVY,
        leading=17,
        leftIndent=12,
        spaceAfter=8
    )

    datum = prijem.datum_prijema.strftime("%d.%m.%Y. u %H:%M")

    zaglavlje_podaci = [
        [
            Paragraph('<font color="#f5f0e8" size="16"><b>LexIntake</b></font>', stilovi['Normal']),
            Paragraph(
                f'<font color="white" size="9">Urgentnost: <b>{tekst_urgentnosti(prijem.procena_urgentnosti)}</b></font>',
                ParagraphStyle('urg', fontName='Helvetica', fontSize=9, textColor=white, alignment=2)
            )
        ]
    ]

    tabela_zaglavlje = Table(zaglavlje_podaci, colWidths=[12*cm, 5*cm])
    tabela_zaglavlje.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), NAVY),
        ('PADDING', (0, 0), (-1, -1), 16),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('ROUNDEDCORNERS', [6, 6, 6, 6]),
    ]))
    elementi.append(tabela_zaglavlje)
    elementi.append(Spacer(1, 0.5*cm))

    elementi.append(Paragraph(prijem.klijent_ime or 'Nepoznat klijent', stil_naslov))
    elementi.append(Paragraph(
        f'Prijem #{prijem.id} · {datum} · {advokat.naziv_kancelarije or advokat.ime}',
        stil_podnaslov
    ))
    elementi.append(HRFlowable(width="100%", thickness=0.5, color=HexColor('#e0d8cc')))

    elementi.append(Paragraph('Kontakt podaci', stil_sekcija))

    kontakt_podaci = [
        [
            _polje_tabela('Ime i prezime', prijem.klijent_ime or '—'),
            _polje_tabela('Telefon', prijem.klijent_telefon or '—'),
        ],
        [
            _polje_tabela('Email', prijem.klijent_email or '—'),
            _polje_tabela('Oblast prava', prijem.oblast_prava or '—', bold=True),
        ]
    ]

    tabela_kontakt = Table(kontakt_podaci, colWidths=[8.5*cm, 8.5*cm], hAlign='LEFT')
    tabela_kontakt.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), POZADINA),
        ('PADDING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#ede7d9')),
        ('ROUNDEDCORNERS', [4, 4, 4, 4]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elementi.append(tabela_kontakt)

    elementi.append(Paragraph('Opis slučaja', stil_sekcija))

    for oznaka, vrednost in [
        ('Opis problema', prijem.opis_problema),
        ('Detalji slučaja', prijem.detalji_slucaja),
        ('Dokumenti', prijem.dokumenti_napomena),
    ]:
        if vrednost:
            podaci = [[
                Paragraph(f'<b>{oznaka}</b>', stil_oznaka),
            ], [
                Paragraph(vrednost, stil_vrednost),
            ]]
            t = Table([[Paragraph(f'<b>{oznaka}</b><br/>{vrednost}', stil_vrednost)]], colWidths=[17*cm])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), POZADINA),
                ('PADDING', (0, 0), (-1, -1), 10),
                ('BOX', (0, 0), (-1, -1), 0.5, HexColor('#ede7d9')),
                ('ROUNDEDCORNERS', [4, 4, 4, 4]),
            ]))
            elementi.append(t)
            elementi.append(Spacer(1, 0.2*cm))

    elementi.append(Paragraph('AI pravna analiza', stil_sekcija))

    ai_tabela = Table(
        [[Paragraph(prijem.ai_analiza or 'Analiza nije dostupna.', stil_ai)]],
        colWidths=[17*cm]
    )
    ai_tabela.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), SVETLO_PLAVA),
        ('PADDING', (0, 0), (-1, -1), 14),
        ('LINEBEFORE', (0, 0), (0, -1), 3, NAVY),
        ('ROUNDEDCORNERS', [0, 4, 4, 0]),
    ]))
    elementi.append(ai_tabela)
    elementi.append(Spacer(1, 0.3*cm))

    if prijem.preporuceni_koraci:
        t = Table(
            [[Paragraph(f'<b>Preporučeni koraci</b><br/>{prijem.preporuceni_koraci}', stil_vrednost)]],
            colWidths=[17*cm]
        )
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), POZADINA),
            ('PADDING', (0, 0), (-1, -1), 10),
            ('BOX', (0, 0), (-1, -1), 0.5, HexColor('#ede7d9')),
            ('ROUNDEDCORNERS', [4, 4, 4, 4]),
        ]))
        elementi.append(t)

    elementi.append(Spacer(1, 0.3*cm))
    urg_boja = boja_urgentnosti(prijem.procena_urgentnosti)
    urg_tekst = tekst_urgentnosti(prijem.procena_urgentnosti)
    elementi.append(Paragraph(
        f'Procena urgentnosti: <font color="#{urg_boja.hexval()[2:]}"><b>{urg_tekst}</b></font>',
        ParagraphStyle('urg2', fontName='Helvetica', fontSize=11, textColor=SIVA)
    ))

    elementi.append(Spacer(1, 0.5*cm))
    elementi.append(HRFlowable(width="100%", thickness=0.5, color=HexColor('#e0d8cc')))
    elementi.append(Spacer(1, 0.2*cm))
    podnozje_podaci = [[
        Paragraph('LexIntake · Automatski generisan izveštaj', ParagraphStyle('pf', fontName='Helvetica', fontSize=9, textColor=SIVA)),
        Paragraph(f'Prijem #{prijem.id} · {datum}', ParagraphStyle('pf2', fontName='Helvetica', fontSize=9, textColor=SIVA, alignment=2))
    ]]
    tabela_podnozje = Table(podnozje_podaci, colWidths=[10*cm, 7*cm])
    tabela_podnozje.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    elementi.append(tabela_podnozje)

    doc.build(elementi)
    return buffer.getvalue()


def _polje_tabela(oznaka: str, vrednost: str, bold: bool = False) -> Paragraph:
    stil = ParagraphStyle(
        'Polje',
        fontName='Helvetica',
        fontSize=11,
        textColor=HexColor('#1a1610'),
        leading=16
    )
    tekst = f'<font size="9" color="#8a8070"><b>{oznaka.upper()}</b></font><br/>'
    if bold:
        tekst += f'<b><font color="#0f2744">{vrednost}</font></b>'
    else:
        tekst += vrednost
    return Paragraph(tekst, stil)