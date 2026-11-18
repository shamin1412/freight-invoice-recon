"""Render invoices in six carrier-specific layouts.

RDGL  PDF   classic LTL freight bill (boxed header, commodity grid, gross/discount/net)
PXLT  TXT   fixed-width dot-matrix style freight bill printout
BWTR  PDF   modern invoice with accessorial codes, weight in LB and KG
IHLG  PDF   truckload invoice referencing a load / rate confirmation
CCCO  TXT   invoice pasted into an email body
SMFB  TXT   ANSI X12 EDI 210 (Motor Carrier Freight Details and Invoice)

Some PDFs are rasterized with noise and skew to imitate scanned paper.
"""
from __future__ import annotations

import datetime as dt
import io
import random
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from synth import reference as R

FORMATS = {"RDGL": "pdf", "PXLT": "txt", "BWTR": "pdf", "IHLG": "pdf", "CCCO": "txt", "SMFB": "txt"}


def money(x):
    return f"{x:,.2f}"


def addr_lines(s):
    sh = s["shipper"]
    return sh, {"name": s["consignee"], "city": s["dest_city"], "state": s["dest_state"], "zip": s["dest_zip"]}


def street(rng):
    return f"{rng.randint(100, 9899)} {rng.choice(R.STREETS)}"


def notes_for(rec):
    kinds = {c.split(":")[0] for c in rec["conds"]}
    out = []
    if rec.get("kind") == "DUP_INVOICE":
        out.append(rec["_rng"].choice(["SECOND NOTICE - PAST DUE", "COPY - PLEASE REMIT", "STATEMENT REPRINT"]))
    if rec.get("kind") == "DUP_SHIPMENT":
        out.append("REBILL - corrected invoice")
    if "CLASS_WRONG" in kinds:
        out.append("Reclassed per carrier inspection")
    if "WEIGHT_INFLATED" in kinds and rec["_rng"].random() < 0.5:
        out.append("Weight corrected per carrier scale")
    return out


