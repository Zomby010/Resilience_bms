"""Payslip PDF, drawn with ReportLab like the invoice PDF."""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from billing.pdf import DARK, GREY, RED, _money, _p
from core.models import CompanySettings
from core.templatetags.ui import masked

from .services import payslip_rows


def _logo_bytes(logo):
    # Read through the storage: in the cloud the logo has no local file path.
    with logo.open("rb") as fh:
        return BytesIO(fh.read())


def payslip_pdf(line):
    company = CompanySettings.load()
    run = line.run
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"Payslip {run.period:%B %Y}", author=company.company_name or "")
    ss = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=ss["Normal"], fontSize=10, leading=14)
    small = ParagraphStyle("s", parent=normal, fontSize=8.5, textColor=GREY)
    bold = ParagraphStyle("b", parent=normal, fontName="Helvetica-Bold")
    title = ParagraphStyle("t", parent=ss["Title"], fontSize=22, textColor=RED, alignment=2, spaceAfter=0)

    left = []
    if company.logo:
        try:
            left.append(Image(_logo_bytes(company.logo), width=38 * mm, height=18 * mm, kind="proportional"))
        except Exception:  # a missing or unreadable logo never stops the payslip
            pass
    left.append(_p(company.company_name or "Resilience Security", bold))
    for text in (company.address, company.phone, company.email):
        if text:
            left.append(_p(text, normal))
    right = [Paragraph("PAYSLIP", title), Spacer(1, 4), _p(f"{run.period:%B %Y}", bold)]
    head = Table([[left, right]], colWidths=[100 * mm, 74 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    who = Table([
        [_p("Name", small), _p(line.employee_name, bold), _p("Employee no.", small), _p(line.employee_number, bold)],
        [_p("Role", small), _p(line.role.title(), normal), _p("Pay period", small), _p(f"{run.period:%B %Y}", normal)],
    ], colWidths=[24 * mm, 63 * mm, 30 * mm, 57 * mm])
    who.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))

    earnings, deductions = payslip_rows(line)
    rows = [["Earnings", "KES"]] + [[label, _money(v)] for label, v in earnings] + [["Gross pay", _money(line.gross)]]
    rows += [["Deductions", "KES"]] + [[label, _money(v)] for label, v in deductions]
    rows += [["Total deductions", _money(line.total_deductions)], ["NET PAY", _money(line.net)]]
    d_head = len(earnings) + 2
    table = Table(rows, colWidths=[124 * mm, 50 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, d_head), (-1, d_head), DARK), ("TEXTCOLOR", (0, d_head), (-1, d_head), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTNAME", (0, d_head), (-1, d_head), "Helvetica-Bold"),
        ("FONTNAME", (0, d_head - 1), (-1, d_head - 1), "Helvetica-Bold"),
        ("FONTNAME", (0, -2), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTSIZE", (0, -1), (-1, -1), 12), ("TEXTCOLOR", (0, -1), (-1, -1), RED),
        ("LINEABOVE", (0, -1), (-1, -1), 1, DARK), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    method = line.get_payment_method_display() or "-"
    paid = f"Paid by: {method}" + (f" {masked(line.payment_detail)}" if line.payment_detail else "")
    story = [head, Spacer(1, 8 * mm), who, Spacer(1, 6 * mm), table, Spacer(1, 6 * mm), _p(paid, normal),
             Spacer(1, 10 * mm), _p("CONFIDENTIAL. This payslip is for the named employee only.", small)]
    doc.build(story)
    return buf.getvalue()
