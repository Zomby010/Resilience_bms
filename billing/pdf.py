"""Invoice PDF, drawn with ReportLab (approved at Gate 7). Pure Python, nothing to install on Windows."""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from core.models import CompanySettings

RED = colors.HexColor("#d10012")
DARK = colors.HexColor("#140102")
GREY = colors.HexColor("#64748b")


def _p(text, style):
    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)


def _money(value):
    return f"{value:,.2f}"


def invoice_pdf(invoice):
    company = CompanySettings.load()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=str(invoice), author=company.company_name or "")
    ss = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=ss["Normal"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=normal, fontSize=8.5, textColor=GREY)
    title = ParagraphStyle("t", parent=ss["Title"], fontSize=22, textColor=RED, alignment=2, spaceAfter=0)
    bold = ParagraphStyle("b", parent=normal, fontName="Helvetica-Bold")
    story = []

    left = []
    if company.logo:
        try:
            left.append(Image(company.logo.path, width=38 * mm, height=18 * mm, kind="proportional"))
        except Exception:  # a missing or unreadable logo never stops the invoice
            pass
    left.append(_p(company.company_name or "Resilience Security", bold))
    for line in (company.address, company.phone, company.email, f"KRA PIN: {company.kra_pin}" if company.kra_pin else ""):
        if line:
            left.append(_p(line, normal))
    right = [Paragraph("INVOICE", title), Spacer(1, 4),
             _p(f"Number: {invoice.number or 'DRAFT'}", bold),
             _p(f"Date: {invoice.invoice_date:%d %B %Y}", normal),
             _p(f"Due: {invoice.due_date:%d %B %Y}", normal)]
    head = Table([[left, right]], colWidths=[95 * mm, 79 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [head, Spacer(1, 8 * mm)]

    name = invoice.bill_to_name or invoice.client.name
    address = invoice.bill_to_address or "\n".join(x for x in (invoice.client.physical_address, invoice.client.postal_address) if x)
    pin = invoice.bill_to_kra_pin or invoice.client.kra_pin
    bill = [_p("BILL TO", small), _p(name, bold)]
    if address:
        bill.append(_p(address, normal))
    if pin:
        bill.append(_p(f"KRA PIN: {pin}", normal))
    story += bill + [Spacer(1, 6 * mm)]

    rows = [["Description", "Qty", "Unit price (KES)", "Amount (KES)"]]
    for line in invoice.lines.all():
        rows.append([_p(line.description, normal), f"{line.quantity.normalize():f}", _money(line.unit_price), _money(line.amount)])
    rows.append(["", "", "Subtotal", _money(invoice.subtotal)])
    if invoice.vat_enabled:
        rows.append(["", "", f"VAT {invoice.vat_rate.normalize():f}%", _money(invoice.vat_amount)])
    rows.append(["", "", "TOTAL", _money(invoice.total)])
    if invoice.amount_paid:
        rows.append(["", "", "Paid", _money(invoice.amount_paid)])
        rows.append(["", "", "Balance due", _money(invoice.balance)])
    n_tot = len(rows) - 1 - invoice.lines.count()
    table = Table(rows, colWidths=[92 * mm, 18 * mm, 32 * mm, 32 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1 - n_tot), 0.4, colors.HexColor("#e2e8f0")),
        ("FONTNAME", (2, -n_tot), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [table, Spacer(1, 8 * mm)]

    if invoice.payment_instructions or company.payment_instructions:
        story += [_p("HOW TO PAY", small), _p(invoice.payment_instructions or company.payment_instructions, normal), Spacer(1, 4 * mm)]
    if invoice.notes:
        story += [_p("NOTES", small), _p(invoice.notes, normal)]
    if invoice.status == invoice.Status.CANCELLED:
        story += [Spacer(1, 6 * mm), Paragraph("CANCELLED", title)]
    doc.build(story)
    return buf.getvalue()
