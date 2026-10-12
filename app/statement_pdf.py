"""Render a stored statement snapshot as a PDF."""
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY = colors.HexColor("#14284b")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


def money(cents: int, cur: str) -> str:
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return f"{sign}{whole:,}.{frac:02d} {cur}"


def _table(rows, widths, header=True, right_cols=()):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [("FONTSIZE", (0, 0), (-1, -1), 9), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8cdd6")),
             ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                  ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    for c in right_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


def render(data: dict, content_hash: str) -> bytes:
    cur = data["airline"]["currency"]
    p = data["period"]
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=NAVY, fontSize=18, alignment=0, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=NAVY, fontSize=12, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["Normal"], fontSize=9, leading=12)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.HexColor("#555555"))
    cell = ParagraphStyle("c", parent=body, fontSize=8, leading=10)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"Statement {data['statement_no']}",
                            author="Self Weigh Service", invariant=True)
    s = []
    s.append(Paragraph("Self Weigh Service: Monthly Statement", h1))
    s.append(Paragraph(f"<b>{escape(data['airline']['name'])}</b> ({data['airline']['iata_code']}) &nbsp;|&nbsp; "
                       f"{MONTHS[p['month'] - 1]} {p['year']} &nbsp;|&nbsp; Statement {data['statement_no']}", body))
    s.append(Paragraph(f"Generated {data['generated_at']} &nbsp;|&nbsp; Month boundaries in {p['timezone']} "
                       f"&nbsp;|&nbsp; Collection mode: {data['airline']['collector']}", small))

    sm = data["summary"]
    s.append(Paragraph("Bags weighed", h2))
    s.append(_table([["Measure", "Count"],
                     ["Bags weighed", sm["bags_weighed"]],
                     ["Within allowance (no fee)", sm["bags_within_allowance"]],
                     ["Over allowance (fee applied)", sm["bags_over_allowance"]],
                     ["Rejected (over maximum weight)", sm["bags_rejected"]]],
                    [110 * mm, 40 * mm], right_cols=(1,)))

    st = data["settlement"]
    s.append(Paragraph("Settlement", h2))
    if st["applicable"]:
        rows = [["Item", f"Amount ({cur})"],
                ["Opening balance owed to airline", money(st["opening_balance_cents"], cur)],
                ["+ Fees collected on your behalf", money(st["gross_collected_cents"], cur)],
                ["- Operator service fee", money(-st["service_fees_cents"], cur)],
                ["- Payouts made to you", money(-st["payouts_cents"], cur)],
                ["= Closing balance owed to airline", money(st["closing_balance_cents"], cur)]]
        t = _table(rows, [110 * mm, 40 * mm], right_cols=(1,))
        t.setStyle(TableStyle([("FONTNAME", (0, 5), (-1, 5), "Helvetica-Bold")]))
        s.append(t)
        if data["payments_by_method"]:
            s.append(Spacer(1, 4))
            rows = [["Collected by payment method", "Payments", f"Amount ({cur})"]]
            for m in sorted(data["payments_by_method"]):
                v = data["payments_by_method"][m]
                rows.append([m.capitalize(), v["count"], money(v["cents"], cur)])
            s.append(_table(rows, [80 * mm, 30 * mm, 40 * mm], right_cols=(1, 2)))
    else:
        s.append(Paragraph("This airline collects fees directly, so no money is settled through the operator. "
                           "Counts and waivers are shown for information.", body))

    s.append(Paragraph("Fee waivers", h2))
    s.append(Paragraph(f"{sm['bags_waived']} waiver(s), total {money(sm['fees_waived_cents'], cur)}. "
                       "Waived fees are not collected and are not part of the settlement above.", body))
    if data["waivers"]:
        s.append(Spacer(1, 4))
        rows = [["Date", "Txn", "Flight", f"Waived ({cur})", "Staff", "Reason"]]
        for w in data["waivers"]:
            rows.append([Paragraph(escape(w["date"][:16].replace("T", " ")), cell), w["transaction_id"],
                         escape(w["flight_number"] or "-"), money(w["waived_cents"], cur), w["staff_code"],
                         Paragraph(escape(w["reason"] or ""), cell)])
        s.append(_table(rows, [30 * mm, 12 * mm, 17 * mm, 28 * mm, 17 * mm, 70 * mm], right_cols=(3,)))

    ig = data["integrity"]
    s.append(Paragraph("Record integrity", h2))
    s.append(Paragraph(f"Audit chain checked at generation: <b>{'valid' if ig['audit_chain_valid'] else 'INVALID'}</b> "
                       f"({ig['audit_events']} events). Chain head hash at generation:", body))
    s.append(Paragraph(f"<font face='Courier' size='7'>{ig['audit_head_hash']}</font>", body))
    s.append(Paragraph("Statement content hash (also recorded in your audit log as STATEMENT_GENERATED):", body))
    s.append(Paragraph(f"<font face='Courier' size='7'>{content_hash}</font>", body))
    s.append(Spacer(1, 6))
    s.append(Paragraph("Every figure above is computed from the same records as the accompanying CSV, which lists "
                       "each collection, service fee, payout and waiver. In the CSV, the amount_cents column sums "
                       "to the closing balance minus the opening balance. Statements are final once generated; "
                       "corrections appear as entries on a later statement.", small))
    doc.build(s)
    return buf.getvalue()
