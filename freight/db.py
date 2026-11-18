"""SQLite schema and connection helpers.

Tables
------
carriers            carrier master + name aliases used to resolve extracted carrier names
contracts           one row per carrier contract (mode, discount, min charge, fuel method, detention terms)
contract_clauses    the clause text the dispute drafts cite (e.g. "§4.2")
ltl_tariff          base tariff $/CWT by lane (zip3 -> zip3), class and weight break
tl_lane_rates       contracted flat linehaul per truckload lane
fsc_ltl_table       carrier fuel surcharge % by DOE diesel price bracket
doe_diesel          weekly U.S. on-highway diesel average (synthetic, EIA-style)
accessorial_schedule contracted accessorial charges and whether they need prior authorization
shipments           the shipment / Bill of Lading log (what was actually tendered and authorized)
invoice_ledger      invoices already processed (used for duplicate detection)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "freight.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS carriers (
    scac TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    aliases TEXT NOT NULL            -- '|' separated lowercase aliases
);
CREATE TABLE IF NOT EXISTS contracts (
    contract_id TEXT PRIMARY KEY,
    scac TEXT NOT NULL REFERENCES carriers(scac),
    mode TEXT NOT NULL,              -- LTL | TL
    equipment TEXT,                  -- VAN | REEFER | FLATBED (TL only)
    effective_from TEXT NOT NULL,
    effective_to TEXT NOT NULL,
    discount_pct REAL,               -- LTL: discount off base tariff
    min_charge REAL,                 -- LTL: absolute minimum net linehaul
    fsc_method TEXT NOT NULL,        -- PCT_TABLE | PER_MILE
    fsc_peg REAL,                    -- PER_MILE: base diesel price
    fsc_mpg REAL,                    -- PER_MILE: miles per gallon divisor
    detention_free_hours REAL,
    detention_rate REAL,             -- $ per hour after free time
    detention_increment_hours REAL   -- billing increment, e.g. 0.25
);
CREATE TABLE IF NOT EXISTS contract_clauses (
    contract_id TEXT NOT NULL REFERENCES contracts(contract_id),
    clause_ref TEXT NOT NULL,
    topic TEXT NOT NULL,             -- RATES | FUEL | ACCESSORIAL | AUTHORIZATION | DETENTION | WEIGHT_CLASS | DUPLICATE | DISPUTE | LUMPER
    text TEXT NOT NULL,
    PRIMARY KEY (contract_id, clause_ref)
);
CREATE TABLE IF NOT EXISTS ltl_tariff (
    contract_id TEXT NOT NULL,
    orig_zip3 TEXT NOT NULL,
    dest_zip3 TEXT NOT NULL,
    freight_class TEXT NOT NULL,
    min_lbs INTEGER NOT NULL,
    max_lbs INTEGER NOT NULL,
    cwt_rate REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tl_lane_rates (
    contract_id TEXT NOT NULL,
    orig_zip3 TEXT NOT NULL,
    dest_zip3 TEXT NOT NULL,
    miles INTEGER NOT NULL,
    linehaul REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS fsc_ltl_table (
    contract_id TEXT NOT NULL,
    min_price REAL NOT NULL,
    max_price REAL NOT NULL,
    pct REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS doe_diesel (
    week_start TEXT PRIMARY KEY,     -- Monday, ISO date
    price REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS accessorial_schedule (
    contract_id TEXT NOT NULL,
    code TEXT NOT NULL,
    description TEXT NOT NULL,
    unit TEXT NOT NULL,              -- FLAT | PER_HOUR | PER_STOP | AT_COST
    amount REAL NOT NULL,
    requires_authorization INTEGER NOT NULL,
    clause_ref TEXT NOT NULL,
    PRIMARY KEY (contract_id, code)
);
CREATE TABLE IF NOT EXISTS shipments (
    bol_number TEXT PRIMARY KEY,
    pro_number TEXT,
    scac TEXT NOT NULL,
    mode TEXT NOT NULL,
    equipment TEXT,
    ship_date TEXT NOT NULL,
    delivery_date TEXT,
    po_number TEXT,
    shipper_name TEXT, origin_city TEXT, origin_state TEXT, origin_zip TEXT,
    consignee_name TEXT, dest_city TEXT, dest_state TEXT, dest_zip TEXT,
    pieces INTEGER, handling_units INTEGER,
    weight_lbs REAL NOT NULL,
    freight_class TEXT,
    nmfc TEXT,
    commodity TEXT,
    miles INTEGER,
    stops INTEGER DEFAULT 1,
    authorized_accessorials TEXT DEFAULT '',   -- CSV of codes on BOL / approved in writing
    dock_in TEXT, dock_out TEXT,               -- consignee dock log (TL)
    lumper_receipt REAL,
    reweigh_certificate INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS invoice_ledger (
    scac TEXT NOT NULL,
    invoice_number TEXT NOT NULL,
    pro_number TEXT,
    bol_number TEXT,
    total REAL,
    decision TEXT,
    source_file TEXT,
    processed_at TEXT,
    PRIMARY KEY (scac, invoice_number, source_file)
);
"""


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
