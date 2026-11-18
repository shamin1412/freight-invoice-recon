"""Eval: baseline prompt (LLM extracts and judges) vs refined prompt + rule engine.

    python -m eval.run_eval                     # both arms, all 50 invoices
    python -m eval.run_eval --arms refined --limit 5
    python -m eval.run_eval --arms oracle       # rules on answer-key data, no API calls (engine check)

Arms
----
baseline : BASELINE_PROMPT extraction, then Claude decides APPROVE / DISPUTE / EXCEPTION and the
           overcharge, given the same contract, rate, fuel and BOL data the rule engine uses.
refined  : REFINED_PROMPT extraction, then the deterministic rule engine.
oracle   : answer-key extraction + rule engine. Not a result; it checks the engine in isolation.

Raw API outputs are cached in eval/runs/<arm>/ so metrics can be recomputed without new calls.
Every reported number is computed from these runs against data/answer_key.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from freight import db
from freight.extract import BASELINE_PROMPT, REFINED_PROMPT, EFFORT, extract
from freight.llm import default_model, provider, structured
from freight.pricing import RateBook
from freight.reconcile import Reconciler
from freight.schemas import AuditDecision
from eval.metrics import score

ROOT = Path(__file__).resolve().parent.parent
INV = ROOT / "data" / "invoices"
RUNS = ROOT / "eval" / "runs"
RESULTS = ROOT / "eval" / "results"

JUDGE_PROMPT = """You are a freight audit analyst. Decide whether this carrier invoice should be paid.

Policy:
- APPROVE if the invoice total is within 1% of what the contract supports and nothing is categorically wrong.
- DISPUTE if anything is not payable: duplicate billing (same invoice number, or a shipment already billed),
  accessorials not in the contract or not authorized on the BOL, detention beyond the dock log after free
  time, billed weight/class above the BOL without a reweigh certificate, or rate/fuel errors that put the
  total more than 1% above the contract amount. overcharge_amount = billed total minus the amount the
  contract supports (the full total for a duplicate).
