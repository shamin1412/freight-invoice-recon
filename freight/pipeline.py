"""End-to-end: invoice file -> Claude extraction -> rule engine -> triage + dispute draft."""
from __future__ import annotations

import json
import time
from pathlib import Path

from freight import db
from freight.dispute import draft_dispute
from freight.extract import REFINED_PROMPT, extract
from freight.reconcile import Reconciler


def carrier_name(conn, scac):
    row = conn.execute("SELECT name FROM carriers WHERE scac=?", (scac,)).fetchone() if scac else None
    return row["name"] if row else None


def process(paths: list[Path], conn=None, prompt: str = REFINED_PROMPT) -> list[dict]:
    """Process invoices in the order given (order matters for duplicate detection)."""
    conn = conn or db.connect()
    rec = Reconciler(conn)
    out = []
    for p in paths:
        t0 = time.perf_counter()
        ex = extract(p, prompt=prompt)
        if ex.data is None:
            out.append({"file": p.name, "status": "EXTRACTION_FAILED", "error": ex.error})
            continue
        inv = ex.data.model_dump()
        r = rec.reconcile(inv)
        out.append({"file": p.name, "extraction": inv, "result": r.to_dict(),
                    "dispute": draft_dispute(r, inv, carrier_name(conn, r.carrier_scac)),
                    "seconds": round(time.perf_counter() - t0, 2)})
    return out


if __name__ == "__main__":
    import sys

    files = [Path(x) for x in sys.argv[1:]]
    print(json.dumps(process(files), indent=2, default=str))
