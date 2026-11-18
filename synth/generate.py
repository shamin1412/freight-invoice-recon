"""Generate the synthetic freight world: SQLite reference data, 50 carrier invoices
(PDF, scanned PDF and raw text) with planted errors, and an answer key.

    python -m synth.generate            # writes data/freight.db, data/invoices/*, data/answer_key.json

Deterministic (seeded) so the eval is reproducible.
"""
from __future__ import annotations

import datetime as dt
import json
import random
import shutil
from pathlib import Path

from freight import db as fdb
from freight.pricing import RateBook, r2, dwell_hours
from synth import reference as R
from synth import render

SEED = 20261118
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
INV_DIR = DATA / "invoices"

CONTRACT_START = "2026-01-01"
CONTRACT_END = "2026-12-31"

# Clause numbering differs by carrier contract, as it does in real life.
CLAUSE_REFS = {
    "RDGL": {"RATES": "Section 3.1", "FUEL": "Section 3.4", "ACCESSORIAL": "Section 5.1", "AUTHORIZATION": "Section 5.2",
             "WEIGHT_CLASS": "Section 6.3", "DUPLICATE": "Section 8.2", "DISPUTE": "Section 8.4"},
    "PXLT": {"RATES": "Art. 4(a)", "FUEL": "Art. 4(d)", "ACCESSORIAL": "Art. 7(a)", "AUTHORIZATION": "Art. 7(b)",
             "WEIGHT_CLASS": "Art. 9(c)", "DUPLICATE": "Art. 12(b)", "DISPUTE": "Art. 12(e)"},
    "BWTR": {"RATES": "§2.1", "FUEL": "§2.5", "ACCESSORIAL": "§4.1", "AUTHORIZATION": "§4.3",
             "WEIGHT_CLASS": "§5.2", "DUPLICATE": "§9.1", "DISPUTE": "§9.3"},
    "IHLG": {"RATES": "Clause 2", "FUEL": "Clause 3", "ACCESSORIAL": "Clause 5", "AUTHORIZATION": "Clause 5.4",
             "DETENTION": "Clause 5.2", "LUMPER": "Clause 5.3", "DUPLICATE": "Clause 11.1", "DISPUTE": "Clause 11.3"},
    "CCCO": {"RATES": "Sec. 2.0", "FUEL": "Sec. 2.3", "ACCESSORIAL": "Sec. 4.0", "AUTHORIZATION": "Sec. 4.6",
             "DETENTION": "Sec. 4.2", "LUMPER": "Sec. 4.4", "DUPLICATE": "Sec. 10.2", "DISPUTE": "Sec. 10.4"},
    "SMFB": {"RATES": "Para. 1", "FUEL": "Para. 2", "ACCESSORIAL": "Para. 6", "AUTHORIZATION": "Para. 6(c)",
             "DETENTION": "Para. 6(a)", "DUPLICATE": "Para. 14", "DISPUTE": "Para. 15"},
}


