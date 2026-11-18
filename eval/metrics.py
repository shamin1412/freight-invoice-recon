"""Scoring against the answer key."""
from __future__ import annotations

import re
import statistics

from freight.pricing import normalize_class

PRICE_IN, PRICE_OUT = 4.00, 20.00  # Claude Opus 5.5, $ per million tokens
ID_FIELDS = ["invoice_number", "pro_number", "bol_number"]
FIELDS = ["carrier_scac", "invoice_number", "invoice_date", "pro_number", "bol_number", "ship_date", "origin_zip",
          "dest_zip", "mode", "billed_weight_lbs", "freight_class", "miles", "linehaul_amount",
          "fuel_surcharge_amount", "accessorials", "total_due"]


def _id(x):
    return re.sub(r"[^A-Z0-9]", "", str(x or "").upper())


def field_ok(name, truth, pred) -> bool:
    t, p = truth.get(name), (pred or {}).get(name)
    if name in ID_FIELDS:
        return _id(t) == _id(p)
    if name in ("billed_weight_lbs",):
        return p is not None and abs(float(t) - float(p)) <= 0.5
    if name in ("linehaul_amount", "fuel_surcharge_amount", "total_due"):
        return p is not None and abs(float(t) - float(p)) <= 0.011
    if name == "miles":
        return p is not None and int(t) == int(p)
    if name == "freight_class":
        return normalize_class(t) == normalize_class(p)
    if name == "accessorials":
        tl = sorted((a["code"], round(float(a["amount"]), 2)) for a in t)
        pl = sorted(((a.get("code") or "").upper(), round(float(a.get("amount") or 0), 2)) for a in (p or []))
        return tl == pl
    if name in ("carrier_scac", "mode"):
        return str(t or "").upper() == str(p or "").upper()
    return str(t or "").strip() == str(p or "").strip()


def applicable(name, truth):
    if name == "freight_class":
        return truth["mode"] == "LTL"
    if name == "miles":
        return truth["mode"] == "TL"
    return True


def score(key: list[dict], preds: list[dict]) -> dict:
    by_file = {p["file"]: p for p in preds}
    n = len(key)
    per_field = {f: [0, 0] for f in FIELDS}
    inv_perfect = 0
    for k in key:
        p = by_file[k["file"]]
        all_ok = True
        for f in FIELDS:
            if not applicable(f, k["truth"]):
                continue
            ok = p["extraction"] is not None and field_ok(f, k["truth"], p["extraction"])
            per_field[f][0] += ok
            per_field[f][1] += 1
            all_ok &= ok
        inv_perfect += all_ok
    tot_ok = sum(v[0] for v in per_field.values())
    tot = sum(v[1] for v in per_field.values())

    should_approve = [k for k in key if k["expected_decision"] == "APPROVE"]
    errors = [k for k in key if k["expected_decision"] != "APPROVE"]
    disputes = [k for k in key if k["expected_decision"] == "DISPUTE"]
    approved = [k for k in key if by_file[k["file"]]["decision"] == "APPROVE"]
    correct_appr = [k for k in approved if k["expected_decision"] == "APPROVE"]
    caught, exact = 0.0, 0
    for k in disputes:
        p = by_file[k["file"]]
        if p["decision"] == "DISPUTE" and p["overcharge"] > 0:
            caught += min(p["overcharge"], k["true_overcharge"])
            exact += abs(p["overcharge"] - k["true_overcharge"]) <= 0.05
    flagged = sum(by_file[k["file"]]["overcharge"] for k in key if by_file[k["file"]]["decision"] == "DISPUTE")
    secs = [p["seconds"] for p in preds]
    in_tok = sum(p.get("in_tok", 0) for p in preds)
    out_tok = sum(p.get("out_tok", 0) for p in preds)
    return {
        "invoices": n,
        "extraction_field_accuracy": round(tot_ok / tot, 4) if tot else None,
        "extraction_invoices_all_fields_correct": inv_perfect,
        "decision_accuracy": round(sum(by_file[k["file"]]["decision"] == k["expected_decision"] for k in key) / n, 4),
        "touchless_rate": round(len(approved) / n, 4),
        "touchless_ceiling": round(len(should_approve) / n, 4),
        "clean_invoices_auto_approved": f"{len(correct_appr)}/{len(should_approve)}",
        "bad_invoices_auto_approved": len(approved) - len(correct_appr),
        "error_invoices_flagged": f"{sum(by_file[k['file']]['decision'] != 'APPROVE' for k in errors)}/{len(errors)}",
        "clean_invoices_flagged": sum(by_file[k["file"]]["decision"] != "APPROVE" for k in should_approve),
        "overcharge_planted": round(sum(k["true_overcharge"] for k in disputes), 2),
        "overcharge_caught": round(caught, 2),
        "overcharge_amount_exact": f"{exact}/{len(disputes)}",
        "overcharge_flagged_total": round(flagged, 2),
        "seconds_per_invoice_mean": round(statistics.mean(secs), 2) if secs else None,
        "seconds_per_invoice_median": round(statistics.median(secs), 2) if secs else None,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "est_cost_usd": round(in_tok / 1e6 * PRICE_IN + out_tok / 1e6 * PRICE_OUT, 2),
        "per_field": {f: round(v[0] / v[1], 3) for f, v in per_field.items() if v[1]},
    }