- EXCEPTION if the invoice cannot be matched to a shipment in our BOL log.
Use the data provided; do not assume facts that are not given."""


def judge_context(conn, rb: RateBook, ex: dict, prior: list[dict]) -> str:
    """Contract, rate, fuel and BOL data for the baseline judge (naive exact-match lookups)."""
    scac = (ex.get("carrier_scac") or "").upper()
    if not conn.execute("SELECT 1 FROM carriers WHERE scac=?", (scac,)).fetchone():
        name = (ex.get("carrier_name") or "").lower()
        scac = next((r["scac"] for r in conn.execute("SELECT * FROM carriers")
                     if any(a in name for a in r["aliases"].split("|"))), None)
    parts = [f"EXTRACTED INVOICE:\n{json.dumps(ex, indent=1)}"]
    ship = conn.execute("SELECT * FROM shipments WHERE bol_number=?", (ex.get("bol_number"),)).fetchone()
    parts.append("BOL LOG RECORD:\n" + (json.dumps(dict(ship), indent=1) if ship else "No shipment found for this BOL number."))
    if scac:
        c = conn.execute("SELECT * FROM contracts WHERE scac=?", (scac,)).fetchone()
        parts.append("CONTRACT TERMS:\n" + json.dumps(dict(c), indent=1))
        parts.append("CONTRACT CLAUSES:\n" + "\n".join(f"{r['clause_ref']} [{r['topic']}]: {r['text']}" for r in
                     conn.execute("SELECT * FROM contract_clauses WHERE contract_id=?", (c["contract_id"],))))
        parts.append("SCHEDULE C ACCESSORIALS:\n" + "\n".join(
            f"{r['code']} {r['description']} {r['unit']} ${r['amount']:.2f} auth_required={bool(r['requires_authorization'])}"
            for r in conn.execute("SELECT * FROM accessorial_schedule WHERE contract_id=?", (c["contract_id"],))))
        parts.append("DOE WEEKLY DIESEL (week starting Monday):\n" + "\n".join(
            f"{r['week_start']}: ${r['price']:.3f}" for r in conn.execute("SELECT * FROM doe_diesel")))
        if c["mode"] == "LTL":
            parts.append("FUEL TABLE (DOE price bracket -> %):\n" + "\n".join(
                f"${r['min_price']:.3f}-${r['max_price']:.3f}: {r['pct']:.2f}%" for r in conn.execute(
                    "SELECT * FROM fsc_ltl_table WHERE contract_id=? AND min_price BETWEEN 3.0 AND 4.6", (c["contract_id"],))))
            oz = (ship["origin_zip"] if ship else ex.get("origin_zip") or "")[:3]
            dz = (ship["dest_zip"] if ship else ex.get("dest_zip") or "")[:3]
            parts.append(f"BASE TARIFF $/CWT for lane {oz}xx -> {dz}xx (class, weight break lbs, rate):\n" + "\n".join(
                f"class {r['freight_class']}, {r['min_lbs']}-{r['max_lbs']}: {r['cwt_rate']:.2f}" for r in conn.execute(
                    "SELECT * FROM ltl_tariff WHERE contract_id=? AND orig_zip3=? AND dest_zip3=?", (c["contract_id"], oz, dz))))
        else:
            parts.append("SCHEDULE A LANE RATES:\n" + "\n".join(
                f"{r['orig_zip3']}xx -> {r['dest_zip3']}xx: {r['miles']} mi, linehaul ${r['linehaul']:.2f}" for r in
                conn.execute("SELECT * FROM tl_lane_rates WHERE contract_id=?", (c["contract_id"],))))
    parts.append("INVOICES ALREADY RECEIVED FROM THIS CARRIER:\n" + (
        "\n".join(f"invoice {p.get('invoice_number')} PRO {p.get('pro_number')} BOL {p.get('bol_number')} total {p.get('total_due')}"
                  for p in prior if p.get("carrier_scac") == ex.get("carrier_scac")) or "none"))
    return "\n\n".join(parts)


def judge(ctx: str, model: str, effort: str, prov: str):
    r = structured(JUDGE_PROMPT, AuditDecision, text=ctx, model=model, effort=effort, prov=prov)
    if r.parsed is None:
        return None, r.error, r.seconds, 0, 0
    return r.parsed.model_dump(), None, r.seconds, r.input_tokens, r.output_tokens


def run_extractions(arm: str, files: list[Path], prompt: str, model: str, effort: str, workers: int, fresh: bool, prov: str):
    d = RUNS / prov / arm / "extractions"
    d.mkdir(parents=True, exist_ok=True)

    def one(p: Path):
        out = d / (p.stem + ".json")
        if out.exists() and not fresh:
            cached = json.loads(out.read_text())
            if cached.get("data") is not None:
                return cached
        r = extract(p, prompt=prompt, model=model, effort=effort, prov=prov)
        rec = {"file": p.name, "data": r.data.model_dump() if r.data else None, "error": r.error, "ocr_used": r.ocr_used,
               "seconds": round(r.seconds, 3), "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
               "provider": prov, "model": model, "effort": effort, "at": dt.datetime.now(dt.timezone.utc).isoformat()}
        out.write_text(json.dumps(rec, indent=1))
        print(f"  [{arm}] {p.name}: {'ok' if r.data else r.error} ({r.seconds:.1f}s)", flush=True)
        return rec

    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(one, files))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="baseline,refined")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--provider", default=provider(), choices=["claude", "groq"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--effort", default=EFFORT)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--fresh", action="store_true", help="ignore cached API outputs")
    args = ap.parse_args()
    args.model = args.model or default_model(args.provider)
    print(f"provider={args.provider} model={args.model} effort={args.effort}")

    key = json.loads((ROOT / "data" / "answer_key.json").read_text())
    key.sort(key=lambda k: k["received_order"])
    if args.limit:
        key = key[: args.limit]
    files = [INV / k["file"] for k in key]
    RESULTS.mkdir(parents=True, exist_ok=True)
    summary = {}

    for arm in [a.strip() for a in args.arms.split(",") if a.strip()]:
        print(f"== {arm} ==", flush=True)
        conn = db.connect()
        preds = []
        if arm == "oracle":
            rec = Reconciler(conn)
            for k in key:
                t0 = time.perf_counter()
                r = rec.reconcile(dict(k["truth"]))
                preds.append({"file": k["file"], "extraction": k["truth"], "decision": r.decision,
                              "overcharge": r.overcharge, "findings": [f.rule for f in r.findings],
                              "seconds": time.perf_counter() - t0, "in_tok": 0, "out_tok": 0})
        elif arm == "refined":
            exs = run_extractions(arm, files, REFINED_PROMPT, args.model, args.effort, args.workers, args.fresh, args.provider)
            rec = Reconciler(conn)
            for k, e in zip(key, exs):
                if e["data"] is None:
                    preds.append({"file": k["file"], "extraction": None, "decision": "EXCEPTION", "overcharge": 0.0,
                                  "findings": ["EXTRACTION_FAILED"], "seconds": e["seconds"], "in_tok": 0, "out_tok": 0})
                    continue
                t0 = time.perf_counter()
                r = rec.reconcile(e["data"])
                preds.append({"file": k["file"], "extraction": e["data"], "decision": r.decision,
                              "overcharge": r.overcharge, "findings": [f.rule for f in r.findings],
                              "seconds": e["seconds"] + (time.perf_counter() - t0),
                              "in_tok": e["input_tokens"], "out_tok": e["output_tokens"]})
        elif arm == "baseline":
            exs = run_extractions(arm, files, BASELINE_PROMPT, args.model, args.effort, args.workers, args.fresh, args.provider)
            rb = RateBook(conn)
            jd = RUNS / args.provider / arm / "judgments"
            jd.mkdir(parents=True, exist_ok=True)

            def one(i):
                k, e = key[i], exs[i]
                out = jd / (Path(k["file"]).stem + ".json")
                if out.exists() and not args.fresh:
                    j = json.loads(out.read_text())
                    if j.get("decision") is not None:
                        return j
                if e["data"] is None:
                    return {"decision": None, "error": "extraction failed", "seconds": 0, "in": 0, "out": 0}
                prior = [x["data"] for x in exs[:i] if x["data"]]
                local = db.connect()
                ctx = judge_context(local, RateBook(local), e["data"], prior)
                d, err, secs, it, ot = judge(ctx, args.model, args.effort, args.provider)
                j = {"decision": d, "error": err, "seconds": round(secs, 3), "in": it, "out": ot}
                out.write_text(json.dumps(j, indent=1))
                print(f"  [baseline-judge] {k['file']}: {d['decision'] if d else err}", flush=True)
                return j

            with ThreadPoolExecutor(args.workers) as pool:
                judgments = list(pool.map(one, range(len(key))))
            for k, e, j in zip(key, exs, judgments):
                d = j.get("decision") or {}
                preds.append({"file": k["file"], "extraction": e["data"], "decision": d.get("decision", "EXCEPTION"),
                              "overcharge": float(d.get("overcharge_amount") or 0.0), "findings": d.get("reasons", []),
                              "seconds": e["seconds"] + j.get("seconds", 0),
                              "in_tok": e["input_tokens"] + j.get("in", 0), "out_tok": e["output_tokens"] + j.get("out", 0)})
        else:
            raise SystemExit(f"unknown arm {arm}")

        m = score(key, preds)
        m["provider"], m["model"], m["effort"] = (args.provider, args.model, args.effort) if arm != "oracle" else (None, None, None)
        if args.provider != "claude" and arm != "oracle":
            m["est_cost_usd"] = None  # token counts are reported; see the provider's price list
        summary[arm] = m
        (RESULTS / f"{arm}_predictions.json").write_text(json.dumps(preds, indent=1, default=str))
        print(json.dumps({k: v for k, v in m.items() if k != "per_field"}, indent=1))

    prev = json.loads((RESULTS / "summary.json").read_text()) if (RESULTS / "summary.json").exists() else {}
    prev.update(summary)
    prev["_meta"] = {"invoices": len(key), "generated_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    (RESULTS / "summary.json").write_text(json.dumps(prev, indent=1))
    from eval.report import write_report
    write_report(prev, RESULTS / "results.md")
    print(f"wrote {RESULTS / 'summary.json'} and results.md")


if __name__ == "__main__":
    main()