def clause_texts(scac: str, c: dict) -> dict:
    mode = R.CARRIERS[scac]["mode"]
    t = {}
    if mode == "LTL":
        t["RATES"] = (f"Linehaul charges shall be computed from Carrier's base rate tariff in effect on the date of pickup "
                      f"(Schedule A), less a discount of {c['discount_pct']:.1f}%, subject to an absolute minimum charge of "
                      f"${c['min_charge']:.2f} per shipment. No other rate basis applies.")
        t["FUEL"] = ("Fuel surcharge shall be the percentage shown in Schedule B corresponding to the U.S. DOE/EIA national "
                     "average on-highway diesel price published for the week in which the shipment is picked up, applied "
                     "to net linehaul only. Fuel surcharge shall not be applied to accessorial charges.")
        t["WEIGHT_CLASS"] = ("The weight, NMFC item and class declared on Shipper's Bill of Lading govern. Carrier may "
                             "adjust weight or class only upon furnishing a certified weight & inspection (W&I) certificate "
                             "with the invoice; absent such certificate the BOL weight and class shall be used.")
    else:
        t["RATES"] = ("Linehaul shall be the all-in lane rate set out in Schedule A for the origin/destination pair, "
                      "inclusive of all miles. Rates may be changed only by a written amendment signed by both parties.")
        t["FUEL"] = (f"Fuel surcharge per loaded mile = (DOE/EIA U.S. average on-highway diesel price for the week of pickup "
                     f"- ${c['fsc_peg']:.2f}) / {c['fsc_mpg']:.1f}, rounded to the nearest cent, multiplied by Schedule A "
                     f"lane miles.")
        t["DETENTION"] = (f"Shipper allows {c['det_free']:.0f} hours free time at each facility, measured from the "
                          f"consignee's dock check-in to check-out. Detention thereafter is payable at ${c['det_rate']:.2f} "
                          f"per hour, in increments of {c['det_inc']:g} hour, and only as supported by facility in/out times.")
        if "LUMPER" in CLAUSE_REFS[scac]:
            t["LUMPER"] = "Lumper charges are reimbursed at actual cost only when the original lumper receipt accompanies the invoice."
    t["ACCESSORIAL"] = ("Accessorial charges are payable only at the amounts listed in Schedule C. Any charge not listed in "
                        "Schedule C is not payable.")
    t["AUTHORIZATION"] = ("Accessorial services marked 'authorization required' in Schedule C are payable only if the service "
                          "is noted on the Bill of Lading or approved in writing by Shipper's transportation department "
                          "before the service is performed.")
    t["DUPLICATE"] = ("Each shipment shall be invoiced once. Duplicate invoices, or invoices for a PRO/BOL already billed, "
                      "will be rejected and shall not be paid.")
    t["DISPUTE"] = ("Shipper may short-pay any disputed amount and pay the undisputed balance. Carrier shall respond to a "
                    "written dispute within 30 days; claims for undercharges must be filed within 180 days of delivery.")
    return t


# --------------------------------------------------------------------------------------
# Scenario plan: 50 invoices. Each tuple = (carrier, list of planted conditions).
#  Errors:   WEIGHT_INFLATED, UNAUTH_ACC, DUP_INVOICE, DUP_SHIPMENT, FSC_WRONG, RATE_OVER,
#            CLASS_WRONG, DETENTION_OVER, UNKNOWN_BOL
#  Benign:   TOLERANCE (variance < 1%), and legit accessorials (LEGIT:<code>), MIN_CHARGE
# --------------------------------------------------------------------------------------
SCENARIOS = {
    "RDGL": [[], ["LEGIT:LGD"], ["WEIGHT_INFLATED"], ["MIN_CHARGE"], ["UNAUTH_ACC:LGD"], ["LEGIT:RES", "LEGIT:LGD"],
             ["TOLERANCE"], ["DUP_INVOICE:1"], [], ["FSC_WRONG"]],
    "PXLT": [[], ["LEGIT:NOA"], ["RATE_OVER"], [], ["CLASS_WRONG"], ["MIN_CHARGE"], ["UNAUTH_ACC:INS", "WEIGHT_INFLATED"],
             ["TOLERANCE"], ["LEGIT:HAZ"]],
    "BWTR": [[], ["LEGIT:HAZ"], ["FSC_WRONG"], ["LEGIT:LAD"], ["UNKNOWN_BOL"], [], ["WEIGHT_INFLATED"], ["DUP_SHIPMENT:0"],
             ["LEGIT:RES", "LEGIT:LGD", "LEGIT:NOA"]],
    "IHLG": [[], ["LEGIT:DET"], ["DETENTION_OVER"], ["LEGIT:STP"], ["RATE_OVER"], [], ["TOLERANCE"], ["UNAUTH_ACC:LAY"],
             ["LEGIT:LUM"]],
    "CCCO": [[], ["LEGIT:LUM"], ["FSC_WRONG"], ["LEGIT:DET"], ["DETENTION_OVER"], ["DUP_INVOICE:0"], []],
    "SMFB": [[], ["LEGIT:TARP"], ["TOLERANCE"], ["UNAUTH_ACC:TARP"], ["LEGIT:STP"], []],
}
SCANNED = {("RDGL", 2), ("RDGL", 8), ("BWTR", 3), ("BWTR", 6), ("IHLG", 4), ("IHLG", 7)}

