"""Static reference data for the synthetic world.

Everything here is fictional: the shipper (Larkspur Home Goods), the six carriers, the
consignees and the addresses. The *structure* follows real-world practice:

* LTL is priced as a discount off the carrier's base tariff ($/CWT by lane, NMFC class and
  weight break) with an absolute minimum charge, plus a fuel surcharge percentage taken from
  a carrier table keyed to the weekly DOE/EIA U.S. on-highway diesel average.
* Truckload is priced as a flat lane linehaul plus a per-mile fuel surcharge
  ((DOE price - peg) / MPG), with a peg of $1.25 and 6.0 / 5.5 / 5.0 MPG for van / reefer /
  flatbed, which is the common convention.
* Accessorials (liftgate, residential, inside delivery, notify/appointment, limited access,
  hazmat, detention, stop-off, lumper, layover, tarp, driver assist) are paid only per the
  contract schedule, and most require authorization on the BOL.
"""

SHIPPER = "Larkspur Home Goods, Inc."

DCS = {
    "JOL": {"name": "Larkspur Home Goods - Joliet DC", "addr": "1450 Laraway Rd", "city": "Joliet", "state": "IL", "zip": "60433"},
    "SAV": {"name": "Larkspur Home Goods - Savannah DC", "addr": "88 Crossroads Pkwy", "city": "Savannah", "state": "GA", "zip": "31407"},
    "RNO": {"name": "Larkspur Home Goods - Reno DC", "addr": "1150 Trademark Dr", "city": "Reno", "state": "NV", "zip": "89521"},
}

# (dc, city, state, zip, miles)
LTL_DESTS = {
    "JOL": [("Indianapolis", "IN", "46241", 181), ("Columbus", "OH", "43207", 334), ("Milwaukee", "WI", "53207", 112),
            ("Des Moines", "IA", "50313", 331), ("Detroit", "MI", "48210", 288), ("St. Louis", "MO", "63132", 279),
            ("Minneapolis", "MN", "55413", 402)],
    "SAV": [("Charlotte", "NC", "28208", 251), ("Orlando", "FL", "32809", 287), ("Nashville", "TN", "37210", 478),
            ("Raleigh", "NC", "27610", 331), ("Birmingham", "AL", "35211", 418)],
    "RNO": [("Sacramento", "CA", "95815", 132), ("Boise", "ID", "83716", 421), ("Salt Lake City", "UT", "84104", 518),
            ("Fresno", "CA", "93725", 302), ("Portland", "OR", "97230", 577)],
}

TL_LANES = {
    "IHLG": [("JOL", "Dallas", "TX", "75241", 931), ("JOL", "Atlanta", "GA", "30336", 718), ("SAV", "Joliet", "IL", "60433", 952),
             ("JOL", "Kansas City", "MO", "64120", 509), ("JOL", "Harrisburg", "PA", "17111", 702)],
    "CCCO": [("SAV", "Dallas", "TX", "75241", 1012), ("RNO", "Phoenix", "AZ", "85043", 736), ("JOL", "Atlanta", "GA", "30336", 718),
             ("SAV", "Orlando", "FL", "32809", 287)],
    "SMFB": [("JOL", "Houston", "TX", "77029", 1083), ("RNO", "Denver", "CO", "80216", 1031), ("SAV", "Charlotte", "NC", "28208", 251),
             ("JOL", "Columbus", "OH", "43207", 334)],
}

STORE_CONSIGNEES = [
    "Hearth & Field Mercantile #{n}", "Northline Home Store #{n}", "Cobalt Kitchen Supply", "Maple Row Outfitters",
    "Brightwater Furnishings #{n}", "Saltbox Living Co.", "Tallgrass Home Center #{n}", "Juniper & Oak Retail",
    "Harbor Lane Housewares", "Redstone Interiors DC", "Granite Peak Home #{n}", "Willowmere Decor",
]
RESIDENTIAL_CONSIGNEES = ["Dana Whitfield", "Marcus Ojeda", "Priya Raman", "Tom Kessler", "Alicia Brandt", "Jun Park",
                          "Renee Castillo", "Owen McBride"]
STREETS = ["Commerce Dr", "Industrial Pkwy", "Distribution Way", "Logistics Blvd", "Enterprise Ave", "Gateway Ct",
           "Wholesale Rd", "Freight Ln", "Market St", "Elm Ridge Rd", "Oak Hollow Dr", "Cedar Bluff Ln"]

