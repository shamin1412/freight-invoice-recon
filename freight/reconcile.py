"""Deterministic reconciliation engine.

Input: an extracted invoice (dict with the InvoiceExtraction fields).
Output: a decision (APPROVE / DISPUTE / EXCEPTION), a list of findings with dollar impact and
the contract clause each one relies on, and the contract-supported total.

Policy
------
* Categorical violations are disputed regardless of size: duplicate billing, accessorials not in
  the contract or not authorized on the BOL, detention beyond the dock log, unsupported lumper,
  billed weight more than 1% over the BOL, or a class change, without a W&I certificate.
* Rate and fuel variances (rounding, table look-ups) are tolerated when the invoice total is
  within 1% of the contract-supported total. Above 1% they are disputed.
* An invoice that cannot be matched to the shipment log or to a contract is an EXCEPTION for a
  human, not an automatic dispute.
"""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
from dataclasses import dataclass, field, asdict

from freight.pricing import RateBook, r2, dwell_hours, normalize_class

TOLERANCE = 0.01
CATEGORICAL = {"DUPLICATE", "UNAUTHORIZED_ACCESSORIAL", "NOT_IN_CONTRACT", "DETENTION_EXCESS", "LUMPER_UNSUPPORTED",
               "WEIGHT_OVER_BOL", "CLASS_MISMATCH", "ACCESSORIAL_OVER_SCHEDULE"}

ACC_KEYWORDS = [  # fallback mapping when the extractor did not give a canonical code
    ("LGD", r"lift\s*-?gate|lgate|lftd"), ("RES", r"resid|resd"), ("INS", r"inside|indl"),
    ("NOA", r"notif|notf|appt|appoint|call"), ("LAD", r"limited|ltda"), ("HAZ", r"haz"),
    ("DET", r"detention|\bdet\b"), ("STP", r"stop|\bsoc\b"), ("LUM", r"lumper|unload"),
    ("LAY", r"layover|\blay\b"), ("TONU", r"tonu|tnu|not used"), ("TARP", r"tarp|\btrp\b"), ("DRV", r"driver assist"),
]


@dataclass
class Finding:
    rule: str
    title: str
    detail: str
    billed: float
    allowed: float
    impact: float
    clause_ref: str | None = None
    clause_text: str | None = None


@dataclass
class Reconciliation:
    decision: str
    billed_total: float
    expected_total: float | None
    overcharge: float
    findings: list[Finding] = field(default_factory=list)
    carrier_scac: str | None = None
    contract_id: str | None = None
    bol_number: str | None = None
    invoice_number: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        return d


def _norm_id(x) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(x or "").upper())