# ------------------------------------------------------------------ RDGL (PDF)
def rdgl(rec, path):
    s, b, rng = rec["shipment"], rec["billed"], rec["_rng"]
    sh, cn = addr_lines(s)
    fd = lambda d: dt.date.fromisoformat(d).strftime("%m/%d/%Y") if isinstance(d, str) else d.strftime("%m/%d/%Y")
    c = canvas.Canvas(str(path), pagesize=letter)
    W, H = letter
    c.setFont("Helvetica-Bold", 18); c.drawString(40, H - 50, "RIDGELINE")
    c.setFont("Helvetica", 9); c.drawString(40, H - 63, "FREIGHT LINES, INC.  |  SCAC: RDGL  |  MC-418829")
    c.drawString(40, H - 75, f"Remit to: {R.CARRIERS['RDGL']['remit']}")
    c.drawString(40, H - 87, f"Billing inquiries {R.CARRIERS['RDGL']['phone']}")
    c.setFont("Helvetica-Bold", 14); c.drawRightString(W - 40, H - 50, "FREIGHT BILL")
    c.rect(W - 230, H - 125, 190, 62)
    c.setFont("Helvetica", 8)
    rows = [("PRO NUMBER", s["pro_number"]), ("BILL DATE", fd(rec["invoice_date"])), ("PICKUP DATE", fd(s["ship_date"])),
            ("TERMS", "PREPAID")]
    for i, (k, v) in enumerate(rows):
        c.drawString(W - 225, H - 77 - i * 13, k); c.setFont("Helvetica-Bold", 9)
        c.drawRightString(W - 45, H - 77 - i * 13, v); c.setFont("Helvetica", 8)
    y = H - 150
    for x, title, p, a in [(40, "SHIPPER", sh, sh["addr"]), (300, "CONSIGNEE", cn, street(rng))]:
        c.setFont("Helvetica-Bold", 8); c.drawString(x, y, title); c.setFont("Helvetica", 9)
        c.drawString(x, y - 12, p["name"]); c.drawString(x, y - 24, a)
        c.drawString(x, y - 36, f"{p['city'].upper()}, {p['state']} {p['zip']}")
    c.setFont("Helvetica", 8)
    c.drawString(40, y - 56, f"BILL TO: {R.SHIPPER} - Freight Payables, 200 W Monroe St Ste 1800, Chicago IL 60606")
    c.drawString(40, y - 68, f"SHIPPER BOL# {s['bol_number']}     CUST REF/PO# {s['po_number']}")
    y -= 95
    c.line(40, y + 10, W - 40, y + 10)
    hdr = ["H/U", "PCS", "DESCRIPTION", "NMFC", "CLASS", "WEIGHT", "RATE", "CHARGES"]
    xs = [40, 70, 100, 330, 385, 425, 480, W - 40]
    c.setFont("Helvetica-Bold", 7)
    for h, x in zip(hdr, xs):
        (c.drawRightString if h == "CHARGES" else c.drawString)(x, y, h)
    c.setFont("Helvetica", 8); y -= 14
    c.drawString(40, y, str(s["handling_units"])); c.drawString(70, y, str(s["pieces"]))
    c.drawString(100, y, s["commodity"][:42]); c.drawString(330, y, s["nmfc"]); c.drawString(385, y, b["billed_class"])
    c.drawString(425, y, f"{b['billed_weight']:,.0f}"); c.drawString(480, y, f"{b['cwt_rate']:.2f}")
    c.drawRightString(W - 40, y, money(b["gross"]))
    y -= 13
    c.drawString(100, y, f"DISCOUNT {b['discount_pct']:.1f}%"); c.drawRightString(W - 40, y, "-" + money(b["discount"]))
    if b.get("min_applied"):
        y -= 13; c.drawString(100, y, "ABSOLUTE MINIMUM CHARGE APPLIES"); c.drawRightString(W - 40, y, money(b["net_linehaul"]))
    y -= 13
    c.drawString(100, y, f"FUEL SURCHARGE {b['fsc_pct']:.2f}%"); c.drawRightString(W - 40, y, money(b["fsc"]))
    for l in b["accessorials"]:
        y -= 13; c.drawString(100, y, R.ACC_WORDING["RDGL"][l["code"]]); c.drawRightString(W - 40, y, money(l["amount"]))
    y -= 8; c.line(40, y, W - 40, y); y -= 16
    c.setFont("Helvetica-Bold", 11); c.drawString(330, y, "TOTAL CHARGES  USD"); c.drawRightString(W - 40, y, money(b["total"]))
    y -= 30; c.setFont("Helvetica", 7)
    for n in notes_for(rec):
        c.setFont("Helvetica-Bold", 10); c.drawString(40, y, n); y -= 14
    c.setFont("Helvetica", 6.5)
    for t in ["Subject to the rules, rates and charges of RDGL 100 Rules Tariff in effect on date of shipment.",
              "Payment due 30 days from bill date. Please reference PRO number on remittance.",
              "Claims for loss or damage must be filed in writing within 9 months of delivery (49 U.S.C. 14706)."]:
        c.drawString(40, y, t); y -= 9
    c.save()


