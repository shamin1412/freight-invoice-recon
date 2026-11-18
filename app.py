"""Streamlit dashboard for the touchless freight invoice reconciliation demo.

    streamlit run app.py
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from freight import db
from freight.dispute import draft_dispute
from freight.reconcile import Reconciler

ROOT = Path(__file__).resolve().parent
INV = ROOT / "data" / "invoices"
RES = ROOT / "eval" / "results"

st.set_page_config(page_title="Touchless Freight Audit", layout="wide")


@st.cache_data
def load_key():
    k = json.loads((ROOT / "data" / "answer_key.json").read_text())
    return sorted(k, key=lambda x: x["received_order"])


@st.cache_data
def load_summary():
    p = RES / "summary.json"
    return json.loads(p.read_text()) if p.exists() else {}


def available_arms():
    return [a for a in ("refined", "baseline", "oracle") if (RES / f"{a}_predictions.json").exists()]


@st.cache_data
def replay(arm: str):
    """Re-run the rule engine on the stored extractions (deterministic) to get full findings and drafts."""
    preds = json.loads((RES / f"{arm}_predictions.json").read_text())
    if arm == "baseline":
        return {p["file"]: {"pred": p, "result": None, "draft": ""} for p in preds}
    conn = db.connect()
    rec = Reconciler(conn)
    out = {}
    for p in preds:
        if p["extraction"] is None:
            out[p["file"]] = {"pred": p, "result": None, "draft": ""}
            continue
        r = rec.reconcile(dict(p["extraction"]))
        name = conn.execute("SELECT name FROM carriers WHERE scac=?", (r.carrier_scac,)).fetchone()
        out[p["file"]] = {"pred": p, "result": r.to_dict(), "draft": draft_dispute(r, p["extraction"], name["name"] if name else None)}
    return out


def show_document(path: Path):
    if path.suffix == ".pdf":
        b64 = base64.b64encode(path.read_bytes()).decode()
        st.markdown(f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="720" style="border:1px solid #ddd"></iframe>',
                    unsafe_allow_html=True)
        st.download_button("Download PDF", path.read_bytes(), file_name=path.name)
    else:
        st.code(path.read_text(), language=None)


key = load_key()
summary = load_summary()
arms = available_arms()

st.title("Touchless Freight Invoice Reconciliation")
st.caption("Claude extracts each invoice into a Pydantic schema. A SQL/Python rule engine checks it against contracted "
           "rates, the DOE fuel table, the accessorial schedule and the BOL log. Clean invoices within 1% are approved "
           "without a human; the rest get a dispute draft citing the contract clause.")

tab_over, tab_queue, tab_live, tab_ref = st.tabs(["Results", "Invoice queue", "Run an invoice", "Reference data"])

# ---------------------------------------------------------------- Results
with tab_over:
    real = [a for a in ("baseline", "refined") if a in summary]
    if not real:
        st.warning("No live eval run yet. Showing the rule-engine check on answer-key data only. "
                   "Run `python -m eval.run_eval` with ANTHROPIC_API_KEY set to produce real metrics.")
    show = real or [a for a in ("oracle",) if a in summary]
    if show:
        main_arm = "refined" if "refined" in show else show[0]
        m = summary[main_arm]
        b = summary.get("baseline")
        st.subheader(f"{'Refined prompt + rule engine' if main_arm == 'refined' else main_arm} · {m['invoices']} invoices"
                     + (f" · {m.get('provider', '')} {m.get('model')}" if m.get("model") else ""))
        c = st.columns(4)

        def delta(k, pct=True):
            if not b or main_arm == "baseline" or b.get(k) is None:
                return None
            d = m[k] - b[k]
            return f"{d * 100:+.1f} pts vs baseline" if pct else f"{d:+,.2f} vs baseline"

        c[0].metric("Extraction accuracy", f"{m['extraction_field_accuracy'] * 100:.1f}%", delta("extraction_field_accuracy"))
        c[1].metric("Touchless rate", f"{m['touchless_rate'] * 100:.1f}%", delta("touchless_rate"),
                    help=f"Ceiling is {m['touchless_ceiling'] * 100:.0f}%: only clean invoices should be auto-approved.")
        c[2].metric("Overcharges caught", f"${m['overcharge_caught']:,.2f}",
                    f"of ${m['overcharge_planted']:,.2f} planted", delta_color="off")
        c[3].metric("Seconds per invoice", f"{m['seconds_per_invoice_mean']:.1f}s",
                    "vs ~8 min manual (assumed)", delta_color="off")
        c = st.columns(4)
        c[0].metric("Decision accuracy", f"{m['decision_accuracy'] * 100:.1f}%", delta("decision_accuracy"))
        c[1].metric("Bad invoices auto-approved", m["bad_invoices_auto_approved"], delta_color="off")
        c[2].metric("Clean invoices wrongly flagged", m["clean_invoices_flagged"], delta_color="off")
        c[3].metric("API cost for 50 invoices", f"${m['est_cost_usd']:.2f}" if m.get("est_cost_usd") is not None
                    else f"{(m['input_tokens'] + m['output_tokens']) / 1000:,.0f}k tokens", delta_color="off")
        st.markdown("#### All arms")
        md = (RES / "results.md").read_text() if (RES / "results.md").exists() else ""
        st.markdown(md.split("## Field accuracy")[0].replace("# Eval results", ""))
        with st.expander("Field accuracy by field"):
            st.markdown("## Field accuracy" + md.split("## Field accuracy")[1] if "## Field accuracy" in md else "")

# ---------------------------------------------------------------- Queue
with tab_queue:
    if not arms:
        st.info("Run the eval first.")
    else:
        arm = st.radio("Pipeline", arms, horizontal=True,
                       format_func=lambda a: {"refined": "Refined + rules", "baseline": "Baseline (LLM judge)",
                                              "oracle": "Rules on answer key"}[a])
        data = replay(arm)
        rows = []
        for k in key:
            d = data.get(k["file"])
            if not d:
                continue
            p = d["pred"]
            rows.append({"#": k["received_order"], "file": k["file"], "carrier": k["truth"]["carrier_scac"],
                         "format": k["format"], "billed": k["truth"]["total_due"], "decision": p["decision"],
                         "disputed $": round(p["overcharge"], 2), "expected": k["expected_decision"],
                         "planted": ", ".join(k["errors"]) or ("within tolerance" if "TOLERANCE" in k["planted"] else "clean"),
                         "match": "✓" if p["decision"] == k["expected_decision"] else "✗"})
        df = pd.DataFrame(rows)
        f1, f2 = st.columns(2)
        dec = f1.multiselect("Decision", sorted(df["decision"].unique()), default=list(sorted(df["decision"].unique())))
        car = f2.multiselect("Carrier", sorted(df["carrier"].unique()), default=list(sorted(df["carrier"].unique())))
        view = df[df["decision"].isin(dec) & df["carrier"].isin(car)]
        st.dataframe(view, hide_index=True, use_container_width=True,
                     column_config={"billed": st.column_config.NumberColumn(format="$%.2f"),
                                    "disputed $": st.column_config.NumberColumn(format="$%.2f")})
        pick = st.selectbox("Open invoice", view["file"].tolist())
        if pick:
            k = next(x for x in key if x["file"] == pick)
            d = data[pick]
            left, right = st.columns([1, 1])
            with left:
                st.markdown(f"**{pick}** · {k['format']}")
                show_document(INV / pick)
            with right:
                p = d["pred"]
                color = {"APPROVE": "green", "DISPUTE": "red", "EXCEPTION": "orange"}.get(p["decision"], "gray")
                st.markdown(f"### :{color}[{'TOUCHLESS APPROVED' if p['decision'] == 'APPROVE' else p['decision']}]")
                if d["result"]:
                    r = d["result"]
                    exp = f"${r['expected_total']:,.2f}" if r["expected_total"] is not None else "n/a"
                    st.write(f"Billed **${r['billed_total']:,.2f}** · contract supports **{exp}** · "
                             f"disputed **${r['overcharge']:,.2f}** · contract {r['contract_id']} · BOL {r['bol_number']}")
                    for n in r["notes"]:
                        st.info(n)
                    for f in r["findings"]:
                        st.markdown(f"- **{f['title']}** (+${f['impact']:,.2f}): {f['detail']}  \n"
                                    f"  _{f['clause_ref'] or ''}_ {('“' + f['clause_text'] + '”') if f['clause_text'] else ''}")
                    if d["draft"]:
                        st.markdown("**Dispute draft**")
                        st.code(d["draft"], language=None)
                elif p.get("findings"):
                    st.markdown("**LLM reasons**")
                    for x in p["findings"]:
                        st.markdown(f"- {x}")
                st.markdown(f"**Answer key:** {k['expected_decision']}, overcharge ${k['true_overcharge']:,.2f}, "
                            f"planted: {', '.join(k['planted']) or 'none'}")
                if p["extraction"]:
                    with st.expander("Extracted fields vs answer key"):
                        from eval.metrics import FIELDS, applicable, field_ok
                        comp = [{"field": f, "extracted": json.dumps(p["extraction"].get(f)),
                                 "truth": json.dumps(k["truth"].get(f)),
                                 "ok": "✓" if field_ok(f, k["truth"], p["extraction"]) else "✗"}
                                for f in FIELDS if applicable(f, k["truth"])]
                        st.dataframe(pd.DataFrame(comp), hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- Live
with tab_live:
    st.markdown("Run one invoice through the live pipeline (LLM extraction + rule engine). Needs `ANTHROPIC_API_KEY` or `GROQ_API_KEY`.")
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("GROQ_API_KEY"))
    if not has_key:
        st.warning("No ANTHROPIC_API_KEY or GROQ_API_KEY in this environment.")
    src = st.radio("Source", ["Sample invoice", "Upload"], horizontal=True)
    path = None
    if src == "Sample invoice":
        f = st.selectbox("Invoice", [k["file"] for k in key])
        path = INV / f
    else:
        up = st.file_uploader("Invoice (PDF or text)", type=["pdf", "txt"])
        if up:
            tmp = Path(tempfile.mkdtemp()) / up.name
            tmp.write_bytes(up.getvalue())
            path = tmp
    st.caption("Duplicate detection only sees invoices processed in this session.")
    if path and st.button("Process", disabled=not has_key, type="primary"):
        from freight.extract import extract
        if "live_rec" not in st.session_state:
            st.session_state.live_rec = Reconciler(db.connect())
        with st.spinner("Extracting with Claude..."):
            ex = extract(path)
        if ex.data is None:
            st.error(f"Extraction failed: {ex.error}")
        else:
            inv = ex.data.model_dump()
            r = st.session_state.live_rec.reconcile(inv)
            st.success(f"{r.decision} · billed ${r.billed_total:,.2f} · disputed ${r.overcharge:,.2f} · {ex.seconds:.1f}s")
            c1, c2 = st.columns(2)
            c1.json(inv)
            draft = draft_dispute(r, inv)
            c2.json(r.to_dict())
            if draft:
                st.code(draft, language=None)

# ---------------------------------------------------------------- Reference
with tab_ref:
    conn = db.connect()
    which = st.selectbox("Table", ["contracts", "contract_clauses", "accessorial_schedule", "shipments", "tl_lane_rates",
                                   "doe_diesel", "fsc_ltl_table", "carriers"])
    st.dataframe(pd.read_sql_query(f"SELECT * FROM {which}", conn), hide_index=True, use_container_width=True)
