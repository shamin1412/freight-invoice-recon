"""Write eval/results/results.md from summary.json."""
from __future__ import annotations

from pathlib import Path

ROWS = [
    ("Extraction field accuracy", "extraction_field_accuracy", "pct"),
    ("Invoices with every field correct", "extraction_invoices_all_fields_correct", "raw"),
    ("Decision accuracy (approve / dispute / exception)", "decision_accuracy", "pct"),
    ("Touchless rate (auto-approved)", "touchless_rate", "pct"),
    ("Touchless ceiling (share of invoices that are clean)", "touchless_ceiling", "pct"),
    ("Clean invoices auto-approved", "clean_invoices_auto_approved", "raw"),
    ("Bad invoices auto-approved (leakage)", "bad_invoices_auto_approved", "raw"),
    ("Error invoices flagged", "error_invoices_flagged", "raw"),
    ("Clean invoices wrongly flagged", "clean_invoices_flagged", "raw"),
    ("Overcharges planted", "overcharge_planted", "usd"),
    ("Overcharges caught", "overcharge_caught", "usd"),
    ("Dispute amounts exactly right", "overcharge_amount_exact", "raw"),
    ("Total amount flagged", "overcharge_flagged_total", "usd"),
    ("Seconds per invoice (mean)", "seconds_per_invoice_mean", "raw"),
    ("Seconds per invoice (median)", "seconds_per_invoice_median", "raw"),
    ("API cost for the run", "est_cost_usd", "usd"),
]


def fmt(v, kind):
    if v is None:
        return "n/a"
    if kind == "pct":
        return f"{v * 100:.1f}%"
    if kind == "usd":
        return f"${v:,.2f}"
    return str(v)


def write_report(summary: dict, path: Path):
    arms = [a for a in ("baseline", "refined", "oracle") if a in summary]
    lines = ["# Eval results", "", f"Invoices: {summary.get('_meta', {}).get('invoices')}  ",
             f"Generated: {summary.get('_meta', {}).get('generated_at')}", "",
             "| Metric | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    for label, key, kind in ROWS:
        lines.append(f"| {label} | " + " | ".join(fmt(summary[a].get(key), kind) for a in arms) + " |")
    lines += ["", "`oracle` runs the rule engine on answer-key data (no LLM). It checks the engine, it is not a result.", "",
              "## Field accuracy by field", "", "| Field | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    fields = list(summary[arms[0]].get("per_field", {}))
    for f in fields:
        lines.append(f"| {f} | " + " | ".join(fmt(summary[a]["per_field"].get(f), "pct") for a in arms) + " |")
    path.write_text("\n".join(lines) + "\n")
