# Eval results

Invoices: 50  
Generated: 2026-11-19T07:03:58.656323+00:00

| Metric | baseline | refined | oracle |
|---|---|---|---|
| Extraction field accuracy | 85.1% | 95.3% | 100.0% |
| Invoices with every field correct | 1 | 32 | 50 |
| Decision accuracy (approve / dispute / exception) | 76.0% | 96.0% | 100.0% |
| Touchless rate (auto-approved) | 46.0% | 66.0% | 64.0% |
| Touchless ceiling (share of invoices that are clean) | 64.0% | 64.0% | 64.0% |
| Clean invoices auto-approved | 22/32 | 32/32 | 32/32 |
| Bad invoices auto-approved (leakage) | 1 | 1 | 0 |
| Error invoices flagged | 17/18 | 17/18 | 18/18 |
| Clean invoices wrongly flagged | 10 | 0 | 0 |
| Overcharges planted | $5,668.09 | $5,668.09 | $5,668.09 |
| Overcharges caught | $5,201.61 | $5,293.09 | $5,668.09 |
| Dispute amounts exactly right | 10/17 | 15/17 | 17/17 |
| Total amount flagged | $6,121.29 | $5,293.09 | $5,668.09 |
| Seconds per invoice (mean) | 42.36 | 23.69 | 0.0 |
| Seconds per invoice (median) | 36.85 | 22.12 | 0.0 |
| API cost for the run | n/a | n/a | $0.00 |

`oracle` runs the rule engine on answer-key data (no LLM). It checks the engine, it is not a result.

## Field accuracy by field

| Field | baseline | refined | oracle |
|---|---|---|---|
| carrier_scac | 32.0% | 98.0% | 100.0% |
| invoice_number | 82.0% | 92.0% | 100.0% |
| invoice_date | 96.0% | 96.0% | 100.0% |
| pro_number | 90.0% | 90.0% | 100.0% |
| bol_number | 90.0% | 100.0% | 100.0% |
| ship_date | 84.0% | 86.0% | 100.0% |
| origin_zip | 96.0% | 88.0% | 100.0% |
| dest_zip | 98.0% | 98.0% | 100.0% |
| mode | 86.0% | 98.0% | 100.0% |
| billed_weight_lbs | 88.0% | 98.0% | 100.0% |
| freight_class | 64.3% | 85.7% | 100.0% |
| miles | 100.0% | 100.0% | 100.0% |
| linehaul_amount | 90.0% | 98.0% | 100.0% |
| fuel_surcharge_amount | 94.0% | 98.0% | 100.0% |
| accessorials | 74.0% | 100.0% | 100.0% |
| total_due | 96.0% | 98.0% | 100.0% |
