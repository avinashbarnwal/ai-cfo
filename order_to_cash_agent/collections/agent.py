"""Collections Management Agent (POC)

Prioritises past-due customers into a daily worklist, scores payment risk,
picks a dunning strategy and drafts the outreach email.
"""
import numpy as np
import pandas as pd

from common import AgentResult, BaseAgent, narrate
from common.synth import TODAY, invoices


class CollectionsAgent(BaseAgent):
    name = "Collections Management Agent"
    category = "Order to Cash"
    description = "Risk-scored collector worklist + automated dunning drafts."

    def sample_data(self):
        return {"invoices": invoices(self.seed)}

    def run(self, data=None):
        inv = (data or self.sample_data())["invoices"].copy()
        inv = inv[inv.open_amount > 0]
        inv["days_past_due"] = (TODAY - inv.due_date).dt.days.clip(lower=0)

        cust = inv.groupby("customer").agg(
            open_ar=("open_amount", "sum"),
            past_due=("open_amount", lambda s: s[inv.loc[s.index, "days_past_due"] > 0].sum()),
            max_dpd=("days_past_due", "max"),
            n_open=("invoice_id", "count"),
        ).reset_index()

        # Simple risk score: exposure x delinquency (stand-in for an ML payment-prediction model)
        cust["risk_score"] = (
            0.5 * cust.past_due / cust.past_due.max()
            + 0.4 * cust.max_dpd / max(cust.max_dpd.max(), 1)
            + 0.1 * cust.n_open / cust.n_open.max()
        ).round(3)
        cust["strategy"] = np.select(
            [cust.max_dpd > 60, cust.max_dpd > 30, cust.max_dpd > 0],
            ["Escalate: call + credit hold review", "Call collector", "Friendly email reminder"],
            "Pre-due courtesy note",
        )
        cust = cust.sort_values("risk_score", ascending=False)

        top = cust.iloc[0]
        top_inv = inv[inv.customer == top.customer].sort_values("days_past_due", ascending=False)
        fallback = (
            f"Subject: Past-due balance of ${top.past_due:,.0f}\n\n"
            f"Hello {top.customer} AP team,\nOur records show {len(top_inv)} open invoices "
            f"(oldest {int(top.max_dpd)} days past due). Please share a payment date or flag any dispute.\n"
            "Thank you,\nCollections"
        )
        email = narrate(
            "You are a polite but firm B2B collections specialist. Draft a short dunning email.",
            {"customer": top.customer, "strategy": top.strategy,
             "invoices": top_inv[["invoice_id", "open_amount", "days_past_due"]].head(5).to_dict("records")},
            fallback,
        )
        return AgentResult(
            self.name,
            {"customers_in_worklist": len(cust), "total_open_ar": round(cust.open_ar.sum(), 2),
             "total_past_due": round(cust.past_due.sum(), 2),
             "pct_past_due": round(cust.past_due.sum() / cust.open_ar.sum() * 100, 1)},
            cust,
            email,
        )


if __name__ == "__main__":
    CollectionsAgent.cli()
