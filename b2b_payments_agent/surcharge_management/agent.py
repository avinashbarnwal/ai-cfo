"""Surcharge Management Agent (POC)

Decides whether and how much to surcharge a card payment: blocks surcharges
on debit/prepaid cards and in prohibited states, caps at the lower of the
network cap (3%) and actual cost of acceptance, and produces the disclosure text.
"""
import pandas as pd

from common import AgentResult, BaseAgent
from common.synth import CUSTOMERS, rng

PROHIBITED_STATES = {"CT", "MA", "ME"}  # illustrative - verify current state law before production use
NETWORK_CAP = 0.03


class SurchargeAgent(BaseAgent):
    name = "Surcharge Management Agent"
    category = "B2B Payments"
    description = "Compliant card surcharging with automatic disclosure."

    def sample_data(self):
        r = rng(self.seed)
        n = 20
        return {"card_payments": pd.DataFrame({
            "txn_id": [f"CC-{i}" for i in range(n)], "customer": r.choice(CUSTOMERS, n),
            "amount": r.uniform(500, 40_000, n).round(2), "card_type": r.choice(["credit", "credit", "debit", "prepaid", "commercial"], n),
            "state": r.choice(["NY", "CA", "TX", "CT", "MA", "IL", "FL"], n),
            "cost_of_acceptance_pct": r.uniform(0.018, 0.034, n).round(4)})}

    def run(self, data=None):
        p = (data or self.sample_data())["card_payments"].copy()
        def decide(t):
            if t.card_type in ("debit", "prepaid"): return 0.0, "Not allowed on debit/prepaid"
            if t.state in PROHIBITED_STATES: return 0.0, f"Prohibited in {t.state}"
            rate = min(NETWORK_CAP, t.cost_of_acceptance_pct)
            return rate, "Surcharge applied"
        p[["surcharge_pct", "reason"]] = p.apply(lambda t: pd.Series(decide(t)), axis=1)
        p["surcharge_amt"] = (p.amount * p.surcharge_pct).round(2)
        p["fee_cost"] = (p.amount * p.cost_of_acceptance_pct).round(2)
        p["disclosure"] = p.apply(lambda t: f"A {t.surcharge_pct:.2%} surcharge (${t.surcharge_amt:,.2f}) applies to credit card payments "
                                  "and does not exceed our cost of acceptance." if t.surcharge_amt else "", axis=1)
        return AgentResult(self.name, {"txns": len(p), "surcharged": int((p.surcharge_amt > 0).sum()),
                                       "fees_incurred": round(p.fee_cost.sum(), 2), "fees_recovered": round(p.surcharge_amt.sum(), 2),
                                       "recovery_pct": round(p.surcharge_amt.sum() / p.fee_cost.sum() * 100, 1)},
                           p[["txn_id", "amount", "card_type", "state", "surcharge_pct", "surcharge_amt", "reason"]])


if __name__ == "__main__":
    SurchargeAgent.cli()
