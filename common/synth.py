"""Synthetic data helpers so every POC runs with zero setup."""
from __future__ import annotations

import numpy as np
import pandas as pd

TODAY = pd.Timestamp("2026-11-14")

CUSTOMERS = [
    "Acme Retail", "Northwind Foods", "Globex Mfg", "Initech Labs", "Umbrella Health",
    "Stark Logistics", "Wayne Distribution", "Hooli Tech", "Soylent CPG", "Tyrell Chemicals",
    "Cyberdyne Energy", "Wonka Confectionery", "Vandelay Imports", "Pied Piper Media",
    "Gringotts Insurance",
]
VENDORS = [
    "Apex Steel", "BlueLine Freight", "Crest Packaging", "Delta IT Services", "Evergreen Paper",
    "Falcon Office", "Granite Utilities", "Harbor Leasing", "Ion Chemicals", "Juno Staffing",
]
ENTITIES = ["US01", "UK01", "IN01", "DE01"]
CCY = {"US01": "USD", "UK01": "GBP", "IN01": "INR", "DE01": "EUR"}


def rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def invoices(seed: int = 7, n: int = 200) -> pd.DataFrame:
    r = rng(seed)
    inv_date = TODAY - pd.to_timedelta(r.integers(5, 150, n), unit="D")
    terms = r.choice([30, 45, 60], n)
    amount = np.round(r.lognormal(9, 0.9, n), 2)
    paid = r.random(n) < 0.35
    return pd.DataFrame({
        "invoice_id": [f"INV-{10000 + i}" for i in range(n)],
        "customer": r.choice(CUSTOMERS, n),
        "invoice_date": inv_date,
        "due_date": inv_date + pd.to_timedelta(terms, unit="D"),
        "amount": amount,
        "open_amount": np.where(paid, 0.0, amount),
        "currency": "USD",
    })
