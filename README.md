# Touchless Freight Invoice Reconciliation

An end-to-end pipeline that reads messy carrier freight invoices (PDFs, scanned PDFs, fixed-width
printouts, emails and EDI 210), extracts them with Claude into a Pydantic schema, reconciles them
against contracted rates and the Bill of Lading log in SQLite, and either approves them without a
human ("touchless") or drafts a dispute that cites the exact contract clause.

```
invoice (PDF / scan / text / EDI 210)
   │  Claude structured output  ->  InvoiceExtraction (Pydantic)
   ▼
rule engine (SQLite + Python)
   ├─ match BOL / PRO in the shipment log      -> no match: EXCEPTION (human)
   ├─ duplicate invoice # or shipment already paid
   ├─ linehaul vs contract (LTL tariff, discount, min charge / TL lane rate)
   ├─ fuel vs DOE diesel week of pickup (LTL % table / TL per-mile formula)
   ├─ weight & class vs BOL (W&I certificate rule)
   ├─ accessorials vs Schedule C and BOL authorization, detention vs dock log, lumper vs receipt
   └─ invoice arithmetic
   ▼
TOUCHLESS APPROVED (total within 1%, nothing categorical)  |  DISPUTE + clause-cited draft
```

## Results

> **Pending the live run.** The numbers in this section are produced by `python -m eval.run_eval`
> and copied from `eval/results/results.md`. Nothing here is estimated.

| Metric | Baseline prompt (LLM judges) | Refined prompt + rule engine |
|---|---|---|
| Extraction field accuracy | _pending_ | _pending_ |
| Touchless rate | _pending_ | _pending_ |
| Overcharges caught (of $5,668.09 planted) | _pending_ | _pending_ |
| Seconds per invoice | _pending_ | _pending_ |

**Ceilings to keep in mind.** 32 of the 50 invoices are clean (4 of them have a rounding variance under
1%), so the highest correct touchless rate on this set is **64%**. The brief's 78% would require
approving bad invoices. The "~8 minutes per manual audit" figure is an assumption from the brief, not
something measured here.

## The synthetic data

All companies, people and addresses are fictional. The *structure* follows real practice:

| Real-world convention | How it is modeled |
|---|---|
| LTL priced as a discount off the carrier's base tariff ($/CWT by lane, NMFC class, weight break) with an absolute minimum charge | `ltl_tariff`, `contracts.discount_pct`, `contracts.min_charge` |
| LTL fuel surcharge = % from a carrier table keyed to the weekly DOE/EIA on-highway diesel average, applied to net linehaul | `fsc_ltl_table`, `doe_diesel` |
| Truckload fuel = (DOE price - $1.25 peg) / MPG per mile (6.0 van, 5.5 reefer, 5.0 flatbed) | `contracts.fsc_peg`, `fsc_mpg` |
| Accessorials (liftgate, residential, inside, notify, limited access, hazmat, detention, stop-off, lumper, layover, TONU, tarp) payable only per schedule, most requiring BOL authorization | `accessorial_schedule`, `shipments.authorized_accessorials` |
| Detention: 2 hours free, then hourly, supported by facility in/out times | `shipments.dock_in/dock_out`, contract increments |
| BOL weight and class govern unless the carrier provides a W&I certificate | `shipments.reweigh_certificate` |

**Six carriers, six layouts:** Ridgeline (classic LTL freight bill PDF), Prairie Express (fixed-width
dot-matrix printout), Bluewater (modern PDF with codes and LB/KG), Ironhorse (truckload PDF with dock
times), Coldchain (invoice pasted in an email), Summit Flatbed (ANSI X12 EDI 210). Six PDFs are
rasterized with skew and noise to look scanned. Date formats, wording of charges and ID formats differ by
carrier. The BOL log also holds 24 shipments that were never invoiced.

**50 invoices, planted conditions** (`data/answer_key.json` has the truth for every field, the expected
decision and the true overcharge):

| Condition | Invoices |
|---|---|
| Clean | 28 |
| Variance under 1% (should still be approved) | 4 |
| Inflated weight vs BOL (one also has an unauthorized fee) | 3 |
| Unauthorized or non-contract accessorial | 4 |
| Wrong fuel surcharge | 3 |
| Rate above contract (wrong discount / lane rate) | 2 |
| Class changed without inspection | 1 |
| Detention beyond the dock log | 2 |
| Duplicate invoice (re-sent, past-due notice) | 2 |
| Same shipment re-billed under a new invoice number | 1 |
| BOL not in our shipment log (exception) | 1 |

Legitimate look-alikes are included on purpose (authorized liftgate, residential, hazmat, limited
access, detention that matches the dock log, lumper with receipt, approved stop-off and tarp) so a
pipeline that flags every accessorial gets penalized.

## Eval design

* **Baseline:** a one-line extraction prompt, then Claude itself decides approve / dispute / exception
  and the overcharge, given the same contract, tariff, fuel, schedule and BOL data the engine uses.
* **Refined:** a detailed extraction prompt (field definitions, date and unit normalization, accessorial
  code mapping, EDI 210 segment hints), then the deterministic rule engine.
* **Oracle (engine check, not a result):** the rule engine on answer-key data. It scores 50/50, which
  shows that any errors in the refined arm come from extraction.

Metrics are computed by `eval/metrics.py` against the answer key: field-level extraction accuracy over 15
fields, decision accuracy, touchless rate, bad invoices auto-approved, clean invoices wrongly flagged,
dollars caught (capped at the true overcharge per invoice), wall-clock seconds per invoice and API cost.
API outputs are cached under `eval/runs/` so results can be re-scored without new calls.

## Run it

```bash
pip install -r requirements.txt
python -m synth.generate          # rebuild data/ (deterministic; already committed)
python -m pytest -q               # offline tests: engine vs answer key, mocked Claude call
export ANTHROPIC_API_KEY=...      # needed for extraction
python -m eval.run_eval           # both arms, 50 invoices -> eval/results/
streamlit run app.py              # dashboard
```

Model and effort are configurable: `FREIGHT_MODEL` (default `claude-opus-5-5`) and `FREIGHT_EFFORT`
(default `low`), or `--model` / `--effort` on the eval.

## Layout

```
freight/        db.py (schema) · pricing.py (contract math) · schemas.py (Pydantic)
                extract.py (Claude) · reconcile.py (rules) · dispute.py (drafts) · pipeline.py
synth/          reference.py (carriers, lanes, terms) · generate.py (data + answer key) · render.py (layouts)
eval/           run_eval.py · metrics.py · report.py · results/ · runs/
data/           freight.db · invoices/ · answer_key.json
app.py          Streamlit dashboard
```