# ------------------------------------------------------------------ PXLT (TXT, fixed width)
def pxlt(rec, path):
    s, b, rng = rec["shipment"], rec["billed"], rec["_rng"]
    fd = lambda d: (dt.date.fromisoformat(d) if isinstance(d, str) else d).strftime("%d%b%y").upper()
    sh, cn = addr_lines(s)
    wt = f"{b['billed_weight']:,.0f}#" if rng.random() < 0.6 else f"{b['billed_weight']:.0f} LBS"
    L = []
    L.append("PRAIRIE EXPRESS LTL".ljust(48) + "FREIGHT BILL / INVOICE")
    L.append("DEPT 4410  PO BOX 9187  DES MOINES IA 50306".ljust(48) + f"INVOICE NO: {rec['invoice_number']}")
    L.append(f"PH {R.CARRIERS['PXLT']['phone']}".ljust(48) + f"INV DATE  : {fd(rec['invoice_date'])}")
    L.append("".ljust(48) + f"PRO NO    : {s['pro_number']}")
    L.append("=" * 78)
    L.append(f"SHIPPER : {sh['name'][:34]:<34}  CONSIGNEE: {cn['name'][:30]}")
    L.append(f"          {sh['addr']:<34}             {street(rng)}")
    L.append(f"          {sh['city'].upper()+' '+sh['state']+' '+sh['zip']:<34}             {cn['city'].upper()} {cn['state']} {cn['zip']}")
    L.append("-" * 78)
    L.append(f"P/U DATE {fd(s['ship_date'])}   BOL {s['bol_number']}   PO {s['po_number']}   TERMS PPD")
    L.append("-" * 78)
    L.append(f"{'PCS':>4} {'HU':>3}  {'DESCRIPTION':<34} {'CL':>5} {'WEIGHT':>10} {'RATE':>8} {'AMOUNT':>10}")
    L.append(f"{s['pieces']:>4} {s['handling_units']:>3}  {s['commodity'][:34]:<34} {b['billed_class']:>5} {wt:>10} {b['cwt_rate']:>8.2f} {money(b['gross']):>10}")
    L.append(f"{'':>10}NMFC {s['nmfc']}")
    L.append(f"{'':>10}{'LESS DISC ' + format(b['discount_pct'], '.1f') + ' PCT':<52}{'-' + money(b['discount']):>16}")
    if b.get("min_applied"):
        L.append(f"{'':>10}{'MIN CHG APPLIED':<52}{money(b['net_linehaul']):>16}")
    L.append(f"{'':>10}{'FUEL SURCH ' + format(b['fsc_pct'], '.2f') + '%':<52}{money(b['fsc']):>16}")
    for l in b["accessorials"]:
        L.append(f"{'':>10}{R.ACC_WORDING['PXLT'][l['code']]:<52}{money(l['amount']):>16}")
    L.append(" " * 62 + "-" * 16)
    L.append(f"{'':>10}{'TOTAL DUE':<52}{money(b['total']):>16}")
    L.append("=" * 78)
    for n in notes_for(rec):
        L.append(f"*** {n} ***")
    L.append("REMIT WITH PRO NO. NET 30. SUBJECT TO PXLT 500 RULES TARIFF.")
    path.write_text("\n".join(L) + "\n")


