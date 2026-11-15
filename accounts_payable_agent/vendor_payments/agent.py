"""Vendor Payments Agent (POC)

Builds the payment run: picks invoices due inside the horizon, captures early-pay
discounts when the annualised return beats the cost of cash, chooses rail
(ACH / wire / virtual card), and respects available cash.
"""
import numpy as np
import pandas as pd

from common import AgentResult, BaseAgent
from common.synth import TODAY, VENDORS, rng

COST_OF_CASH = 0.08  # annual
CARD_VENDORS = {"Falcon Office", "Evergreen Paper", "Delta IT Services"}


class VendorPaymentsAgent(BaseAgent):
    name = "Vendor Payments Agent"
    category = "Accounts Payable"
    description = "Payment-run optimisation: discounts, rails, cash limits."

    def sample_data(self):
        r = rng(self.seed)
        n = 30
        inv_date = TODAY - pd.to_timedelta(r.integers(0, 40, n), unit="D")
        return {"approved_invoices": pd.DataFrame({
            "invoice_no": [f"VI-{9100 + i}" for i in range(n)], "vendor": r.choice(VENDORS, n),
            "amount": r.uniform(1_000, 60_000, n).round(2), "invoice_date": inv_date,
            "due_date": inv_date + pd.Timedelta(days=45),
            "discount_pct": r.choice([0, 0, 0.01, 0.02], n), "discount_days": 10,
            "international": r.random(n) < 0.15,
        }), "cash_available": pd.DataFrame({"usd": [400_000]})}

    def run(self, data=None, horizon_days=7):
        data = data or self.sample_data()
        d = data["approved_invoices"].copy()
        cash = float(data["cash_available"].usd.iloc[0])
        d["disc_deadline"] = d.invoice_date + pd.to_timedelta(d.discount_days, unit="D")
        days_early = (d.due_date - d.disc_deadline).dt.days
        d["disc_apr"] = np.where(d.discount_pct > 0, d.discount_pct / (1 - d.discount_pct) * 365 / days_early, 0)
        take_disc = (d.disc_apr > COST_OF_CASH) & (d.disc_deadline >= TODAY)
        due_soon = d.due_date <= TODAY + pd.Timedelta(days=horizon_days)
        d["reason"] = np.select([take_disc, due_soon], ["Capture discount", "Due in horizon"], "Defer")
        d["pay_amount"] = np.where(take_disc, d.amount * (1 - d.discount_pct), d.amount).round(2)
        d["rail"] = np.select([d.international, d.vendor.isin(CARD_VENDORS)], ["Wire", "Virtual card (rebate)"], "ACH")
        run = d[d.reason != "Defer"].sort_values(["reason", "disc_apr"], ascending=[True, False])
        run["cum"] = run.pay_amount.cumsum()
        run["in_run"] = run.cum <= cash
        sel = run[run.in_run]
        return AgentResult(self.name, {"cash_available": cash, "payments": len(sel), "total_paid": round(sel.pay_amount.sum(), 2),
                                       "discounts_captured": round((sel.amount - sel.pay_amount).sum(), 2),
                                       "rail_mix": sel.rail.value_counts().to_dict(), "deferred_for_cash": int((~run.in_run).sum())},
                           run[["invoice_no", "vendor", "amount", "pay_amount", "reason", "disc_apr", "rail", "in_run"]].round(3))


if __name__ == "__main__":
    VendorPaymentsAgent.cli()