# commodity, nmfc, class, lbs-per-piece range, hazmat
LTL_COMMODITIES = [
    ("Plastic storage containers, nested, boxed", "156600-04", "100", (18, 40), False),
    ("Glass candle jars, boxed", "86750-03", "85", (22, 45), False),
    ("Kitchen textiles (towels, linens), cartoned", "49880-02", "65", (25, 55), False),
    ("Furniture, KD, wood, boxed", "79300-07", "125", (45, 120), False),
    ("Cast iron cookware, cartoned", "83060", "55", (40, 70), False),
    ("Area rugs, rolled, poly-wrapped", "174060-02", "77.5", (30, 90), False),
    ("Ceramic dinnerware, cartoned", "86920-04", "70", (30, 60), False),
    ("Aerosol air freshener, UN1950, 2.1", "48635", "60", (25, 45), True),
    ("Lamp oil, NA1993, combustible liquid", "149980", "55", (35, 55), True),
]
TL_COMMODITIES = {
    "VAN": ["Household goods, mixed SKUs, palletized", "Seasonal decor, cartoned, 26 pallets", "Small kitchen appliances, palletized"],
    "REEFER": ["Soy candles & wax melts, temp controlled 55-65F", "Live potted plants, temp controlled 50F", "Scented candles, temp controlled 60F"],
    "FLATBED": ["Steel patio furniture, banded on skids", "Outdoor shed kits, steel, crated", "Cast aluminum fire pits, crated"],
}

CLASS_FACTORS = {"50": 0.55, "55": 0.60, "60": 0.65, "65": 0.70, "70": 0.75, "77.5": 0.80, "85": 0.86,
                 "92.5": 0.93, "100": 1.00, "125": 1.20, "150": 1.40}
WEIGHT_BREAKS = [(0, 500, 1.00), (500, 1000, 0.82), (1000, 2000, 0.70), (2000, 5000, 0.58), (5000, 10000, 0.47),
                 (10000, 20000, 0.40)]

CARRIERS = {
    "RDGL": {"name": "Ridgeline Freight Lines, Inc.", "mode": "LTL", "aliases": ["ridgeline", "ridgeline freight", "ridgeline freight lines"],
             "remit": "PO Box 77014, Columbus, OH 43277-0140", "phone": "(800) 555-0142", "dcs": ["JOL", "SAV"]},
    "PXLT": {"name": "Prairie Express LTL", "mode": "LTL", "aliases": ["prairie express", "prairie express ltl", "pxlt"],
             "remit": "Dept 4410, PO Box 9187, Des Moines, IA 50306", "phone": "(515) 555-0199", "dcs": ["JOL"]},
    "BWTR": {"name": "Bluewater Transport Co.", "mode": "LTL", "aliases": ["bluewater", "bluewater transport", "blue water transport"],
             "remit": "Lockbox 22981, Sacramento, CA 94298", "phone": "(916) 555-0117", "dcs": ["RNO", "SAV"]},
    "IHLG": {"name": "Ironhorse Logistics LLC", "mode": "TL", "equipment": "VAN", "aliases": ["ironhorse", "ironhorse logistics", "iron horse logistics"],
             "remit": "3300 Stockyard Blvd, Fort Worth, TX 76106", "phone": "(817) 555-0163"},
    "CCCO": {"name": "Coldchain Carriers Co.", "mode": "TL", "equipment": "REEFER", "aliases": ["coldchain", "coldchain carriers", "cold chain carriers"],
             "remit": "PO Box 5521, Lakeland, FL 33807", "phone": "(863) 555-0108"},
    "SMFB": {"name": "Summit Flatbed Inc.", "mode": "TL", "equipment": "FLATBED", "aliases": ["summit flatbed", "summit", "summit flatbed inc"],
             "remit": "PO Box 1290, Gary, IN 46401", "phone": "(219) 555-0186"},
}