# ------------------------------------------------------------------ BWTR (PDF, modern)
def bwtr(rec, path):
    s, b, rng = rec["shipment"], rec["billed"], rec["_rng"]
    fd = lambda d: d if isinstance(d, str) else d.isoformat()
    sh, cn = addr_lines(s)
    c = canvas.Canvas(str(path), pagesize=letter)
    W, H = letter
    c.setFillColorRGB(0.06, 0.29, 0.55); c.rect(0, H - 70, W, 70, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1); c.setFont("Helvetica-Bold", 20); c.drawString(40, H - 42, "bluewater")
    c.setFont("Helvetica", 9); c.drawString(40, H - 57, "Bluewater Transport Co. - LTL & Regional Freight")
    c.setFont("Helvetica-Bold", 16); c.drawRightString(W - 40, H - 42, "INVOICE")
    c.setFillColorRGB(0, 0, 0); c.setFont("Helvetica", 9)
    y = H - 95
    meta = [("Invoice #", rec["invoice_number"]), ("Invoice date", fd(rec["invoice_date"])), ("PRO", s["pro_number"]),
            ("Ship date", fd(s["ship_date"])), ("Delivered", fd(s["delivery_date"])), ("Your BOL", s["bol_number"]),
            ("Your ref", s["po_number"])]
    for i, (k, v) in enumerate(meta):
        c.drawString(360, y - i * 12, k); c.drawRightString(W - 40, y - i * 12, v)
    c.setFont("Helvetica-Bold", 9); c.drawString(40, y, "Bill to"); c.setFont("Helvetica", 9)
    c.drawString(40, y - 12, R.SHIPPER); c.drawString(40, y - 24, "Attn: Freight Payables"); c.drawString(40, y - 36, "200 W Monroe St Ste 1800, Chicago IL 60606")
    y -= 100
    c.setFont("Helvetica-Bold", 9); c.drawString(40, y, "Origin"); c.drawString(300, y, "Destination"); c.setFont("Helvetica", 9)
    c.drawString(40, y - 12, sh["name"]); c.drawString(40, y - 24, f"{sh['city']}, {sh['state']} {sh['zip']}")
    c.drawString(300, y - 12, cn["name"]); c.drawString(300, y - 24, f"{cn['city']}, {cn['state']} {cn['zip']}")
    y -= 50
    kg = b["billed_weight"] * 0.45359237
    c.setFillColorRGB(0.92, 0.95, 0.98); c.rect(40, y - 4, W - 80, 16, fill=1, stroke=0); c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 8)
    for x, h in [(44, "Code"), (90, "Description"), (330, "Class"), (370, "Weight"), (470, "Rate")]:
        c.drawString(x, y, h)
    c.drawRightString(W - 44, y, "Amount")
    c.setFont("Helvetica", 8)
    y -= 16
    c.drawString(44, y, "LH"); c.drawString(90, y, f"{s['commodity'][:36]} ({s['pieces']} pcs / {s['handling_units']} plt)")
    c.drawString(330, y, b["billed_class"]); c.drawString(370, y, f"{b['billed_weight']:,.0f} LB ({kg:,.0f} KG)")
    c.drawString(470, y, f"${b['cwt_rate']:.2f}/cwt"); c.drawRightString(W - 44, y, money(b["gross"]))
    y -= 13; c.drawString(44, y, "DSC"); c.drawString(90, y, f"Contract discount ({b['discount_pct']:.1f}%)"); c.drawRightString(W - 44, y, f"({money(b['discount'])})")
    if b.get("min_applied"):
        y -= 13; c.drawString(44, y, "MIN"); c.drawString(90, y, "Adjusted to minimum charge"); c.drawRightString(W - 44, y, money(b["net_linehaul"]))
    y -= 13; c.drawString(44, y, "FSC"); c.drawString(90, y, f"Fuel surcharge {b['fsc_pct']:.2f}% (DOE ${b['doe_price']:.3f})" if rng.random() < 0.5 else f"Fuel surcharge {b['fsc_pct']:.2f}%")
    c.drawRightString(W - 44, y, money(b["fsc"]))
    for l in b["accessorials"]:
        code, desc = R.ACC_WORDING["BWTR"][l["code"]].split(None, 1)
        y -= 13; c.drawString(44, y, code); c.drawString(90, y, desc); c.drawRightString(W - 44, y, money(l["amount"]))
    y -= 10; c.line(330, y, W - 40, y); y -= 16
    c.setFont("Helvetica-Bold", 12); c.drawString(330, y, "Amount due (USD)"); c.drawRightString(W - 44, y, "$" + money(b["total"]))
    y -= 30
    for n in notes_for(rec):
        c.setFillColorRGB(0.7, 0, 0); c.setFont("Helvetica-Bold", 10); c.drawString(40, y, n); y -= 14
    c.setFillColorRGB(0.3, 0.3, 0.3); c.setFont("Helvetica", 7)
    c.drawString(40, 60, f"Remit: {R.CARRIERS['BWTR']['remit']}  ·  ACH details on request  ·  Terms: Net 30  ·  Questions: {R.CARRIERS['BWTR']['phone']}")
    c.save()


