"""Financial Reporting Agent (POC)

Generates the monthly P&L flux report: actual vs. budget vs. prior month,
flags lines breaching materiality thresholds, and drafts management
commentary for the CFO pack.
"""
import numpy as np
import pandas as pd

from common import AgentResult, BaseAgent, narrate
from common.synth import rng

LINES = ["Revenue", "COGS", "Gross Profit", "Sales & Marketing", "R&D", "G&A", "EBITDA", "D&A", "Interest", "Tax", "Net Income"]


class FinancialReportingAgent(BaseAgent):
    name = "Financial Reporting Agent"
    category = "Consolidation & Reporting"
    description = "Flux analysis + auto-drafted management commentary."

    def sample_data(self):
        r = rng(self.seed)
        base = {"Revenue": 10e6, "COGS": -5.8e6, "Sales & Marketing": -1.4e6, "R&D": -1.1e6, "G&A": -0.8e6, "D&A": -0.3e6, "Interest": -0.1e6}
        def build(noise):
            v = {k: x * r.normal(1, noise) for k, x in base.items()}
            v["Gross Profit"] = v["Revenue"] + v["COGS"]
            v["EBITDA"] = v["Gross Profit"] + v["Sales & Marketing"] + v["R&D"] + v["G&A"]
            v["Tax"] = -0.25 * max(v["EBITDA"] + v["D&A"] + v["Interest"], 0)
            v["Net Income"] = v["EBITDA"] + v["D&A"] + v["Interest"] + v["Tax"]
            return [round(v[l], 0) for l in LINES]
        return {"pl": pd.DataFrame({"line": LINES, "actual": build(0.08), "budget": build(0.0), "prior_month": build(0.05)})}

    def run(self, data=None, pct_threshold=0.03, abs_threshold=50_000):
        pl = (data or self.sample_data())["pl"].copy()
        pl["var_vs_budget"] = pl.actual - pl.budget
        pl["var_vs_budget_pct"] = (pl.var_vs_budget / pl.budget.abs()).round(3)
        pl["var_vs_pm"] = pl.actual - pl.prior_month
        pl["favourable"] = pl.var_vs_budget > 0  # sign convention: costs negative
        pl["flag"] = (pl.var_vs_budget_pct.abs() > pct_threshold) & (pl.var_vs_budget.abs() > abs_threshold)
        flagged = pl[pl.flag]
        fb = "\n".join(f"- {r.line}: {'+' if r.var_vs_budget>0 else ''}{r.var_vs_budget/1e3:,.0f}k vs budget "
                       f"({r.var_vs_budget_pct:+.1%}), {'favourable' if r.favourable else 'unfavourable'}. [driver: to be confirmed by owner]"
                       for r in flagged.itertuples())
        commentary = narrate("You are an FP&A lead. Write CFO-pack flux commentary. Do NOT invent business drivers; "
                             "where the cause is unknown, write 'driver TBC with <owner>'.", pl.to_dict("records"), fb)
        return AgentResult(self.name, {"lines_flagged": int(pl.flag.sum()),
                                       "revenue_vs_budget_pct": float(pl.loc[pl.line == "Revenue", "var_vs_budget_pct"].iloc[0]),
                                       "ebitda_margin_pct": round(float(pl.loc[pl.line == "EBITDA", "actual"].iloc[0] / pl.loc[pl.line == "Revenue", "actual"].iloc[0] * 100), 1)},
                           pl, commentary)


if __name__ == "__main__":
    FinancialReportingAgent.cli()
