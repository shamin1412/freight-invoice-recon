# Eval results

Invoices: 50  
Generated: 2026-11-18T05:59:17.715160+00:00

| Metric | oracle |
|---|---|
| Extraction field accuracy | 100.0% |
| Invoices with every field correct | 50 |
| Decision accuracy (approve / dispute / exception) | 100.0% |
| Touchless rate (auto-approved) | 64.0% |
| Touchless ceiling (share of invoices that are clean) | 64.0% |
| Clean invoices auto-approved | 32/32 |
| Bad invoices auto-approved (leakage) | 0 |
| Error invoices flagged | 18/18 |
| Clean invoices wrongly flagged | 0 |
| Overcharges planted | $5,668.09 |
| Overcharges caught | $5,668.09 |
| Dispute amounts exactly right | 17/17 |
| Total amount flagged | $5,668.09 |
| Seconds per invoice (mean) | 0.0 |
| Seconds per invoice (median) | 0.0 |
| API cost for the run | $0.00 |

`oracle` runs the rule engine on answer-key data (no LLM). It checks the engine, it is not a result.

## Field accuracy by field

| Field | oracle |
|---|---|
| carrier_scac | 100.0% |
| invoice_number | 100.0% |
| invoice_date | 100.0% |
| pro_number | 100.0% |
| bol_number | 100.0% |
| ship_date | 100.0% |
| origin_zip | 100.0% |
| dest_zip | 100.0% |
| mode | 100.0% |
| billed_weight_lbs | 100.0% |
| freight_class | 100.0% |
| miles | 100.0% |
| linehaul_amount | 100.0% |
| fuel_surcharge_amount | 100.0% |
| accessorials | 100.0% |
| total_due | 100.0% |