# ------------------------------------------------------------------ IHLG (PDF, truckload)
def ihlg(rec, path):
    s, b, rng = rec["shipment"], rec["billed"], rec["_rng"]
    fd = lambda d: (dt.date.fromisoformat(d) if isinstance(d, str) else d).strftime("%b %d, %Y")
    sh, cn = addr_lines(s)
    c = canvas.Canvas(str(path), pagesize=letter)
    W, H = letter
    c.setFont("Times-Bold", 22); c.drawString(40, H - 55, "IRONHORSE LOGISTICS LLC")
    c.setFont("Times-Roman", 10); c.drawString(40, H - 70, f"{R.CARRIERS['IHLG']['remit']}  ·  {R.CARRIERS['IHLG']['phone']}  ·  USDOT 3318842")
    c.line(40, H - 80, W - 40, H - 80)
    c.setFont("Times-Bold", 13); c.drawString(40, H - 102, f"Invoice {rec['invoice_number']}")
    c.setFont("Times-Roman", 10)
    c.drawString(40, H - 118, f"Date: {fd(rec['invoice_date'])}     Load #: {s['pro_number']}     Customer: LARKSPUR HOME GOODS")
    c.drawString(40, H - 132, f"Shipper BOL: {s['bol_number']}     PO: {s['po_number']}     Equipment: 53' Dry Van")
    y = H - 165
    c.setFont("Times-Bold", 10); c.drawString(40, y, "Pick Up"); c.drawString(300, y, "Delivery")
    c.setFont("Times-Roman", 10)
    c.drawString(40, y - 13, sh["name"]); c.drawString(40, y - 26, f"{sh['addr']}, {sh['city']}, {sh['state']} {sh['zip']}")
    c.drawString(40, y - 39, fd(s["ship_date"]))
    c.drawString(300, y - 13, cn["name"][:40]); c.drawString(300, y - 26, f"{cn['city']}, {cn['state']} {cn['zip']}")
    din = dt.datetime.fromisoformat(s["dock_in"]); dout = dt.datetime.fromisoformat(s["dock_out"])
    c.drawString(300, y - 39, f"{fd(s['delivery_date'])}  In {din:%H:%M} / Out {dout:%H:%M}")
    if s["stops"] > 1:
        c.drawString(300, y - 52, f"+ {s['stops'] - 1} additional stop(s) en route")
    y -= 80
    c.drawString(40, y, f"Commodity: {s['commodity']}   Weight: {b['billed_weight']:,.0f} lbs   Pieces: {s['pieces']}")
    y -= 25
    c.setFont("Times-Bold", 10); c.drawString(40, y, "Description"); c.drawString(330, y, "Qty"); c.drawString(390, y, "Rate"); c.drawRightString(W - 40, y, "Amount")
    c.line(40, y - 4, W - 40, y - 4); c.setFont("Times-Roman", 10); y -= 18
    c.drawString(40, y, f"Line Haul  {sh['city']}, {sh['state']} to {cn['city']}, {cn['state']}"); c.drawString(330, y, "1")
    c.drawString(390, y, money(b["linehaul"])); c.drawRightString(W - 40, y, money(b["linehaul"]))
    y -= 15; c.drawString(40, y, "Fuel Surcharge"); c.drawString(330, y, f"{b['miles']} mi"); c.drawString(390, y, f"${b['fsc_per_mile']:.2f}/mi")
    c.drawRightString(W - 40, y, money(b["fsc"]))
    for l in b["accessorials"]:
        y -= 15
        name = R.ACC_WORDING["IHLG"][l["code"]]
        if l["code"] == "DET":
            c.drawString(40, y, f"{name} ({l['qty']:g} hrs)"); c.drawString(330, y, f"{l['qty']:g}"); c.drawString(390, y, f"${l['rate']:.2f}/hr")
        else:
            c.drawString(40, y, name); c.drawString(330, y, f"{l['qty']:g}"); c.drawString(390, y, money(l["rate"]))
        c.drawRightString(W - 40, y, money(l["amount"]))
    y -= 10; c.line(330, y, W - 40, y); y -= 18
    c.setFont("Times-Bold", 12); c.drawString(330, y, "Balance Due"); c.drawRightString(W - 40, y, "$" + money(b["total"]))
    y -= 30
    for n in notes_for(rec):
        c.setFont("Times-Bold", 11); c.drawString(40, y, n); y -= 15
    c.setFont("Times-Italic", 8)
    c.drawString(40, 70, "Thank you for your business. Rates per signed rate confirmation. Quick pay available at 2% - contact AR.")
    c.save()


