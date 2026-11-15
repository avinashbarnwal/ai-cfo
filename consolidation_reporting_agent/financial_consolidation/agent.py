"""Financial Consolidation Agent (POC)

Consolidates entity trial balances: currency translation (closing rate for BS,
average rate for P&L, CTA plug to equity), intercompany elimination, and
minority interest, producing a consolidated TB that balances.
"""
import pandas as pd

from common import AgentResult, BaseAgent
from common.synth import CCY, rng

CLOSE = {"USD": 1.0, "GBP": 1.27, "INR": 0.012, "EUR": 1.08}
AVG = {"USD": 1.0, "GBP": 1.26, "INR": 0.0121, "EUR": 1.09}
OWNERSHIP = {"US01": 1.0, "UK01": 1.0, "IN01": 0.8, "DE01": 1.0}
BS = ["Cash", "Receivables", "IC Receivable", "Fixed Assets", "Payables", "IC Payable", "Equity"]
PL = ["Revenue", "IC Revenue", "COGS", "IC COGS", "Opex"]


class FinancialConsolidationAgent(BaseAgent):
    name = "Financial Consolidation Agent"
    category = "Consolidation & Reporting"
    description = "FX translation, IC eliminations, NCI -> consolidated TB."

    def sample_data(self):
        r = rng(self.seed)
        rows = []
        for e, ccy in CCY.items():
            k = 1 / CLOSE[ccy]
            bal = {"Cash": 4e5, "Receivables": 6e5, "IC Receivable": 1.5e5 if e in ("US01", "DE01") else 0, "Fixed Assets": 9e5,
                   "Payables": -5e5, "IC Payable": -1.5e5 if e in ("UK01", "IN01") else 0,
                   "Revenue": -1.2e6, "IC Revenue": -2e5 if e == "US01" else 0, "COGS": 6e5, "IC COGS": 2e5 if e == "IN01" else 0, "Opex": 3e5}
            bal = {a: round(v * k * r.uniform(0.8, 1.2), 2) for a, v in bal.items()}
            bal["Equity"] = round(-sum(bal.values()), 2)  # TB balances in local currency
            rows += [{"entity": e, "ccy": ccy, "account": a, "lcy": v} for a, v in bal.items()]
        return {"trial_balances": pd.DataFrame(rows)}

    def run(self, data=None):
        tb = (data or self.sample_data())["trial_balances"].copy()
        tb["rate"] = tb.apply(lambda r: (AVG if r.account in PL else CLOSE)[r.ccy], axis=1)
        tb["usd"] = (tb.lcy * tb.rate).round(2)
        cta = tb.groupby("entity").usd.sum().rename("usd").reset_index().assign(account="CTA (OCI)", usd=lambda d: -d.usd)
        tb = pd.concat([tb, cta], ignore_index=True)
        cons = tb.pivot_table(index="account", columns="entity", values="usd", aggfunc="sum").fillna(0)
        cons["aggregate_usd"] = cons.sum(axis=1)
        elim = pd.Series(0.0, index=cons.index)
        for a, b in [("IC Receivable", "IC Payable"), ("IC Revenue", "IC COGS")]:
            elim[a], elim[b] = -cons.loc[a, "aggregate_usd"], -cons.loc[b, "aggregate_usd"]
        elim_diff = elim.sum()
        elim["IC elimination diff (to P&L)"] = -elim_diff
        cons = cons.reindex(elim.index, fill_value=0)
        cons["eliminations"] = elim
        net_income_in01 = -cons.loc[PL, "IN01"].sum()
        nci = round(net_income_in01 * (1 - OWNERSHIP["IN01"]), 2)
        cons["consolidated"] = cons["aggregate_usd"].fillna(0) + cons.eliminations
        return AgentResult(self.name, {"entities": tb.entity.nunique(), "consolidated_tb_balances": bool(abs(cons.consolidated.sum()) < 1),
                                       "ic_elimination_difference_usd": round(elim_diff, 2), "nci_share_of_profit_usd": nci,
                                       "consolidated_net_income_usd": round(-cons.loc[PL, "consolidated"].sum() - elim_diff, 2)},
                           cons.round(2).reset_index())


if __name__ == "__main__":
    FinancialConsolidationAgent.cli()
