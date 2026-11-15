"""Interchange Fee Optimizer Agent (POC)

Checks each commercial-card transaction for Level 2 / Level 3 data
completeness; where data is missing it enriches from the invoice (tax, PO,
line items) and estimates the interchange saving from qualifying at the
lower L2/L3 rate.
"""
import pandas as pd

from common import AgentResult, BaseAgent
from common.synth import CUSTOMERS, rng

RATES = {"L1": 0.0270, "L2": 0.0225, "L3": 0.0190}  # illustrative commercial-card interchange


class InterchangeOptimizerAgent(BaseAgent):
    name = "Interchange Fee Optimizer Agent"
    category = "B2B Payments"
    description = "Level 2/3 data enrichment to cut commercial-card interchange."

    def sample_data(self):
        r = rng(self.seed)
        n = 25
        return {"card_txns": pd.DataFrame({
            "txn_id": [f"IC-{i}" for i in range(n)], "customer": r.choice(CUSTOMERS, n), "amount": r.uniform(1_000, 50_000, n).round(2),
            "has_tax_amount": r.random(n) < 0.5, "has_po": r.random(n) < 0.5, "has_line_items": r.random(n) < 0.3,
            "invoice_available": r.random(n) < 0.85})}

    @staticmethod
    def level(tax, po, lines):
        return "L3" if tax and po and lines else "L2" if tax and po else "L1"

    def run(self, data=None):
        t = (data or self.sample_data())["card_txns"].copy()
        t["level_before"] = [self.level(*x) for x in zip(t.has_tax_amount, t.has_po, t.has_line_items)]
        # enrichment: pull missing fields from the matched invoice
        t["level_after"] = [("L3" if inv else lb) for inv, lb in zip(t.invoice_available, t.level_before)]
        t["fee_before"] = (t.amount * t.level_before.map(RATES)).round(2)
        t["fee_after"] = (t.amount * t.level_after.map(RATES)).round(2)
        t["saving"] = (t.fee_before - t.fee_after).round(2)
        return AgentResult(self.name, {"txns": len(t), "upgraded": int((t.level_before != t.level_after).sum()),
                                       "fees_before": round(t.fee_before.sum(), 2), "fees_after": round(t.fee_after.sum(), 2),
                                       "saving": round(t.saving.sum(), 2),
                                       "saving_bps": round(t.saving.sum() / t.amount.sum() * 1e4, 1)},
                           t[["txn_id", "amount", "level_before", "level_after", "fee_before", "fee_after", "saving"]])


if __name__ == "__main__":
    InterchangeOptimizerAgent.cli()
