"""Daily Revenue Reconciliation Agent (POC)

Three-way daily recon for high-volume revenue: POS/order system -> payment
processor settlements -> bank deposits. Calculates processor fees, flags
missing settlements and deposit timing gaps.
"""
import numpy as np
import pandas as pd

from common import AgentResult, BaseAgent
from common.synth import TODAY, rng


class DailyRevenueReconAgent(BaseAgent):
    name = "Daily Revenue Reconciliation Agent"
    category = "Close & Reconciliation"
    description = "Orders vs. processor settlements vs. bank deposits, every day."

    def sample_data(self):
        r = rng(self.seed)
        days = pd.date_range(TODAY - pd.Timedelta(days=13), TODAY - pd.Timedelta(days=1))
        rows = []
        for d in days:
            for proc in ["Stripe", "Adyen", "PayPal"]:
                gross = round(r.uniform(20_000, 90_000), 2)
                fee_rate = {"Stripe": 0.029, "Adyen": 0.025, "PayPal": 0.034}[proc]
                settled = gross * (1 - fee_rate) - (r.uniform(200, 1500) if r.random() < 0.15 else 0)
                rows.append({"date": d, "processor": proc, "orders_gross": gross, "expected_fee_rate": fee_rate,
                             "settlement_net": round(settled, 2) if r.random() > 0.05 else np.nan,
                             "bank_deposit": round(settled, 2) if r.random() > 0.08 else 0.0})
        return {"daily": pd.DataFrame(rows)}

    def run(self, data=None):
        d = (data or self.sample_data())["daily"].copy()
        d["expected_net"] = (d.orders_gross * (1 - d.expected_fee_rate)).round(2)
        d["fee_variance"] = (d.settlement_net - d.expected_net).round(2)
        d["deposit_gap"] = (d.bank_deposit - d.settlement_net).round(2)
        d["status"] = np.select(
            [d.settlement_net.isna(), d.bank_deposit == 0, d.fee_variance.abs() > 50],
            ["Missing settlement file", "Deposit not received (timing?)", "Fee / chargeback variance"], "Matched")
        return AgentResult(self.name, {"days": d.date.nunique(), "lines": len(d),
                                       "match_rate_pct": round((d.status == "Matched").mean() * 100, 1),
                                       "gross_revenue": round(d.orders_gross.sum(), 2),
                                       "unexplained_fee_variance": round(d.loc[d.status.str.startswith("Fee"), "fee_variance"].sum(), 2)},
                           d[d.status != "Matched"][["date", "processor", "orders_gross", "expected_net", "settlement_net", "bank_deposit", "status"]])


if __name__ == "__main__":
    DailyRevenueReconAgent.cli()
