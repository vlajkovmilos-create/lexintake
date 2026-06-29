import resend
from ..config import get_settings

settings = get_settings()
resend.api_key = settings.resend_api_key

def posalji_izvestaj_advokatu(
    advokat_email: str,
    advokat_ime: str,
    klijent_ime: str,
    oblast_prava: str,
    opis_problema: str,
    ai_analiza: str,
    procena_urgentnosti: str,
    preporuceni_koraci: str,
    prijem_id: int
) -> bool:
    
    boja_urgentnosti = {
        "visoka": "#dc2626",
        "srednja": "#d97706",
        "niska": "#16a34a"
    }.get(procena_urgentnosti, "#6b7280")

    html = f"""
    <!DOCTYPE html>
    <html lang="sr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin:0;padding:0;background:#f5f0e8;font-family:Georgia,serif;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f0e8;padding:40px 20px;">
            <tr><td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e0d8cc;">
                    
                    <!-- Zaglavlje -->
                    <tr>
                        <td style="background:#0f2744;padding:28px 36px;">
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td>
                                        <span style="font-family:Georgia,serif;font-size:22px;color:#f5f0e8;font-weight:normal;">LexIntake</span>
                                        <p style="margin:4px 0 0;font-size:13px;color:rgba(245,240,232,0.5);font-family:Arial,sans-serif;">Novi prijem klijenta</p>
                                    </td>
                                    <td align="right">
                                        <span style="background:{boja_urgentnosti};color:#ffffff;font-size:12px;font-family:Arial,sans-serif;padding:5px 14px;border-radius:20px;font-weight:500;">
                                            Urgentnost: {procena_urgentnosti.upper()}
                                        </span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Pozdrav -->
                    <tr>
                        <td style="padding:32px 36px 0;">
                            <p style="font-size:16px;color:#1a1610;margin:0 0 8px;">Poštovani {advokat_ime},</p>
                            <p style="font-size:15px;color:#3d3830;margin:0;font-family:Arial,sans-serif;line-height:1.6;">
                                Novi klijent je završio upitnik. U nastavku se nalazi kompletan izveštaj o prijemu.
                            </p>
                        </td>
                    </tr>

                    <!-- Podaci o klijentu -->
                    <tr>
                        <td style="padding:24px 36px 0;">
                            <p style="font-size:11px;font-weight:bold;text-transform:uppercase;letter-spacing:0.08em;color:#8a8070;font-family:Arial,sans-serif;margin:0 0 12px;">Podaci o klijentu</p>
                            <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9f6f0;border-radius:8px;overflow:hidden;">
                                <tr>
                                    <td style="padding:14px 18px;border-bottom:1px solid #ede7d9;">
                                        <span style="font-size:11px;color:#8a8070;font-family:Arial,sans-serif;">IME I PREZIME</span><br>
                                        <span style="font-size:15px;color:#1a1610;font-weight:normal;">{klijent_ime}</span>
                                    </td>
                                    <td style="padding:14px 18px;border-bottom:1px solid #ede7d9;">
                                        <span style="font-size:11px;color:#8a8070;font-family:Arial,sans-serif;">OBLAST PRAVA</span><br>
                                        <span style="font-size:15px;color:#0f2744;font-weight:bold;font-family:Arial,sans-serif;">{oblast_prava}</span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Opis problema -->
                    <tr>
                        <td style="padding:20px 36px 0;">
                            <p style="font-size:11px;font-weight:bold;text-transform:uppercase;letter-spacing:0.08em;color:#8a8070;font-family:Arial,sans-serif;margin:0 0 10px;">Opis problema</p>
                            <div style="background:#f9f6f0;border-radius:8px;padding:16px 18px;">
                                <p style="font-size:14px;color:#3d3830;margin:0;line-height:1.7;font-family:Arial,sans-serif;">{opis_problema}</p>
                            </div>
                        </td>
                    </tr>

                    <!-- AI analiza -->
                    <tr>
                        <td style="padding:20px 36px 0;">
                            <p style="font-size:11px;font-weight:bold;text-transform:uppercase;letter-spacing:0.08em;color:#8a8070;font-family:Arial,sans-serif;margin:0 0 10px;">AI pravna analiza</p>
                            <div style="background:#eef3f8;border-left:3px solid #0f2744;border-radius:0 8px 8px 0;padding:16px 18px;">
                                <p style="font-size:14px;color:#0f2744;margin:0;line-height:1.7;font-family:Arial,sans-serif;">{ai_analiza}</p>
                            </div>
                        </td>
                    </tr>

                    <!-- Preporučeni koraci -->
                    <tr>
                        <td style="padding:20px 36px 0;">
                            <p style="font-size:11px;font-weight:bold;text-transform:uppercase;letter-spacing:0.08em;color:#8a8070;font-family:Arial,sans-serif;margin:0 0 10px;">Preporučeni koraci</p>
                            <div style="background:#f9f6f0;border-radius:8px;padding:16px 18px;">
                                <p style="font-size:14px;color:#3d3830;margin:0;line-height:1.7;font-family:Arial,sans-serif;">{preporuceni_koraci}</p>
                            </div>
                        </td>
                    </tr>

                    <!-- Dugme -->
                    <tr>
                        <td style="padding:28px 36px;">
                            <table cellpadding="0" cellspacing="0">
                                <tr>
                                    <td style="background:#0f2744;border-radius:6px;">
                                        <a href="#" style="display:inline-block;padding:12px 24px;font-size:14px;color:#f5f0e8;text-decoration:none;font-family:Arial,sans-serif;">
                                            Pogledaj kompletan izveštaj →
                                        </a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="background:#f9f6f0;padding:20px 36px;border-top:1px solid #ede7d9;">
                            <p style="font-size:12px;color:#8a8070;margin:0;font-family:Arial,sans-serif;line-height:1.6;">
                                Ovaj izveštaj je automatski generisan od strane LexIntake sistema.<br>
                                Prijem #{prijem_id} · Svi podaci su poverljivi i enkriptovani.
                            </p>
                        </td>
                    </tr>

                </table>
            </td></tr>
        </table>
    </body>
    </html>
    """

    try:
        resend.Emails.send({
            "from": settings.from_email,
            "to": advokat_email,
            "subject": f"Novi prijem: {klijent_ime} — {oblast_prava}",
            "html": html
        })
        return True
    except Exception as e:
        print(f"Greška pri slanju emaila: {e}")
        return False