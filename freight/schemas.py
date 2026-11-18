"""Pydantic schemas used as Claude structured outputs."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

AccessorialCode = Literal["LGD", "RES", "INS", "NOA", "LAD", "HAZ", "DET", "STP", "LUM", "LAY", "TONU", "TARP", "DRV", "OTHER"]


class AccessorialLine(BaseModel):
    code: AccessorialCode = Field(description="Canonical accessorial code (see instructions).")
    description: str = Field(description="The charge description exactly as printed on the invoice.")
    quantity: Optional[float] = Field(description="Hours for detention, number of stops for stop-offs, else 1.")
    rate: Optional[float] = Field(description="Unit rate if printed.")
    amount: float = Field(description="Extended charge amount in USD.")


class InvoiceExtraction(BaseModel):
    carrier_name: str
    carrier_scac: Optional[str] = Field(description="4-letter SCAC if printed or known, else null.")
    invoice_number: str
    invoice_date: Optional[str] = Field(description="ISO date YYYY-MM-DD.")
    pro_number: Optional[str] = Field(description="Carrier PRO / load / freight bill number.")
    bol_number: Optional[str] = Field(description="Shipper's Bill of Lading number.")
    po_number: Optional[str]
    ship_date: Optional[str] = Field(description="Pickup date, ISO YYYY-MM-DD.")
    origin_city: Optional[str]
    origin_state: Optional[str]
    origin_zip: Optional[str]
    dest_city: Optional[str]
    dest_state: Optional[str]
    dest_zip: Optional[str]
    mode: Literal["LTL", "TL"]
    billed_weight_lbs: Optional[float] = Field(description="Billed weight in pounds.")
    freight_class: Optional[str] = Field(description="NMFC freight class for LTL, e.g. '77.5'; null for truckload.")
    miles: Optional[int] = Field(description="Billed miles (truckload).")
    linehaul_gross: Optional[float] = Field(description="Gross tariff linehaul before discount (LTL), if shown.")
    discount_pct: Optional[float]
    discount_amount: Optional[float]
    linehaul_amount: float = Field(description="NET linehaul after discount / minimum charge adjustment.")
    fuel_surcharge_pct: Optional[float] = Field(description="Fuel surcharge percent (LTL), e.g. 25.5.")
    fuel_surcharge_per_mile: Optional[float] = Field(description="Fuel surcharge $ per mile (truckload).")
    fuel_surcharge_amount: float
    accessorials: list[AccessorialLine]
    total_due: float
    is_reminder_or_copy: bool = Field(description="True if the document says it is a copy, reprint, past-due notice, second request or rebill.")
    notes: Optional[str] = Field(description="Any remarks printed on the invoice (reclass, reweigh, rebill...).")


class AuditDecision(BaseModel):
    """Baseline arm: the LLM itself judges the invoice against the contract and shipment data."""
    decision: Literal["APPROVE", "DISPUTE", "EXCEPTION"]
    overcharge_amount: float = Field(description="Dollar amount that should not be paid (0 if approve).")
    reasons: list[str]
    dispute_summary: Optional[str]