# ------------------------------------------------------------------ CCCO (TXT, email)
def ccco(rec, path):
    s, b, rng = rec["shipment"], rec["billed"], rec["_rng"]
    fd = lambda d: (dt.date.fromisoformat(d) if isinstance(d, str) else d)
    fmt = lambda d: f"{fd(d).month}/{fd(d).day}/{fd(d):%y}"
    sh, cn = addr_lines(s)
    greet = rng.choice(["Hi team,", "Good morning,", "Hello Larkspur AP,", "Hi,"])
    subj = f"Invoice {rec['invoice_number']} - Load {s['pro_number']} - {sh['city']} to {cn['city']}"
    if rec.get("kind") == "DUP_INVOICE":
        subj = "RE: " + subj + " (2nd request)"
    din = dt.datetime.fromisoformat(s["dock_in"]); dout = dt.datetime.fromisoformat(s["dock_out"])
    L = [f"From: billing@coldchaincarriers.example", "To: freightpayables@larkspurhome.example", f"Subject: {subj}",
         f"Date: {fmt(rec['invoice_date'])}", "", greet, ""]
    if rec.get("kind") == "DUP_INVOICE":
        L += ["Following up on the invoice below, we have not received payment yet. Please advise.", ""]
    L += [f"Please find invoice details for the load below. PDF copy to follow from our system.", "",
          f"Invoice #: {rec['invoice_number']}", f"Load/PRO: {s['pro_number']}", f"Your BOL: {s['bol_number']}  /  PO {s['po_number']}",
          f"Picked up {fmt(s['ship_date'])} at {sh['name']}, {sh['city']} {sh['state']} {sh['zip']}",
          f"Delivered {fmt(s['delivery_date'])} to {cn['name']}, {cn['city']} {cn['state']} {cn['zip']}",
          f"  (checked in {din:%H%M}, out {dout:%H%M})",
          f"Equipment: 53' reefer, set point {rng.choice([50, 55, 60])}F continuous",
          f"Product: {s['commodity']}, {s['pieces']} pallets, {b['billed_weight']:,.0f} lbs", "", "Charges:",
          f"  Linehaul (flat) ............ ${money(b['linehaul'])}",
          f"  Fuel  {b['miles']} mi x ${b['fsc_per_mile']:.2f} ..... ${money(b['fsc'])}"]
    for l in b["accessorials"]:
        name = R.ACC_WORDING["CCCO"][l["code"]]
        if l["code"] == "DET":
            name = f"{name}: {l['qty']:g} hrs @ ${l['rate']:.0f}"
        L.append(f"  {name} ... ${money(l['amount'])}")
    L += [f"  TOTAL DUE: ${money(b['total'])}", "", "Terms net 30. Remit to PO Box 5521, Lakeland FL 33807 or ACH (details on file).", "",
          rng.choice(["Thanks,", "Thank you,", "Best,"]), rng.choice(["Maria G.", "Kevin T.", "Shonda R."]), "Billing Dept | Coldchain Carriers Co.",
          R.CARRIERS["CCCO"]["phone"]]
    path.write_text("\n".join(L) + "\n")


# ------------------------------------------------------------------ SMFB (EDI 210)
EDI_CODES = {"DET": "DET", "STP": "SOC", "TARP": "TRP", "LAY": "LAY", "TONU": "TNU"}


