"""Credit Management Agent (POC)

Builds a credit score from payment behaviour + bureau-style signals, recommends a
credit limit, flags customers to block, and writes a credit review memo.
"""
import numpy as np
import pandas as pd

from common import AgentResult, BaseAgent, narrate
from common.synth import CUSTOMERS, rng


class CreditAgent(BaseAgent):
    name = "Credit Management Agent"
    category = "Order to Cash"
    description = "Credit scoring, limit recommendation, order-hold decisions."

    def sample_data(self):
        r = rng(self.seed)
        n = len(CUSTOMERS)
        return {"customers": pd.DataFrame({
            "customer": CUSTOMERS,
            "annual_revenue_m": r.lognormal(4, 1, n).round(1),
            "avg_days_to_pay": r.normal(42, 12, n).round(0),
            "terms_days": r.choice([30, 45, 60], n),
            "bureau_score": r.integers(300, 850, n),
            "current_limit": r.choice([50_000, 100_000, 250_000, 500_000], n),
            "open_ar": r.uniform(10_000, 450_000, n).round(0),
            "pending_order": r.uniform(5_000, 120_000, n).round(0),
        })}

    def run(self, data=None):
        c = (data or self.sample_data())["customers"].copy()
        late = (c.avg_days_to_pay - c.terms_days).clip(lower=0)
        c["score"] = (
            40 * (c.bureau_score - 300) / 550
            + 35 * (1 - np.minimum(late, 60) / 60)
            + 25 * np.minimum(np.log1p(c.annual_revenue_m) / np.log1p(500), 1)
        ).round(1)
        c["risk_class"] = pd.cut(c.score, [0, 45, 65, 80, 101], labels=["High", "Medium", "Low", "Minimal"])
        c["recommended_limit"] = (c.annual_revenue_m * 1e6 * 0.002 * c.score / 100).round(-3)
        c["order_decision"] = np.where(
            c.open_ar + c.pending_order <= c.recommended_limit, "Release",
            np.where(c.risk_class.isin(["High"]), "Hold - credit review", "Release w/ approval"))
        c = c.sort_values("score")
        worst = c.iloc[0].to_dict()
        memo = narrate("Write a 5-line credit review memo for a credit manager.", worst,
                       f"Credit review: {worst['customer']} scored {worst['score']} ({worst['risk_class']}). "
                       f"Recommend limit ${worst['recommended_limit']:,.0f}; order decision: {worst['order_decision']}.")
        return AgentResult(self.name, {"customers": len(c), "holds": int((c.order_decision.str.startswith("Hold")).sum()),
                                       "limit_changes": int((c.recommended_limit != c.current_limit).sum())},
                           c[["customer", "score", "risk_class", "current_limit", "recommended_limit", "open_ar", "pending_order", "order_decision"]], memo)


if __name__ == "__main__":
    CreditAgent.cli()
