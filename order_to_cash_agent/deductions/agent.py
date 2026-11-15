"""Deductions Management Agent (POC)

Classifies customer short-payments (promo, pricing, shortage, damage, freight),
decides valid vs. invalid using backup documents, and drafts a dispute / write-off.
"""
import pandas as pd

from common import AgentResult, BaseAgent, narrate
from common.synth import CUSTOMERS, rng

RULES = {
    "promo": ["promo", "trade", "mcb", "billback", "co-op"],
    "pricing": ["price", "pricing", "rate diff"],
    "shortage": ["short", "missing", "qty"],
    "damage": ["damage", "broken", "spoil"],
    "freight": ["freight", "shipping", "carrier"],
    "compliance": ["late delivery", "asn", "label", "fine", "chargeback"],
}


class DeductionsAgent(BaseAgent):
    name = "Deductions Management Agent"
    category = "Order to Cash"
    description = "Auto-codes deductions, validates against backup, routes disputes."

    def sample_data(self):
        r = rng(self.seed)
        memos = ["Promo billback Q3", "Pricing rate diff", "Short shipped 4 cases", "Damaged on arrival",
                 "Freight charge disputed", "Late delivery fine", "ASN label chargeback", "misc"]
        n = 30
        return {"deductions": pd.DataFrame({
            "deduction_id": [f"DED-{900 + i}" for i in range(n)],
            "customer": r.choice(CUSTOMERS, n),
            "amount": r.lognormal(6.5, 0.8, n).round(2),
            "memo": r.choice(memos, n),
            "has_promo_agreement": r.random(n) < 0.6,
            "pod_signed_clean": r.random(n) < 0.5,
        })}

    def run(self, data=None):
        d = (data or self.sample_data())["deductions"].copy()
        def classify(m):
            m = m.lower()
            for k, kws in RULES.items():
                if any(w in m for w in kws):
                    return k
            return "unknown"
        d["reason_code"] = d.memo.map(classify)

        def validity(r):
            if r.reason_code == "promo":
                return "valid" if r.has_promo_agreement else "invalid"
            if r.reason_code in ("shortage", "damage"):
                return "invalid" if r.pod_signed_clean else "valid"
            if r.reason_code == "compliance":
                return "dispute"
            if r.amount < 100:
                return "write-off (below threshold)"
            return "research"
        d["decision"] = d.apply(validity, axis=1)
        d["next_action"] = d.decision.map({
            "valid": "Clear against accrual", "invalid": "Send dispute with POD/contract",
            "dispute": "Request retailer backup", "research": "Route to analyst",
            "write-off (below threshold)": "Auto write-off",
        })
        inv = d[d.decision == "invalid"].head(1)
        letter = ""
        if not inv.empty:
            row = inv.iloc[0].to_dict()
            letter = narrate("Draft a concise deduction dispute letter to a retailer, citing evidence.", row,
                             f"Dispute for {row['deduction_id']} (${row['amount']:,.2f}): our signed POD/contract "
                             f"does not support '{row['memo']}'. Please repay or provide backup.")
        summ = d.groupby("decision").amount.agg(["count", "sum"]).round(2).to_dict("index")
        return AgentResult(self.name, {"total_deductions": round(d.amount.sum(), 2), "by_decision": summ}, d, letter)


if __name__ == "__main__":
    DeductionsAgent.cli()
