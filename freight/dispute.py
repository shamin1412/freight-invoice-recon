"""Dispute summaries that cite the exact contract clause for each finding.

The draft is built deterministically from the engine's findings, so every number and clause
reference is traceable. `polish_with_claude` optionally rewrites it as a carrier-facing email
without changing any figure.
"""
from __future__ import annotations

import os

from freight.reconcile import Reconciliation


def draft_dispute(res: Reconciliation, inv: dict, carrier_name: str | None = None) -> str:
    if res.decision != "DISPUTE":
        return ""
    carrier = carrier_name or inv.get("carrier_name") or res.carrier_scac
    supported = res.expected_total if res.expected_total is not None else 0.0
    lines = [
        f"FREIGHT BILL DISPUTE - {carrier} ({res.carrier_scac})",
        f"Invoice {inv.get('invoice_number')} | PRO {inv.get('pro_number')} | BOL {res.bol_number} | Contract {res.contract_id}",
        "",
        f"Amount billed:            ${res.billed_total:,.2f}",
        f"Supported by contract:    ${supported:,.2f}",
        f"Disputed (short-paid):    ${res.overcharge:,.2f}",
        "",
        "Findings:",
    ]
    n = 0
    for f in res.findings:
        if f.impact <= 0.009:
            continue
        n += 1
        lines.append(f"{n}. {f.title} (+${f.impact:,.2f})")
        lines.append(f"   {f.detail}")
        if f.clause_ref:
            lines.append(f"   Contract {res.contract_id} {f.clause_ref}: \"{f.clause_text}\"")
        lines.append("")
    if any(f.rule == "DUPLICATE" for f in res.findings):
        lines.append("Requested action: void this invoice. No payment will be issued.")
    else:
        lines.append(f"Requested action: issue a corrected invoice for ${supported:,.2f}, or provide supporting "
                     f"documentation (signed BOL notation, written approval, W&I certificate or facility in/out times) "
                     f"within 30 days. The undisputed balance will be paid on normal terms.")
    return "\n".join(lines)


def polish_with_claude(draft: str, model: str | None = None) -> str:
    """Optional: turn the structured draft into a short, professional email. Figures are locked."""
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model or os.environ.get("FREIGHT_MODEL", "claude-opus-5-5"),
        max_tokens=4000,
        output_config={"effort": "low"},
        system=("Rewrite the freight bill dispute below as a concise, courteous email to the carrier's billing "
                "department. Keep every dollar amount, identifier and quoted contract clause exactly as given. "
                "Do not add claims, amounts or clauses that are not in the draft. Output only the email."),
        messages=[{"role": "user", "content": draft}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")
