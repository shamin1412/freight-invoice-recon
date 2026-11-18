"""Contract pricing: what an invoice *should* cost, computed from the SQLite rate tables.

Both the synthetic data generator and the reconciliation engine use this module, so the
answer key and the engine agree on how a correct invoice is priced. The engine never sees
the answer key; it only sees what the LLM extracted from the invoice document.
"""
from __future__ import annotations

import datetime as dt
import math
import sqlite3
from dataclasses import dataclass


def r2(x: float) -> float:
    return float(f"{x + 1e-9:.2f}") if x >= 0 else -float(f"{-x + 1e-9:.2f}")


def week_start(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


@dataclass
class LTLLinehaul:
    cwt_rate: float
    gross: float
    discount_pct: float
    discount: float
    net: float
    min_applied: bool


class RateBook:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---------- lookups ----------
    def contract_for(self, scac: str, ship_date: dt.date) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM contracts WHERE scac=? AND effective_from<=? AND effective_to>=?",
            (scac, ship_date.isoformat(), ship_date.isoformat()),
        ).fetchone()

    def clause(self, contract_id: str, topic: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM contract_clauses WHERE contract_id=? AND topic=? ORDER BY clause_ref LIMIT 1",
            (contract_id, topic),
        ).fetchone()

    def clause_by_ref(self, contract_id: str, ref: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM contract_clauses WHERE contract_id=? AND clause_ref=?", (contract_id, ref)
        ).fetchone()

    def doe_price(self, ship_date: dt.date) -> float:
        row = self.conn.execute(
            "SELECT price FROM doe_diesel WHERE week_start=?", (week_start(ship_date).isoformat(),)
        ).fetchone()
        if row is None:
            raise KeyError(f"no DOE price for week of {ship_date}")
        return row["price"]

    def accessorial(self, contract_id: str, code: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM accessorial_schedule WHERE contract_id=? AND code=?", (contract_id, code)
        ).fetchone()

    # ---------- LTL ----------
    def ltl_linehaul(self, contract: sqlite3.Row, orig_zip: str, dest_zip: str,
                     weight_lbs: float, freight_class: str) -> LTLLinehaul | None:
        row = self.conn.execute(
            """SELECT cwt_rate FROM ltl_tariff WHERE contract_id=? AND orig_zip3=? AND dest_zip3=?
               AND freight_class=? AND min_lbs<=? AND max_lbs>?""",
            (contract["contract_id"], orig_zip[:3], dest_zip[:3], normalize_class(freight_class),
             weight_lbs, weight_lbs),
        ).fetchone()
        if row is None:
            return None
        cwt = row["cwt_rate"]
        gross = r2(weight_lbs / 100.0 * cwt)
        disc = r2(gross * contract["discount_pct"] / 100.0)
        net = r2(gross - disc)
        min_applied = net < contract["min_charge"]
        if min_applied:
            net = contract["min_charge"]
            disc = r2(gross - net)
        return LTLLinehaul(cwt, gross, contract["discount_pct"], disc, net, min_applied)

    def ltl_fsc_pct(self, contract: sqlite3.Row, doe: float) -> float:
        row = self.conn.execute(
            "SELECT pct FROM fsc_ltl_table WHERE contract_id=? AND min_price<=? AND max_price>=?",
            (contract["contract_id"], doe, doe),
        ).fetchone()
        return row["pct"] if row else 0.0

    # ---------- TL ----------
    def tl_lane(self, contract: sqlite3.Row, orig_zip: str, dest_zip: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM tl_lane_rates WHERE contract_id=? AND orig_zip3=? AND dest_zip3=?",
            (contract["contract_id"], orig_zip[:3], dest_zip[:3]),
        ).fetchone()

    @staticmethod
    def tl_fsc_per_mile(contract: sqlite3.Row, doe: float) -> float:
        return max(0.0, r2((doe - contract["fsc_peg"]) / contract["fsc_mpg"]))

    @staticmethod
    def detention_billable_hours(contract: sqlite3.Row, dwell_hours: float) -> float:
        over = max(0.0, dwell_hours - contract["detention_free_hours"])
        inc = contract["detention_increment_hours"] or 1.0
        return math.floor(over / inc + 1e-9) * inc


CLASS_ALIASES = {"77": "77.5", "92": "92.5", "77.50": "77.5", "92.50": "92.5"}


def normalize_class(c) -> str:
    if c is None:
        return ""
    s = str(c).strip().upper().replace("CLASS", "").replace("CL", "").strip()
    try:
        f = float(s)
        s = ("%g" % f)
    except ValueError:
        pass
    return CLASS_ALIASES.get(s, s)


def dwell_hours(dock_in: str | None, dock_out: str | None) -> float:
    if not dock_in or not dock_out:
        return 0.0
    a = dt.datetime.fromisoformat(dock_in)
    b = dt.datetime.fromisoformat(dock_out)
    return (b - a).total_seconds() / 3600.0