ERROR_TYPES = {"WEIGHT_INFLATED", "UNAUTH_ACC", "DUP_INVOICE", "DUP_SHIPMENT", "FSC_WRONG", "RATE_OVER",
               "CLASS_WRONG", "DETENTION_OVER", "UNKNOWN_BOL"}


def doe_series(rng: random.Random) -> dict:
    """Weekly diesel prices, Mondays 2026-08-31 .. 2026-11-16 (synthetic, EIA-like movement)."""
    price, out = 3.684, {}
    d = dt.date(2026, 8, 31)
    while d <= dt.date(2026, 11, 16):
        out[d.isoformat()] = round(price, 3)
        price += rng.choice([-1, 1]) * rng.uniform(0.005, 0.045) + 0.006
        d += dt.timedelta(days=7)
    return out


def seed_reference(conn, rng: random.Random) -> None:
    for scac, c in R.CARRIERS.items():
        conn.execute("INSERT INTO carriers VALUES (?,?,?,?)", (scac, c["name"], c["mode"], "|".join(c["aliases"])))
        t = R.CONTRACT_TERMS[scac]
        cid = f"C-{scac}-2026"
        if c["mode"] == "LTL":
            conn.execute("INSERT INTO contracts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (cid, scac, "LTL", None, CONTRACT_START, CONTRACT_END, t["discount_pct"], t["min_charge"],
                          "PCT_TABLE", None, None, None, None, None))
            # base tariff
            for dc in c["dcs"]:
                for city, st, z, miles in R.LTL_DESTS[dc]:
                    base100 = (95 + 0.12 * miles) * t["tariff_mult"] * rng.uniform(0.96, 1.04)
                    for cls, cf in R.CLASS_FACTORS.items():
                        for lo, hi, wf in R.WEIGHT_BREAKS:
                            conn.execute("INSERT INTO ltl_tariff VALUES (?,?,?,?,?,?,?)",
                                         (cid, R.DCS[dc]["zip"][:3], z[:3], cls, lo, hi, round(base100 * cf * wf, 2)))
            # fuel table: 0% at <= $1.149, +step% per $0.05
            p, pct = 1.15, t["fsc_step_pct"]
            conn.execute("INSERT INTO fsc_ltl_table VALUES (?,?,?,?)", (cid, 0.0, 1.149, 0.0))
            while p < 6.0:
                conn.execute("INSERT INTO fsc_ltl_table VALUES (?,?,?,?)", (cid, round(p, 3), round(p + 0.049, 3), round(pct, 2)))
                p += 0.05
                pct += t["fsc_step_pct"]
        else:
            conn.execute("INSERT INTO contracts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (cid, scac, "TL", c["equipment"], CONTRACT_START, CONTRACT_END, None, None, "PER_MILE",
                          t["fsc_peg"], t["fsc_mpg"], t["det_free"], t["det_rate"], t["det_inc"]))
            for dc, city, st, z, miles in R.TL_LANES[scac]:
                rpm = t["rate_per_mile"] * (1.35 if miles < 400 else 1.0) * rng.uniform(0.95, 1.06)
                lh = max(650.0, round(miles * rpm / 25.0) * 25.0)
                conn.execute("INSERT INTO tl_lane_rates VALUES (?,?,?,?,?)", (cid, R.DCS[dc]["zip"][:3], z[:3], miles, lh))
        mode = c["mode"]
        refs = CLAUSE_REFS[scac]
        for code, amt in R.ACC_AMOUNTS[scac].items():
            desc, unit, auth = R.ACCESSORIALS[mode][code]
            ref = refs["DETENTION"] if code == "DET" else refs.get("LUMPER", refs["ACCESSORIAL"]) if code == "LUM" else (
                refs["AUTHORIZATION"] if auth else refs["ACCESSORIAL"])
            conn.execute("INSERT INTO accessorial_schedule VALUES (?,?,?,?,?,?,?)", (cid, code, desc, unit, amt, auth, ref))
        for topic, text in clause_texts(scac, t).items():
            conn.execute("INSERT INTO contract_clauses VALUES (?,?,?,?)", (cid, refs[topic], topic, text))
    for wk, price in doe_series(rng).items():
        conn.execute("INSERT INTO doe_diesel VALUES (?,?)", (wk, price))
    conn.commit()