def _num(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


class Reconciler:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.rb = RateBook(conn)
        self.seen: list[dict] = []  # invoices processed in this run (duplicate detection)

    # ------------------------------------------------------------------ helpers
    def resolve_carrier(self, inv: dict) -> str | None:
        scac = (inv.get("carrier_scac") or "").strip().upper()
        if scac and self.conn.execute("SELECT 1 FROM carriers WHERE scac=?", (scac,)).fetchone():
            return scac
        name = (inv.get("carrier_name") or "").lower()
        best = None
        for row in self.conn.execute("SELECT scac, aliases FROM carriers"):
            for alias in row["aliases"].split("|"):
                if alias and alias in name and (best is None or len(alias) > best[1]):
                    best = (row["scac"], len(alias))
        return best[0] if best else None

    def match_shipment(self, inv: dict, scac: str | None) -> sqlite3.Row | None:
        bol = _norm_id(inv.get("bol_number"))
        pro = _norm_id(inv.get("pro_number"))
        rows = self.conn.execute("SELECT * FROM shipments" + (" WHERE scac=?" if scac else ""),
                                 (scac,) if scac else ()).fetchall()
        for r in rows:
            if bol and _norm_id(r["bol_number"]) == bol:
                return r
        for r in rows:
            if pro and _norm_id(r["pro_number"]) == pro:
                return r
        return None

    def clause(self, cid: str, topic: str):
        c = self.rb.clause(cid, topic)
        return (c["clause_ref"], c["text"]) if c else (None, None)

    def acc_code(self, line: dict) -> str:
        code = (line.get("code") or "").upper()
        if code and code != "OTHER":
            return code
        desc = (line.get("description") or "").lower()
        for c, pat in ACC_KEYWORDS:
            if re.search(pat, desc):
                return c
        return "OTHER"

    # ------------------------------------------------------------------ main
    def reconcile(self, inv: dict, record: bool = True) -> Reconciliation:
        billed_total = r2(_num(inv.get("total_due")))
        scac = self.resolve_carrier(inv)
        res = Reconciliation("EXCEPTION", billed_total, None, 0.0, carrier_scac=scac,
                             invoice_number=inv.get("invoice_number"))
        if scac is None:
            res.notes.append("Carrier could not be identified; route to AP for manual review.")
            return res

        ship = self.match_shipment(inv, scac)
        if ship is None:
            res.notes.append(f"No shipment in the BOL log matches BOL '{inv.get('bol_number')}' or PRO "
                             f"'{inv.get('pro_number')}' for {scac}. Hold for manual review; do not pay.")
            self._record(inv, scac, None, res, record)
            return res
        res.bol_number = ship["bol_number"]
        ship_date = dt.date.fromisoformat(ship["ship_date"])
        contract = self.rb.contract_for(scac, ship_date)
        if contract is None:
            res.notes.append(f"No active contract for {scac} on {ship_date}.")
            self._record(inv, scac, ship, res, record)
            return res
        cid = contract["contract_id"]
        res.contract_id = cid

        # ---------------- duplicate billing
        inv_no = _norm_id(inv.get("invoice_number"))
        for prev in self.seen:
            if prev["scac"] != scac:
                continue
            same_no = inv_no and prev["invoice_number"] == inv_no
            # a rebill after a disputed invoice is legitimate; a second bill for a shipment already paid is not
            same_ship = prev["bol_number"] == ship["bol_number"] and prev["decision"] == "APPROVE"
            if same_no or same_ship:
                ref, text = self.clause(cid, "DUPLICATE")
                why = (f"invoice number {inv.get('invoice_number')} was already received" if same_no else
                       f"shipment BOL {ship['bol_number']} / PRO {ship['pro_number']} was already billed on "
                       f"invoice {prev['invoice_number_raw']}")
                res.findings.append(Finding("DUPLICATE", "Duplicate billing", why.capitalize() + ".",
                                            billed_total, 0.0, billed_total, ref, text))
                res.decision, res.expected_total, res.overcharge = "DISPUTE", 0.0, billed_total
                self._record(inv, scac, ship, res, record)
                return res

        # ---------------- expected charges
        doe = self.rb.doe_price(ship_date)
        billed_lh = r2(_num(inv.get("linehaul_amount")))
        billed_fsc = r2(_num(inv.get("fuel_surcharge_amount")))
        f = res.findings
        if contract["mode"] == "LTL":
            bol_wt, bol_cls = ship["weight_lbs"], normalize_class(ship["freight_class"])
            billed_wt = _num(inv.get("billed_weight_lbs"), bol_wt) or bol_wt
            billed_cls = normalize_class(inv.get("freight_class")) or bol_cls
            lh = self.rb.ltl_linehaul(contract, ship["origin_zip"], ship["dest_zip"], bol_wt, bol_cls)
            if lh is None:
                res.notes.append("Lane / class not in contract tariff.")
                self._record(inv, scac, ship, res, record)
                return res
            exp_lh = lh.net
            pct = self.rb.ltl_fsc_pct(contract, doe)
            exp_fsc = r2(exp_lh * pct / 100)
            lh_ref, lh_text = self.clause(cid, "RATES")
            wc_ref, wc_text = self.clause(cid, "WEIGHT_CLASS")
            lh_var = r2(billed_lh - exp_lh)
            # fuel attributable to the linehaul difference travels with the linehaul finding
            lh_var_with_fuel = r2(lh_var + lh_var * pct / 100)
            if billed_wt > bol_wt * (1 + TOLERANCE) and not ship["reweigh_certificate"]:
                f.append(Finding("WEIGHT_OVER_BOL", "Billed weight exceeds BOL weight",
                                 f"Invoice bills {billed_wt:,.0f} lbs; BOL {ship['bol_number']} declares {bol_wt:,.0f} lbs "
                                 f"(+{(billed_wt / bol_wt - 1) * 100:.1f}%). No W&I reweigh certificate on file. "
                                 f"Linehaul re-rated at BOL weight: ${exp_lh:,.2f}.",
                                 billed_lh, exp_lh, lh_var_with_fuel, wc_ref, wc_text))
            elif billed_cls != bol_cls and not ship["reweigh_certificate"]:
                f.append(Finding("CLASS_MISMATCH", "Freight class differs from BOL",
                                 f"Invoice bills class {billed_cls}; BOL declares class {bol_cls} (NMFC {ship['nmfc']}). "
                                 f"No inspection certificate on file. Linehaul re-rated at class {bol_cls}: ${exp_lh:,.2f}.",
                                 billed_lh, exp_lh, lh_var_with_fuel, wc_ref, wc_text))
            elif abs(lh_var) >= 0.01:
                billed_disc = inv.get("discount_pct")
                extra = (f" Invoice shows a {billed_disc}% discount; contract discount is {contract['discount_pct']}%."
                         if billed_disc not in (None, "") and abs(_num(billed_disc) - contract["discount_pct"]) > 0.05 else "")
                f.append(Finding("LINEHAUL_VARIANCE", "Linehaul does not match contract",
                                 f"Billed net linehaul ${billed_lh:,.2f}; contract rate for {bol_wt:,.0f} lbs class {bol_cls} "
                                 f"{ship['origin_zip']}->{ship['dest_zip']} is ${exp_lh:,.2f}.{extra}",
                                 billed_lh, exp_lh, lh_var_with_fuel, lh_ref, lh_text))
            fsc_rate_var = r2(billed_fsc - r2(billed_lh * pct / 100))
            if abs(fsc_rate_var) >= 0.01:
                ref, text = self.clause(cid, "FUEL")
                bp = inv.get("fuel_surcharge_pct")
                shown = f"{_num(bp):.2f}%" if bp not in (None, "") else f"${billed_fsc:,.2f}"
                f.append(Finding("FUEL_VARIANCE", "Fuel surcharge does not match contract table",
                                 f"Billed fuel {shown}; DOE diesel for week of {ship_date:%m/%d/%Y} was ${doe:.3f}/gal, "
                                 f"which maps to {pct:.2f}% in the contract fuel table.",
                                 billed_fsc, r2(billed_lh * pct / 100), fsc_rate_var, ref, text))
        else:
            lane = self.rb.tl_lane(contract, ship["origin_zip"], ship["dest_zip"])
            if lane is None:
                res.notes.append("Lane not in contract Schedule A.")
                self._record(inv, scac, ship, res, record)
                return res
            exp_lh = lane["linehaul"]
            fpm = self.rb.tl_fsc_per_mile(contract, doe)
            exp_fsc = r2(fpm * lane["miles"])
            lh_var = r2(billed_lh - exp_lh)
            if abs(lh_var) >= 0.01:
                ref, text = self.clause(cid, "RATES")
                f.append(Finding("LINEHAUL_VARIANCE", "Linehaul does not match contracted lane rate",
                                 f"Billed linehaul ${billed_lh:,.2f}; Schedule A rate for {ship['origin_city']}, "
                                 f"{ship['origin_state']} -> {ship['dest_city']}, {ship['dest_state']} is ${exp_lh:,.2f}.",
                                 billed_lh, exp_lh, lh_var, ref, text))
            fsc_var = r2(billed_fsc - exp_fsc)
            if abs(fsc_var) >= 0.01:
                ref, text = self.clause(cid, "FUEL")
                bpm = inv.get("fuel_surcharge_per_mile")
                shown = f"${_num(bpm):.2f}/mi" if bpm not in (None, "") else f"${billed_fsc:,.2f}"
                f.append(Finding("FUEL_VARIANCE", "Fuel surcharge does not match contract formula",
                                 f"Billed fuel {shown}; contract formula (${doe:.3f} - ${contract['fsc_peg']:.2f}) / "
                                 f"{contract['fsc_mpg']:.1f} = ${fpm:.2f}/mi x {lane['miles']} mi = ${exp_fsc:,.2f}.",
                                 billed_fsc, exp_fsc, fsc_var, ref, text))

        # ---------------- accessorials
        authorized = set(filter(None, (ship["authorized_accessorials"] or "").split(",")))
        allowed_acc = 0.0
        for line in inv.get("accessorials") or []:
            code = self.acc_code(line)
            amt = r2(_num(line.get("amount")))
            sched = self.rb.accessorial(cid, code)
            label = line.get("description") or code
            if sched is None:
                ref, text = self.clause(cid, "ACCESSORIAL")
                f.append(Finding("NOT_IN_CONTRACT", f"Accessorial not in contract: {label}",
                                 f"'{label}' (${amt:,.2f}) is not listed in Schedule C of {cid}.", amt, 0.0, amt, ref, text))
                continue
            if sched["requires_authorization"] and code not in authorized:
                ref, text = self.clause(cid, "AUTHORIZATION")
                f.append(Finding("UNAUTHORIZED_ACCESSORIAL", f"Unauthorized accessorial: {sched['description']}",
                                 f"{sched['description']} (${amt:,.2f}) requires authorization, but BOL {ship['bol_number']} "
                                 f"does not request it and no written approval is on file.", amt, 0.0, amt, ref, text))
                continue
            if code == "DET":
                dwell = dwell_hours(ship["dock_in"], ship["dock_out"])
                hrs = self.rb.detention_billable_hours(contract, dwell)
                allowed = r2(hrs * sched["amount"])
                if amt - allowed > 0.01:
                    ref, text = self.clause(cid, "DETENTION")
                    billed_hrs = _num(line.get("quantity"), 0) or (amt / sched["amount"] if sched["amount"] else 0)
                    f.append(Finding("DETENTION_EXCESS", "Detention exceeds dock log",
                                     f"Billed {billed_hrs:g} hrs (${amt:,.2f}). Consignee dock log: in "
                                     f"{ship['dock_in'][11:]} / out {ship['dock_out'][11:]} = {dwell:.2f} hrs on site, less "
                                     f"{contract['detention_free_hours']:g} hrs free time = {hrs:g} billable hrs "
                                     f"(${allowed:,.2f} at ${sched['amount']:.2f}/hr).", amt, allowed, r2(amt - allowed), ref, text))
                allowed_acc += min(amt, allowed)
            elif code == "LUM":
                receipt = ship["lumper_receipt"] or 0.0
                if amt - receipt > 0.01:
                    ref, text = self.clause(cid, "LUMPER")
                    f.append(Finding("LUMPER_UNSUPPORTED", "Lumper not supported by receipt",
                                     f"Billed ${amt:,.2f}; receipt on file ${receipt:,.2f}.", amt, receipt, r2(amt - receipt), ref, text))
                allowed_acc += min(amt, receipt)
            else:
                qty = (ship["stops"] - 1) if code == "STP" else 1
                allowed = r2(sched["amount"] * max(qty, 0))
                if amt - allowed > 0.01:
                    f.append(Finding("ACCESSORIAL_OVER_SCHEDULE", f"{sched['description']} above schedule",
                                     f"Billed ${amt:,.2f}; Schedule C allows ${allowed:,.2f}.", amt, allowed,
                                     r2(amt - allowed), sched["clause_ref"],
                                     (self.rb.clause_by_ref(cid, sched["clause_ref"]) or {"text": None})["text"]))
                allowed_acc += min(amt, allowed)

        expected_total = r2(exp_lh + exp_fsc + allowed_acc)
        res.expected_total = expected_total
        # arithmetic check on the invoice itself
        line_sum = r2(billed_lh + billed_fsc + sum(_num(l.get("amount")) for l in inv.get("accessorials") or []))
        if billed_total - line_sum > 0.05:
            ref, text = self.clause(cid, "RATES")
            f.append(Finding("MATH_ERROR", "Invoice total exceeds sum of its lines",
                             f"Lines sum to ${line_sum:,.2f} but total due is ${billed_total:,.2f}.",
                             billed_total, line_sum, r2(billed_total - line_sum), ref, text))

        variance = r2(billed_total - expected_total)
        categorical = [x for x in f if x.rule in CATEGORICAL and x.impact > 0.009]
        if categorical or variance > TOLERANCE * expected_total:
            if variance <= 0 and not categorical:
                res.decision = "APPROVE"
            else:
                res.decision = "DISPUTE"
                res.overcharge = max(0.0, variance)
                if res.overcharge == 0.0:  # categorical but offset by an undercharge elsewhere
                    res.decision = "APPROVE"
                    res.notes.append("Violations found but offset by undercharges; total within contract.")
        else:
            res.decision = "APPROVE"
            if f:
                res.notes.append(f"Variance ${variance:+,.2f} ({variance / expected_total * 100:+.2f}%) is within the 1% tolerance.")
        self._record(inv, scac, ship, res, record)
        return res

    def _record(self, inv, scac, ship, res, record):
        if not record:
            return
        self.seen.append({"scac": scac, "invoice_number": _norm_id(inv.get("invoice_number")),
                          "invoice_number_raw": inv.get("invoice_number"), "decision": res.decision,
                          "bol_number": ship["bol_number"] if ship is not None else None})
