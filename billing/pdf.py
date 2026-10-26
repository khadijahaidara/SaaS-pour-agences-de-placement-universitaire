"""Facture PDF (reportlab) aux couleurs NEURALIS."""
from io import BytesIO

from django.conf import settings
from django.contrib.staticfiles import finders

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

NIGHT = colors.HexColor("#0e1b3d")
RIVER = colors.HexColor("#1f4fb8")
OCHRE = colors.HexColor("#c98a2b")
MUTED = colors.HexColor("#6b7389")
LINE = colors.HexColor("#dfe4ee")


def money(value) -> str:
    return f"{int(value):,}".replace(",", " ") + " FCFA"


def render_invoice(invoice) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    c.setTitle(f"Facture {invoice.number}")
    c.setAuthor(settings.BILLING_ISSUER["name"])
    issuer = settings.BILLING_ISSUER
    agency = invoice.agency
    left, right = 20 * mm, width - 20 * mm

    # Bandeau
    c.setFillColor(NIGHT)
    c.rect(0, height - 42 * mm, width, 42 * mm, stroke=0, fill=1)
    c.setFillColor(OCHRE)
    c.rect(0, height - 43.5 * mm, width, 1.5 * mm, stroke=0, fill=1)
    logo = finders.find("img/neuralis-logo.png")
    if logo:
        c.drawImage(logo, left, height - 32 * mm, 18 * mm, 18 * mm, mask="auto")
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(left + 23 * mm, height - 20 * mm, "NEURALIS Mobility")
    c.setFont("Helvetica", 9)
    c.drawString(left + 23 * mm, height - 26 * mm, issuer["name"] + " · " + issuer["address"])
    c.drawString(left + 23 * mm, height - 31 * mm, issuer["email"] + (" · " + issuer["legal"] if issuer["legal"] else ""))
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(right, height - 21 * mm, "FACTURE")
    c.setFont("Helvetica", 10)
    c.drawRightString(right, height - 28 * mm, invoice.number)

    # Statut
    status_color = {"paid": colors.HexColor("#2f7d4f"), "void": MUTED}.get(invoice.status, OCHRE)
    c.setFillColor(status_color)
    c.roundRect(right - 32 * mm, height - 37 * mm, 32 * mm, 6 * mm, 3 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(right - 16 * mm, height - 35 * mm, invoice.get_status_display().upper())

    # Parties
    y = height - 58 * mm
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8)
    c.drawString(left, y, "FACTURÉ À")
    c.drawString(width / 2, y, "DÉTAILS")
    c.setFillColor(NIGHT)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(left, y - 6 * mm, agency.name[:48])
    c.setFont("Helvetica", 9)
    lines = [agency.address, f"{agency.city}, {agency.country}", agency.email, agency.phone, agency.legal_info]
    yy = y - 11 * mm
    for line in filter(None, lines):
        c.drawString(left, yy, str(line)[:60])
        yy -= 4.6 * mm
    details = [("Émise le", f"{invoice.issued_on:%d/%m/%Y}"), ("À régler avant le", f"{invoice.due_on:%d/%m/%Y}"),
               ("Période", f"{invoice.period_start:%d/%m/%Y} → {invoice.period_end:%d/%m/%Y}"),
               ("Formule", f"{invoice.plan.name} — {invoice.get_cycle_display()}")]
    if invoice.paid_on:
        details.append(("Payée le", f"{invoice.paid_on:%d/%m/%Y} ({invoice.get_payment_method_display()})"))
    yy = y - 6 * mm
    for label, value in details:
        c.setFillColor(MUTED)
        c.drawString(width / 2, yy, label)
        c.setFillColor(NIGHT)
        c.drawRightString(right, yy, value)
        yy -= 5 * mm

    # Tableau
    y = height - 112 * mm
    c.setFillColor(colors.HexColor("#f3f5f9"))
    c.rect(left, y - 2 * mm, right - left, 9 * mm, stroke=0, fill=1)
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(left + 3 * mm, y + 1.5 * mm, "DÉSIGNATION")
    c.drawRightString(right - 3 * mm, y + 1.5 * mm, "MONTANT")
    c.setFillColor(NIGHT)
    c.setFont("Helvetica", 10)
    y -= 11 * mm
    c.drawString(left + 3 * mm, y, invoice.label[:85])
    c.drawRightString(right - 3 * mm, y, money(invoice.amount))
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    limits = [f"{invoice.plan.max_active_dossiers or 'Illimité'} dossiers en cours",
              f"{invoice.plan.max_staff or 'Illimité'} membres d'équipe"]
    c.drawString(left + 3 * mm, y - 5 * mm, " · ".join(limits))
    c.setStrokeColor(LINE)
    c.line(left, y - 10 * mm, right, y - 10 * mm)

    y -= 22 * mm
    for label, value, bold in [("Sous-total", money(invoice.amount), False), ("TVA", "Non applicable", False),
                               ("Total à payer", money(invoice.amount), True)]:
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 12 if bold else 9)
        c.setFillColor(RIVER if bold else MUTED)
        c.drawString(width / 2 + 10 * mm, y, label)
        c.setFillColor(NIGHT)
        c.drawRightString(right - 3 * mm, y, value)
        y -= 7 * mm

    # Paiement
    y -= 8 * mm
    c.setFillColor(colors.HexColor("#eef3fc"))
    c.roundRect(left, y - 16 * mm, right - left, 20 * mm, 3 * mm, stroke=0, fill=1)
    c.setFillColor(NIGHT)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left + 5 * mm, y - 2 * mm, "Modalités de paiement")
    c.setFont("Helvetica", 9)
    c.drawString(left + 5 * mm, y - 8 * mm, issuer["payment"][:110])
    c.drawString(left + 5 * mm, y - 13 * mm, f"Merci d'indiquer la référence {invoice.number} lors de votre paiement.")
    if invoice.notes:
        c.setFillColor(MUTED)
        c.drawString(left, y - 24 * mm, invoice.notes[:110])

    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.5)
    c.drawCentredString(width / 2, 12 * mm, f"{issuer['name']} — NEURALIS Mobility, le suivi des études à l'étranger. "
                                            f"Document généré le {invoice.created_at:%d/%m/%Y}.")
    c.showPage()
    c.save()
    return buf.getvalue()