# --------------------------------------------------------------------------------------
# Shipments
# --------------------------------------------------------------------------------------
class IdGen:
    def __init__(self, rng):
        self.rng = rng
        self.seq = {}

    def nxt(self, key, start):
        self.seq[key] = self.seq.get(key, start) + self.rng.randint(1, 37)
        return self.seq[key]


def pro_number(scac, ids):
    if scac == "RDGL":
        n = ids.nxt("RDGL", 4418200)
        return f"{n}-{sum(int(x) for x in str(n)) % 10}"
    if scac == "PXLT":
        return f"31044{ids.nxt('PXLT', 58000):05d}"
    if scac == "BWTR":
        return f"BWT{ids.nxt('BWTR', 20118000):08d}"
    if scac == "IHLG":
        return f"IH-26-{ids.nxt('IHLG', 4400):05d}"
    if scac == "CCCO":
        return f"CC{ids.nxt('CCCO', 9100):04d}"
    return f"SF26{ids.nxt('SMFB', 4100):05d}"


def make_shipment(scac, rng, ids, ship_date, conds):
    c = R.CARRIERS[scac]
    legit = [x.split(":")[1] for x in conds if x.startswith("LEGIT:")]
    s = {"scac": scac, "mode": c["mode"], "ship_date": ship_date.isoformat(), "pro_number": pro_number(scac, ids),
         "po_number": f"45002{rng.randint(10000, 99999)}", "stops": 1, "authorized": [], "dock_in": None,
         "dock_out": None, "lumper_receipt": None, "equipment": c.get("equipment")}
    if c["mode"] == "LTL":
        dc = rng.choice(c["dcs"])
        city, st, z, miles = rng.choice(R.LTL_DESTS[dc])
        hazmat_needed = "HAZ" in legit
        pool = [x for x in R.LTL_COMMODITIES if x[4] == hazmat_needed]
        com, nmfc, cls, ppw, _ = rng.choice(pool)
        if "MIN_CHARGE" in conds:
            pieces = rng.randint(2, 6)
        else:
            pieces = rng.randint(6, 140)
        wt = int(sum(rng.uniform(*ppw) for _ in range(pieces)) / 5) * 5 + rng.choice([0, 0, 5])
        wt = min(max(wt, 95), 9800)
        hu = max(1, min(12, round(wt / rng.uniform(550, 1100))))
        residential = "RES" in legit
        consignee = rng.choice(R.RESIDENTIAL_CONSIGNEES) if residential else rng.choice(R.STORE_CONSIGNEES).format(n=rng.randint(101, 989))
        s.update({"dc": dc, "dest_city": city, "dest_state": st, "dest_zip": z[:3] + f"{rng.randint(0, 99):02d}" if rng.random() < 0.3 else z,
                  "miles": miles, "commodity": com, "nmfc": nmfc, "freight_class": cls, "pieces": pieces, "handling_units": hu,
                  "weight_lbs": float(wt), "consignee": consignee, "delivery_date": (ship_date + dt.timedelta(days=rng.randint(1, 4))).isoformat()})
    else:
        dc, city, st, z, miles = rng.choice(R.TL_LANES[scac])
        com = rng.choice(R.TL_COMMODITIES[c["equipment"]])
        wt = float(rng.randint(180, 435) * 100 + rng.choice([0, 20, 40, 60, 80]))
        s.update({"dc": dc, "dest_city": city, "dest_state": st, "dest_zip": z, "miles": miles, "commodity": com,
                  "nmfc": None, "freight_class": None, "pieces": rng.randint(18, 26) if c["equipment"] != "FLATBED" else rng.randint(6, 14),
                  "handling_units": None, "weight_lbs": wt, "consignee": rng.choice(R.STORE_CONSIGNEES).format(n=rng.randint(101, 989)) if city != "Joliet" else R.DCS["JOL"]["name"],
                  "delivery_date": (ship_date + dt.timedelta(days=max(1, round(miles / 500)))).isoformat()})
        deliv = dt.date.fromisoformat(s["delivery_date"])
        appt = dt.datetime.combine(deliv, dt.time(rng.choice([6, 7, 8, 9, 10, 13, 14])))
        if "LEGIT:DET" in conds or "DETENTION_OVER" in conds:
            dwell = rng.choice([3.25, 3.75, 4.5, 5.0, 4.0, 3.5])
        else:
            dwell = rng.uniform(0.6, 1.9)
        s["dock_in"] = appt.isoformat(timespec="minutes")
        s["dock_out"] = (appt + dt.timedelta(minutes=round(dwell * 60))).isoformat(timespec="minutes")
        if "STP" in legit:
            s["stops"] = 2
        if "LUM" in legit:
            s["lumper_receipt"] = float(rng.choice([165, 185, 210, 240, 275, 195]))
    s["authorized"] = [x for x in legit if x not in ("DET", "LUM", "STP")] + (["STP"] if "STP" in legit else [])
    s["bol_number"] = f"LHG-{s['dc']}-{ship_date.strftime('%m%d')}-{rng.randint(1000, 9999)}"
    s["shipper"] = R.DCS[s["dc"]]
    s["reweigh_certificate"] = 0
    return s


