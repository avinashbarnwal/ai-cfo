"""Balance Sheet Reconciliation Agent (POC)

Compares GL balances to sub-ledger / bank / external balances for each account,
risk-rates accounts, auto-certifies low-risk zero-variance recs, and explains
variances from open reconciling items.
"""
import numpy as np
import pandas as pd

from common import AgentResult, BaseAgent, narrate
from common.synth import rng

MATERIALITY = 1_000


class BalanceSheetReconAgent(BaseAgent):
    name = "Balance Sheet Reconciliation Agent"
    category = "Close & Reconciliation"
    description = "GL vs. supporting balance recs with risk-based auto-certification."

    def sample_data(self):
        r = rng(self.seed)
        accts = ["1000 Cash - Operating", "1010 Cash - Payroll", "1200 Accounts Receivable", "1300 Inventory",
                 "1400 Prepaids", "1500 Fixed Assets", "2000 Accounts Payable", "2100 Accrued Liabilities",
                 "2200 Payroll Liabilities", "2300 Sales Tax Payable", "2500 Deferred Revenue", "1600 Intercompany Rec"]
        gl = r.uniform(50_000, 3_000_000, len(accts)).round(2)
        support = gl.copy()
        support[[2, 6, 9, 11]] += [12_500.0, -430.0, 2_310.55, -48_000.0]
        items = pd.DataFrame([
            {"account": accts[2], "item": "Unapplied cash in suspense", "amount": 12_500.0},
            {"account": accts[9], "item": "Q3 filing true-up", "amount": 2_000.0},
            {"account": accts[11], "item": "IC invoice not booked by UK01", "amount": -30_000.0},
        ])
        return {"balances": pd.DataFrame({"account": accts, "gl_balance": gl, "support_balance": support,
                                          "prior_variance": r.choice([0, 0, 500], len(accts))}), "reconciling_items": items}

    def run(self, data=None):
        data = data or self.sample_data()
        b, items = data["balances"].copy(), data["reconciling_items"]
        b["variance"] = (b.support_balance - b.gl_balance).round(2)
        explained = items.groupby("account").amount.sum()
        b["explained"] = b.account.map(explained).fillna(0)
        b["unexplained"] = (b.variance - b.explained).round(2)
        b["risk"] = np.select([b.account.str.contains("Cash|Intercompany|Deferred"), b.gl_balance > 1e6], ["High", "Medium"], "Low")
        b["status"] = np.select(
            [(b.variance == 0) & (b.risk != "High"), b.variance == 0, b.unexplained.abs() < MATERIALITY, b.unexplained.abs() >= MATERIALITY],
            ["Auto-certified", "Zero variance - high-risk reviewer sign-off", "Within materiality - reviewer sign-off", "Exception - investigate"], "Review")
        ex = b[b.status.str.startswith("Exception")]
        note = narrate("Explain balance-sheet reconciliation exceptions and recommended adjusting entries, briefly.",
                       {"exceptions": ex.to_dict("records"), "items": items.to_dict("records")},
                       f"{len(ex)} account(s) have unexplained variance over ${MATERIALITY:,}.")
        return AgentResult(self.name, {"accounts": len(b), "auto_certified": int((b.status == "Auto-certified").sum()),
                                       "exceptions": len(ex)},
                           b[["account", "gl_balance", "support_balance", "variance", "explained", "unexplained", "risk", "status"]], note)


if __name__ == "__main__":
    BalanceSheetReconAgent.cli()