def smfb(rec, path):
    s, b, rng = rec["shipment"], rec["billed"], rec["_rng"]
    sh, cn = addr_lines(s)
    d = lambda x: (dt.date.fromisoformat(x) if isinstance(x, str) else x).strftime("%Y%m%d")
    cents = lambda x: str(int(round(x * 100)))
    ctl = rng.randint(1000, 9999)
    segs = [
        f"ISA*00*          *00*          *02*SMFB           *ZZ*LARKSPURHG     *{d(rec['invoice_date'])[2:]}*0815*U*00401*00000{ctl}*0*P*>",
        f"GS*IM*SMFB*LARKSPURHG*{d(rec['invoice_date'])}*0815*{ctl}*X*004010",
        "ST*210*0001",
        f"B3**{rec['invoice_number']}*{s['pro_number']}*PP**{d(rec['invoice_date'])}*{cents(b['total'])}****SMFB*{d(s['ship_date'])}",
        "C3*USD",
        f"N9*BM*{s['bol_number']}",
        f"N9*PO*{s['po_number']}",
        f"G62*86*{d(s['delivery_date'])}",
        "N1*SH*" + sh["name"].upper(), f"N3*{sh['addr'].upper()}", f"N4*{sh['city'].upper()}*{sh['state']}*{sh['zip']}",
        "N1*CN*" + cn["name"].upper(), f"N4*{cn['city'].upper()}*{cn['state']}*{cn['zip']}",
        "N1*BT*LARKSPUR HOME GOODS INC", "N4*CHICAGO*IL*60606",
        "N7**FB48*****FT",
        "LX*1",
        f"L5*1*{s['commodity'].upper()[:35]}",
        f"L0*1***{int(b['billed_weight'])}*G***{s['pieces']}*PCS**L",
        f"L1*1*{b['linehaul']:.2f}*FR*{cents(b['linehaul'])}****400*FLAT LINEHAUL",
        f"L1*2*{b['fsc_per_mile']:.2f}*PM*{cents(b['fsc'])}****FUE*FUEL {b['miles']} MI",
    ]
    for i, l in enumerate(b["accessorials"], start=3):
        qual = "PH" if l["code"] == "DET" else "FR"
        segs.append(f"L1*{i}*{l['rate']:.2f}*{qual}*{cents(l['amount'])}****{EDI_CODES[l['code']]}*{l['qty']:g} {'HR' if l['code']=='DET' else 'EA'}")
    segs.append(f"L3*{int(b['billed_weight'])}*G***{cents(b['total'])}****{s['pieces']}")
    segs.append(f"SE*{len(segs) - 1}*0001")
    segs += [f"GE*1*{ctl}", f"IEA*1*00000{ctl}"]
    sep = "~\n" if rng.random() < 0.7 else "~"
    path.write_text(sep.join(segs) + "~\n")


# ------------------------------------------------------------------ scanning effect
def scanify(path: Path, rng: random.Random):
    import numpy as np
    import pypdfium2 as pdfium
    from PIL import Image, ImageFilter

    pdf = pdfium.PdfDocument(str(path))
    img = pdf[0].render(scale=1.45).to_pil().convert("L")
    pdf.close()
    img = img.rotate(rng.uniform(-1.4, 1.4), resample=Image.BICUBIC, expand=False, fillcolor=255)
    arr = np.asarray(img).astype("float32")
    nrng = np.random.default_rng(rng.randint(0, 10**6))
    arr = arr * rng.uniform(0.88, 0.97) + nrng.normal(0, 9, arr.shape) + 12
    speck = nrng.random(arr.shape) < 0.0015
    arr[speck] = 40
    img = Image.fromarray(arr.clip(0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.45))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=58)
    Image.open(buf).save(str(path), "PDF", resolution=105)


RENDERERS = {"RDGL": rdgl, "PXLT": pxlt, "BWTR": bwtr, "IHLG": ihlg, "CCCO": ccco, "SMFB": smfb}


def render(rec, path: Path, scanned: bool, rng: random.Random):
    rec["_rng"] = random.Random(rng.randint(0, 10**9))
    RENDERERS[rec["scac"]](rec, path)
    if scanned:
        scanify(path, rng)
