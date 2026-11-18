"""Offline tests: rule engine against the answer key, and the Claude call path with a mocked HTTP transport.

    python -m pytest -q
"""
import json
from pathlib import Path

import anthropic
import httpx2 as httpx

from freight import db
from freight.extract import extract, REFINED_PROMPT
from freight.reconcile import Reconciler

ROOT = Path(__file__).resolve().parent.parent
KEY = sorted(json.loads((ROOT / "data" / "answer_key.json").read_text()), key=lambda k: k["received_order"])


def test_engine_matches_answer_key_on_true_data():
    rec = Reconciler(db.connect())
    for k in KEY:
        r = rec.reconcile(dict(k["truth"]))
        assert r.decision == k["expected_decision"], k["file"]
        assert abs(r.overcharge - k["true_overcharge"]) < 0.02, k["file"]


def test_within_tolerance_is_approved_with_note():
    rec = Reconciler(db.connect())
    tol = [k for k in KEY if "TOLERANCE" in k["planted"]]
    assert tol
    for k in KEY:
        r = rec.reconcile(dict(k["truth"]))
        if k in tol:
            assert r.decision == "APPROVE" and r.findings and r.notes


def test_extract_request_shape_and_parse():
    k = KEY[0]
    t = k["truth"]
    fake = {
        "carrier_name": "x", "carrier_scac": t["carrier_scac"], "invoice_number": t["invoice_number"],
        "invoice_date": t["invoice_date"], "pro_number": t["pro_number"], "bol_number": t["bol_number"], "po_number": None,
        "ship_date": t["ship_date"], "origin_city": None, "origin_state": None, "origin_zip": t["origin_zip"],
        "dest_city": None, "dest_state": None, "dest_zip": t["dest_zip"], "mode": t["mode"],
        "billed_weight_lbs": t["billed_weight_lbs"], "freight_class": t["freight_class"], "miles": t["miles"],
        "linehaul_gross": None, "discount_pct": None, "discount_amount": None, "linehaul_amount": t["linehaul_amount"],
        "fuel_surcharge_pct": None, "fuel_surcharge_per_mile": None, "fuel_surcharge_amount": t["fuel_surcharge_amount"],
        "accessorials": [{"code": a["code"], "description": a["code"], "quantity": None, "rate": None, "amount": a["amount"]}
                         for a in t["accessorials"]],
        "total_due": t["total_due"], "is_reminder_or_copy": False, "notes": None,
    }
    seen = {}

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        seen["body"] = body
        return httpx.Response(200, json={
            "id": "msg_test", "type": "message", "role": "assistant", "model": body["model"],
            "content": [{"type": "text", "text": json.dumps(fake)}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1200, "output_tokens": 300}})

    client = anthropic.Anthropic(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    res = extract(ROOT / "data" / "invoices" / k["file"], client=client)
    assert res.error is None, res.error
    assert res.data.total_due == t["total_due"]
    body = seen["body"]
    assert body["system"] == REFINED_PROMPT
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["effort"] in ("low", "medium", "high", "xhigh", "max")
    blk = body["messages"][0]["content"][0]
    assert blk["type"] in ("document", "text")