# Contract terms per carrier
CONTRACT_TERMS = {
    "RDGL": {"discount_pct": 71.0, "min_charge": 128.00, "fsc_step_pct": 0.50, "tariff_mult": 1.00},
    "PXLT": {"discount_pct": 69.5, "min_charge": 119.50, "fsc_step_pct": 0.48, "tariff_mult": 0.97},
    "BWTR": {"discount_pct": 72.5, "min_charge": 134.00, "fsc_step_pct": 0.52, "tariff_mult": 1.05},
    "IHLG": {"fsc_peg": 1.25, "fsc_mpg": 6.0, "det_free": 2.0, "det_rate": 60.0, "det_inc": 0.25, "rate_per_mile": 2.48},
    "CCCO": {"fsc_peg": 1.25, "fsc_mpg": 5.5, "det_free": 2.0, "det_rate": 75.0, "det_inc": 0.5, "rate_per_mile": 2.91},
    "SMFB": {"fsc_peg": 1.25, "fsc_mpg": 5.0, "det_free": 2.0, "det_rate": 70.0, "det_inc": 1.0, "rate_per_mile": 3.18},
}

# code: (description, unit, needs_auth) and per-carrier amount
ACCESSORIALS = {
    "LTL": {
        "LGD": ("Liftgate service at delivery", "FLAT", 1),
        "RES": ("Residential delivery", "FLAT", 1),
        "INS": ("Inside delivery", "FLAT", 1),
        "NOA": ("Notify / delivery appointment", "FLAT", 1),
        "LAD": ("Limited access delivery", "FLAT", 1),
        "HAZ": ("Hazardous materials handling", "FLAT", 1),
    },
    "TL": {
        "DET": ("Detention at consignee, after free time", "PER_HOUR", 0),
        "STP": ("Stop-off charge, per additional stop", "PER_STOP", 1),
        "LUM": ("Lumper / unloading, reimbursed at cost with receipt", "AT_COST", 0),
        "LAY": ("Layover", "FLAT", 1),
        "TONU": ("Truck ordered not used", "FLAT", 1),
        "TARP": ("Tarping (flatbed)", "FLAT", 1),
        "DRV": ("Driver assist / unload", "FLAT", 1),
    },
}
ACC_AMOUNTS = {
    "RDGL": {"LGD": 92.00, "RES": 118.00, "INS": 95.00, "NOA": 28.00, "LAD": 105.00, "HAZ": 38.50},
    "PXLT": {"LGD": 85.00, "RES": 110.00, "INS": 89.00, "NOA": 25.00, "HAZ": 35.00},
    "BWTR": {"LGD": 96.00, "RES": 122.00, "INS": 99.00, "NOA": 32.00, "LAD": 98.00, "HAZ": 42.00},
    "IHLG": {"DET": 60.00, "STP": 85.00, "LUM": 0.0, "LAY": 275.00, "TONU": 175.00, "DRV": 75.00},
    "CCCO": {"DET": 75.00, "STP": 100.00, "LUM": 0.0, "LAY": 300.00, "TONU": 200.00},
    "SMFB": {"DET": 70.00, "STP": 95.00, "TARP": 100.00, "LAY": 290.00, "TONU": 225.00},
}

# How each carrier words each accessorial on its invoices (non-uniform on purpose)
ACC_WORDING = {
    "RDGL": {"LGD": "LIFTGATE SERVICE - DEST", "RES": "RESIDENTIAL DELIVERY", "INS": "INSIDE DELIVERY",
             "NOA": "NOTIFY PRIOR TO DELIVERY", "LAD": "LIMITED ACCESS - DEST", "HAZ": "HAZARDOUS MATERIAL"},
    "PXLT": {"LGD": "LGATE DEL", "RES": "RESID DEL", "INS": "INSIDE DEL", "NOA": "APPT/NOTIFY", "HAZ": "HAZMAT CHG"},
    "BWTR": {"LGD": "LFTD  Lift gate - delivery", "RES": "RESD  Residential delivery", "INS": "INDL  Inside delivery",
             "NOA": "NOTF  Notification", "LAD": "LTDA  Limited access", "HAZ": "HAZM  Haz mat"},
    "IHLG": {"DET": "Detention - Consignee", "STP": "Stop Off Charge", "LUM": "Lumper Reimbursement",
             "LAY": "Layover", "TONU": "Truck Order Not Used", "DRV": "Driver Assist"},
    "CCCO": {"DET": "Detention at receiver", "STP": "Extra stop", "LUM": "Lumper fee (receipt attached)",
             "LAY": "Layover - driver held overnight", "TONU": "TONU"},
    "SMFB": {"DET": "DET", "STP": "SOC", "TARP": "TRP", "LAY": "LAY", "TONU": "TNU"},
}
