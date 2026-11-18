"""Invoice extraction with Claude structured outputs (Pydantic).

Two prompts are provided so the eval can compare them:

* BASELINE_PROMPT: a one-line "extract the fields" instruction.
* REFINED_PROMPT:  field definitions, normalization rules, accessorial code mapping
                   (including carrier-specific and EDI 210 codes) and format hints.

Both use the same output schema, so differences in accuracy come from the prompt.
"""
from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic

from freight.schemas import InvoiceExtraction

MODEL = os.environ.get("FREIGHT_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("FREIGHT_EFFORT", "low")

BASELINE_PROMPT = "Extract the data from this freight invoice."

REFINED_PROMPT = """You are a freight audit clerk extracting data from a carrier freight invoice for automated
reconciliation against contracts and Bills of Lading. Accuracy matters more than completeness:
copy identifiers exactly, and use null when a field is not on the document. Never compute or
"correct" amounts; report what the carrier billed.

Documents arrive as PDFs (some scanned), fixed-width printouts, emails, or ANSI X12 EDI 210.

FIELD RULES
- carrier_scac: 4-letter SCAC. Known carriers: Ridgeline Freight Lines=RDGL, Prairie Express LTL=PXLT,
  Bluewater Transport=BWTR, Ironhorse Logistics=IHLG, Coldchain Carriers=CCCO, Summit Flatbed=SMFB.
- invoice_number: the invoice / freight bill number. If the only number is the PRO (common on LTL
  freight bills), use the PRO digits without punctuation as invoice_number.
- pro_number: carrier PRO, load # or freight bill #, exactly as printed (keep dashes).
- bol_number: the SHIPPER's BOL number (on this account it looks like LHG-XXX-MMDD-NNNN).
- Dates: convert any format (09/21/2026, 21SEP26, 9/21/26, Sep 21, 2026, 20260921) to YYYY-MM-DD.
  ship_date = pickup date. invoice_date = invoice / bill date.
- Zips: 5-digit ZIP of origin (shipper) and destination (consignee).
- mode: LTL if billed by weight/class/CWT with a discount; TL if a flat linehaul per load with miles.
- billed_weight_lbs: weight in POUNDS. "#" means pounds. If both LB and KG are shown, use LB.
- freight_class: LTL class as a string ("55", "77.5", "92.5"); null for truckload.
- linehaul_amount: the NET linehaul the carrier is charging = gross linehaul minus discount (or the
  minimum charge if the invoice says a minimum applies). For truckload, the flat linehaul.
- fuel_surcharge_pct for LTL (%), fuel_surcharge_per_mile for TL ($/mi); fuel_surcharge_amount in $.
- total_due: the invoice total / amount due / balance due.
- is_reminder_or_copy: true if marked copy, reprint, statement, second notice, past due, 2nd request,
  follow-up on unpaid invoice, or rebill.

ACCESSORIALS - one entry per extra charge (NOT linehaul, discount, minimum or fuel). Map to a code:
  LGD liftgate (LGATE, LFTD, lift gate)        RES residential (RESID, RESD)
  INS inside delivery (INDL)                   NOA notify / appointment / call before (NOTF, APPT)
  LAD limited access (LTDA)                    HAZ hazardous materials (HAZMAT, HAZM)
  DET detention (EDI DET; quantity = hours)    STP stop-off / extra stop (EDI SOC; quantity = stops)
  LUM lumper / unloading fee                   LAY layover
  TONU truck ordered not used (TNU)            TARP tarping (EDI TRP)
  DRV driver assist                            OTHER anything else
  Copy the printed description into `description`.

EDI 210 HINTS
- B3: element 2 = invoice number, 3 = PRO/shipment id, 6 = invoice date, 7 = total in CENTS, 11 = SCAC,
  12 = ship date. N9*BM = BOL number, N9*PO = PO. N4 under N1*SH = origin, under N1*CN = destination.
- L0 element 4 = weight (L = pounds). L1: element 2 = rate, 3 = rate qualifier (PM per mile, PH per
  hour), 4 = charge in CENTS, 8 = charge code (400 linehaul, FUE fuel). The free text after the code
  holds miles / hours.
"""


@dataclass
class ExtractionResult:
    file: str
    data: InvoiceExtraction | None
    error: str | None
    seconds: float
    input_tokens: int = 0
    output_tokens: int = 0


def document_block(path: Path) -> dict:
    if path.suffix.lower() == ".pdf":
        b64 = base64.standard_b64encode(path.read_bytes()).decode()
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    return {"type": "text", "text": f"<invoice_document filename=\"{path.name}\">\n{path.read_text()}\n</invoice_document>"}


def extract(path: str | Path, prompt: str = REFINED_PROMPT, client: anthropic.Anthropic | None = None,
            model: str = MODEL, effort: str = EFFORT) -> ExtractionResult:
    path = Path(path)
    client = client or anthropic.Anthropic()
    t0 = time.perf_counter()
    try:
        resp = client.messages.parse(
            model=model,
            max_tokens=16000,
            system=prompt,
            messages=[{"role": "user", "content": [document_block(path),
                                                   {"type": "text", "text": "Extract this invoice."}]}],
            output_config={"effort": effort},
            output_format=InvoiceExtraction,
        )
        dt_s = time.perf_counter() - t0
        if resp.stop_reason == "refusal":
            return ExtractionResult(path.name, None, "refusal", dt_s)
        if resp.stop_reason == "max_tokens":
            return ExtractionResult(path.name, None, "max_tokens", dt_s)
        return ExtractionResult(path.name, resp.parsed_output, None, dt_s,
                                resp.usage.input_tokens, resp.usage.output_tokens)
    except anthropic.RateLimitError as e:
        return ExtractionResult(path.name, None, f"rate_limited: {e}", time.perf_counter() - t0)
    except anthropic.APIStatusError as e:
        return ExtractionResult(path.name, None, f"api_error {e.status_code}: {e.message}", time.perf_counter() - t0)
    except anthropic.APIConnectionError as e:
        return ExtractionResult(path.name, None, f"connection_error: {e}", time.perf_counter() - t0)
    except Exception as e:  # schema validation etc.
        return ExtractionResult(path.name, None, f"{type(e).__name__}: {e}", time.perf_counter() - t0)