def insert_shipment(conn, s):
    sh = s["shipper"]
    conn.execute("""INSERT INTO shipments (bol_number, pro_number, scac, mode, equipment, ship_date, delivery_date, po_number,
        shipper_name, origin_city, origin_state, origin_zip, consignee_name, dest_city, dest_state, dest_zip, pieces,
        handling_units, weight_lbs, freight_class, nmfc, commodity, miles, stops, authorized_accessorials, dock_in, dock_out,
        lumper_receipt, reweigh_certificate) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (s["bol_number"], s["pro_number"], s["scac"], s["mode"], s["equipment"], s["ship_date"], s["delivery_date"],
                  s["po_number"], sh["name"], sh["city"], sh["state"], sh["zip"], s["consignee"], s["dest_city"],
                  s["dest_state"], s["dest_zip"], s["pieces"], s["handling_units"], s["weight_lbs"], s["freight_class"],
                  s["nmfc"], s["commodity"], s["miles"], s["stops"], ",".join(s["authorized"]), s["dock_in"], s["dock_out"],
                  s["lumper_receipt"], s["reweigh_certificate"]))


# --------------------------------------------------------------------------------------
# Invoice construction
# --------------------------------------------------------------------------------------
def price_invoice(rb: RateBook, s: dict, conds: list, rng: random.Random, correct: bool) -> dict:
    """Build the charge lines. correct=True -> what the contract says should be billed."""
    scac = s["scac"]
    contract = rb.contract_for(scac, dt.date.fromisoformat(s["ship_date"]))
    cid = contract["contract_id"]
    ship_date = dt.date.fromisoformat(s["ship_date"])
    doe = rb.doe_price(ship_date)
    err = set() if correct else {c.split(":")[0] for c in conds}
    lines, inv = [], {"doe_price": doe}
    acc_codes = [c.split(":")[1] for c in conds if c.startswith("LEGIT:")]
    if "UNAUTH_ACC" in err:
        acc_codes.append([c.split(":")[1] for c in conds if c.startswith("UNAUTH_ACC")][0])

    if s["mode"] == "LTL":
        wt = s["weight_lbs"]
        cls = s["freight_class"]
        if "WEIGHT_INFLATED" in err:
            # Carrier bills an inflated weight. Pick a factor that actually raises the charge
            # (crossing into a heavier weight break can lower the $/CWT enough to reduce it).
            base_net = rb.ltl_linehaul(contract, s["shipper"]["zip"], s["dest_zip"], wt, cls).net
            for i in range(400):
                cand = float(int(wt * rng.uniform(1.09, 1.24 + i * 0.002) / 5) * 5)
                if rb.ltl_linehaul(contract, s["shipper"]["zip"], s["dest_zip"], cand, cls).net > base_net * 1.06:
                    break
            else:
                raise RuntimeError("could not inflate weight")
            wt = cand
        if "CLASS_WRONG" in err:
            order = list(R.CLASS_FACTORS)
            cls = order[min(len(order) - 1, order.index(cls) + 2)]
        lh = rb.ltl_linehaul(contract, s["shipper"]["zip"], s["dest_zip"], wt, cls)
        disc_pct, gross, disc, net = lh.discount_pct, lh.gross, lh.discount, lh.net
        if "RATE_OVER" in err:
            disc_pct = contract["discount_pct"] - rng.choice([5.0, 6.5, 7.0])
            disc = r2(gross * disc_pct / 100)
            net = max(contract["min_charge"], r2(gross - disc))
        pct = rb.ltl_fsc_pct(contract, doe)
        if "FSC_WRONG" in err:
            pct = round(pct + rng.choice([3.0, 3.5, 4.5]), 2)
        if "TOLERANCE" in err:
            pct = round(pct + 0.6, 2)
        fsc = r2(net * pct / 100)
        inv.update({"billed_weight": wt, "billed_class": cls, "cwt_rate": lh.cwt_rate, "gross": gross,
                    "discount_pct": disc_pct, "discount": disc, "net_linehaul": net, "fsc_pct": pct, "fsc": fsc,
                    "min_applied": lh.min_applied})
        for code in acc_codes:
            row = rb.accessorial(cid, code)
            lines.append({"code": code, "qty": 1, "rate": row["amount"], "amount": row["amount"]})
    else:
        lane = rb.tl_lane(contract, s["shipper"]["zip"], s["dest_zip"])
        linehaul = lane["linehaul"]
        if "RATE_OVER" in err:
            linehaul += rng.choice([150.0, 200.0, 275.0])
        fpm = rb.tl_fsc_per_mile(contract, doe)
        if "FSC_WRONG" in err:
            fpm = r2((doe - 1.05) / (contract["fsc_mpg"] - 0.5))
        if "TOLERANCE" in err:
            fpm = r2(fpm + 0.01)
        fsc = r2(fpm * lane["miles"])
        inv.update({"billed_weight": s["weight_lbs"], "miles": lane["miles"], "linehaul": linehaul, "fsc_per_mile": fpm,
                    "fsc": fsc, "net_linehaul": linehaul})
        for code in acc_codes:
            row = rb.accessorial(cid, code)
            if code == "DET":
                hrs = rb.detention_billable_hours(contract, dwell_hours(s["dock_in"], s["dock_out"]))
                lines.append({"code": "DET", "qty": hrs, "rate": row["amount"], "amount": r2(hrs * row["amount"])})
            elif code == "STP":
                n = s["stops"] - 1
                lines.append({"code": "STP", "qty": n, "rate": row["amount"], "amount": r2(n * row["amount"])})
            elif code == "LUM":
                lines.append({"code": "LUM", "qty": 1, "rate": s["lumper_receipt"], "amount": s["lumper_receipt"]})
            else:
                lines.append({"code": code, "qty": 1, "rate": row["amount"], "amount": row["amount"]})
        if "DETENTION_OVER" in conds and not correct:
            row = rb.accessorial(cid, "DET")
            dwell = dwell_hours(s["dock_in"], s["dock_out"])
            hrs = round(dwell + rng.choice([0.0, 1.0, 1.5]), 2)  # carrier ignores free time and/or pads hours
            hrs = float(int(hrs * 4) / 4)
            lines.append({"code": "DET", "qty": hrs, "rate": row["amount"], "amount": r2(hrs * row["amount"])})
        elif "DETENTION_OVER" in conds and correct:
            row = rb.accessorial(cid, "DET")
            hrs = rb.detention_billable_hours(contract, dwell_hours(s["dock_in"], s["dock_out"]))
            if hrs:
                lines.append({"code": "DET", "qty": hrs, "rate": row["amount"], "amount": r2(hrs * row["amount"])})
    inv["accessorials"] = lines
    inv["total"] = r2(inv["net_linehaul"] + inv["fsc"] + sum(l["amount"] for l in lines))
    return inv


def invoice_number(scac, s, rng, ids):
    if scac == "RDGL":
        return s["pro_number"].replace("-", "")
    if scac == "PXLT":
        return f"PX-INV-{ids.nxt('PXINV', 98100):07d}"
    if scac == "BWTR":
        return f"26-{ids.nxt('BWINV', 11400):06d}"
    if scac == "IHLG":
        return f"IH{ids.nxt('IHINV', 100400)}"
    if scac == "CCCO":
        return f"CCC-2026-{ids.nxt('CCINV', 1150):04d}"
    return f"SMF-{ids.nxt('SMINV', 77180)}"


def main():
    rng = random.Random(SEED)
    DATA.mkdir(exist_ok=True)
    if INV_DIR.exists():
        shutil.rmtree(INV_DIR)
    INV_DIR.mkdir(parents=True)
    dbp = DATA / "freight.db"
    if dbp.exists():
        dbp.unlink()
    conn = fdb.connect(dbp)
    fdb.init_schema(conn)
    seed_reference(conn, rng)
    rb = RateBook(conn)
    ids = IdGen(rng)

    # Build each carrier's invoice stream in ship-date order
    records = []
    for scac, plan in SCENARIOS.items():
        d = dt.date(2026, 9, 14) + dt.timedelta(days=rng.randint(0, 4))
        carrier_recs = []
        for idx, conds in enumerate(plan):
            kinds = {c.split(":")[0] for c in conds}
            if "DUP_INVOICE" in kinds or "DUP_SHIPMENT" in kinds:
                src_idx = int([c for c in conds if c.startswith("DUP_")][0].split(":")[1])
                src = carrier_recs[src_idx]
                rec = {"scac": scac, "idx": idx, "conds": conds, "shipment": src["shipment"], "dup_of": src,
                       "kind": "DUP_INVOICE" if "DUP_INVOICE" in kinds else "DUP_SHIPMENT"}
                carrier_recs.append(rec)
                continue
            while d.weekday() >= 5:
                d += dt.timedelta(days=1)
            s = make_shipment(scac, rng, ids, d, conds)
            rec = {"scac": scac, "idx": idx, "conds": conds, "shipment": s}
            carrier_recs.append(rec)
            d += dt.timedelta(days=rng.randint(2, 6))
        records.extend(carrier_recs)

    # Insert shipments into the BOL log (except the UNKNOWN_BOL one), plus un-invoiced noise shipments
    for rec in records:
        if "dup_of" in rec:
            continue
        if "UNKNOWN_BOL" in rec["conds"]:
            continue
        insert_shipment(conn, rec["shipment"])
    for _ in range(24):
        scac = rng.choice(list(R.CARRIERS))
        s = make_shipment(scac, rng, ids, dt.date(2026, 9, 14) + dt.timedelta(days=rng.randint(0, 50)), [])
        if dt.date.fromisoformat(s["ship_date"]).weekday() < 5:
            insert_shipment(conn, s)
    conn.commit()

    # Price + number invoices
    for rec in records:
        s = rec["shipment"]
        if "dup_of" in rec:
            src = rec["dup_of"]
            rec["billed"] = src["billed"]
            rec["correct"] = src["correct"]
            if rec["kind"] == "DUP_INVOICE":
                rec["invoice_number"] = src["invoice_number"]
                rec["invoice_date"] = src["invoice_date"]
            else:
                rec["invoice_number"] = invoice_number(rec["scac"], s, rng, ids)
                rec["invoice_date"] = src["invoice_date"] + dt.timedelta(days=rng.randint(12, 20))
            rec["received"] = src["received"] + dt.timedelta(days=rng.randint(14, 24))
            continue
        rec["billed"] = price_invoice(rb, s, rec["conds"], rng, correct=False)
        rec["correct"] = price_invoice(rb, s, rec["conds"], rng, correct=True)
        rec["invoice_number"] = invoice_number(rec["scac"], s, rng, ids)
        base = dt.date.fromisoformat(s["delivery_date"])
        rec["invoice_date"] = base + dt.timedelta(days=rng.randint(0, 3))
        rec["received"] = rec["invoice_date"] + dt.timedelta(days=rng.randint(1, 4))

    # Received order across all carriers (duplicates naturally land after their originals)
    records.sort(key=lambda r: (r["received"], r["scac"], r["idx"]))
    answer_key = []
    for n, rec in enumerate(records, start=1):
        scac, s, b = rec["scac"], rec["shipment"], rec["billed"]
        scanned = (scac, rec["idx"]) in SCANNED
        fmt = render.FORMATS[scac]
        stem = f"INV{n:03d}_{scac}"
        fname = stem + (".pdf" if fmt == "pdf" else ".txt")
        render.render(rec, INV_DIR / fname, scanned=scanned, rng=rng)
        kinds = [c.split(":")[0] for c in rec["conds"]]
        errors = [k for k in kinds if k in ERROR_TYPES]
        if "UNKNOWN_BOL" in errors:
            decision, over = "EXCEPTION", 0.0
        elif "DUP_INVOICE" in errors or "DUP_SHIPMENT" in errors:
            decision, over = "DISPUTE", b["total"]
        elif errors:
            decision, over = "DISPUTE", r2(b["total"] - rec["correct"]["total"])
        else:
            decision, over = "APPROVE", 0.0
        truth = {
            "carrier_scac": scac,
            "invoice_number": rec["invoice_number"],
            "invoice_date": rec["invoice_date"].isoformat(),
            "pro_number": s["pro_number"],
            "bol_number": s["bol_number"],
            "ship_date": s["ship_date"],
            "origin_zip": s["shipper"]["zip"],
            "dest_zip": s["dest_zip"],
            "mode": s["mode"],
            "billed_weight_lbs": b["billed_weight"],
            "freight_class": b.get("billed_class"),
            "miles": b.get("miles"),
            "linehaul_amount": b["net_linehaul"],
            "fuel_surcharge_amount": b["fsc"],
            "accessorials": [{"code": l["code"], "amount": l["amount"]} for l in b["accessorials"]],
            "total_due": b["total"],
        }
        answer_key.append({"file": fname, "received_order": n, "received_date": rec["received"].isoformat(),
                           "format": "scanned_pdf" if scanned else fmt, "planted": rec["conds"], "errors": errors,
                           "expected_decision": decision, "true_overcharge": over,
                           "correct_total": rec["correct"]["total"], "truth": truth})
    (DATA / "answer_key.json").write_text(json.dumps(answer_key, indent=2))
    conn.close()
    n_dec = {}
    for a in answer_key:
        n_dec[a["expected_decision"]] = n_dec.get(a["expected_decision"], 0) + 1
    print(f"wrote {len(answer_key)} invoices -> {INV_DIR}")
    print("expected decisions:", n_dec, " planted overcharge $", round(sum(a["true_overcharge"] for a in answer_key), 2))


if __name__ == "__main__":
    main()
