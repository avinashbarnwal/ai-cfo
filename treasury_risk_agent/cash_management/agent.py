"""Cash Management Agent (POC)

Builds the daily global cash position from bank balances, checks each account
against target/minimum balances, and proposes sweeps / concentration transfers
into the header account; idle cash above buffer is proposed for investment.
"""
import numpy as np
import pandas as pd

from common import AgentResult, BaseAgent, narrate
from common.synth import rng

FX = {"USD": 1.0, "GBP": 1.27, "INR": 0.012, "EUR": 1.08}


class CashManagementAgent(BaseAgent):
    name = "Cash Management Agent"
    category = "Treasury & Risk"
    description = "Daily cash position, target balancing, sweeps, idle-cash investment."

    def sample_data(self):
        r = rng(self.seed)
        accts = [("US01", "JPM Operating", "USD", True), ("US01", "BofA Payroll", "USD", False), ("US01", "Wells Lockbox", "USD", False),
                 ("UK01", "Barclays Operating", "GBP", True), ("UK01", "HSBC Collections", "GBP", False),
                 ("IN01", "HDFC Current", "INR", True), ("IN01", "ICICI Collections", "INR", False),
                 ("DE01", "Deutsche Operating", "EUR", True)]
        df = pd.DataFrame(accts, columns=["entity", "account", "ccy", "is_header"])
        df["balance_lcy"] = [r.uniform(0.2e6, 6e6) / FX[c] for c in df.ccy]
        df["target_lcy"] = [(1.5e6 if h else 2.5e5) / FX[c] for h, c in zip(df.is_header, df.ccy)]
        df["min_lcy"] = df.target_lcy * 0.5
        return {"accounts": df.round(0), "buffer_usd": pd.DataFrame({"v": [5e6]})}

    def run(self, data=None):
        data = data or self.sample_data()
        a = data["accounts"].copy()
        a["balance_usd"] = (a.balance_lcy * a.ccy.map(FX)).round(0)
        a["excess_lcy"] = (a.balance_lcy - a.target_lcy).round(0)
        moves = []
        for (ent, ccy), g in a.groupby(["entity", "ccy"]):
            header = g[g.is_header].iloc[0]
            for r in g[~g.is_header].itertuples():
                if r.excess_lcy > 0:
                    moves.append({"from": r.account, "to": header.account, "ccy": ccy, "amount_lcy": r.excess_lcy, "type": "Sweep to header"})
                elif r.balance_lcy < r.min_lcy:
                    moves.append({"from": header.account, "to": r.account, "ccy": ccy, "amount_lcy": -r.excess_lcy, "type": "Fund below minimum"})
        moves = pd.DataFrame(moves)
        total = a.balance_usd.sum()
        buffer = float(data["buffer_usd"].v.iloc[0])
        idle = max(total - buffer - a.target_lcy.mul(a.ccy.map(FX)).sum(), 0)
        brief = narrate("Write a 4-line morning cash brief for the Treasurer.",
                        {"position_by_entity": a.groupby("entity").balance_usd.sum().to_dict(), "moves": moves.to_dict("records"), "idle_usd": idle},
                        f"Global cash ${total/1e6:,.1f}M across {len(a)} accounts; {len(moves)} transfers proposed; "
                        f"${idle/1e6:,.1f}M idle above buffer -> propose MMF / T-bill placement.")
        return AgentResult(self.name, {"global_cash_usd": total, "by_entity_usd": a.groupby("entity").balance_usd.sum().to_dict(),
                                       "transfers_proposed": len(moves), "idle_cash_to_invest_usd": round(idle, 0)},
                           moves, brief, {"position": a})


if __name__ == "__main__":
    CashManagementAgent.cli()
