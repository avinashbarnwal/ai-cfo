"""Intercompany Management Agent (POC)

Matches intercompany receivables/payables between entity pairs after FX
translation, identifies mismatches, and proposes the net settlement
(netting) per entity for the month.
"""
import itertools

import pandas as pd

from common import AgentResult, BaseAgent
from common.synth import CCY, ENTITIES, rng

FX_TO_USD = {"USD": 1.0, "GBP": 1.27, "INR": 0.012, "EUR": 1.08}


class IntercompanyAgent(BaseAgent):
    name = "Intercompany Management Agent"
    category = "Close & Reconciliation"
    description = "IC matching, FX-aware mismatch detection, multilateral netting."

    def sample_data(self):
        r = rng(self.seed)
        rows = []
        for a, b in itertools.permutations(ENTITIES, 2):
            if r.random() < 0.85:
                usd = round(r.uniform(10_000, 250_000), 2)
                rows.append({"from_entity": a, "to_entity": b, "type": "AR", "amount_lcy": round(usd / FX_TO_USD[CCY[a]], 2), "ccy": CCY[a]})
                payable = usd * (1 + (r.choice([0, 0, 0, 0.03])))
                if r.random() > 0.1:
                    rows.append({"from_entity": b, "to_entity": a, "type": "AP", "amount_lcy": round(payable / FX_TO_USD[CCY[b]], 2), "ccy": CCY[b]})
        return {"ic_balances": pd.DataFrame(rows)}

    def run(self, data=None):
        ic = (data or self.sample_data())["ic_balances"].copy()
        ic["usd"] = ic.amount_lcy * ic.ccy.map(FX_TO_USD)
        ar = ic[ic.type == "AR"].rename(columns={"from_entity": "creditor", "to_entity": "debtor", "usd": "ar_usd"})
        ap = ic[ic.type == "AP"].rename(columns={"from_entity": "debtor", "to_entity": "creditor", "usd": "ap_usd"})
        m = ar[["creditor", "debtor", "ar_usd"]].merge(ap[["creditor", "debtor", "ap_usd"]], how="outer", on=["creditor", "debtor"])
        m["diff_usd"] = (m.ar_usd.fillna(0) - m.ap_usd.fillna(0)).round(2)
        m["status"] = m.apply(lambda r: "Missing AP booking" if pd.isna(r.ap_usd) else "Missing AR booking" if pd.isna(r.ar_usd)
                              else "Matched" if abs(r.diff_usd) < 100 else "Amount mismatch", axis=1)
        net = (m.groupby("creditor").ar_usd.sum().sub(m.groupby("debtor").ar_usd.sum(), fill_value=0)).round(2)
        netting = net.rename("net_position_usd").reset_index().rename(columns={"index": "entity", "creditor": "entity"})
        netting["action"] = netting.net_position_usd.map(lambda v: "Receive from netting centre" if v > 0 else "Pay netting centre")
        gross = m.ar_usd.sum()
        return AgentResult(self.name, {"pairs": len(m), "matched": int((m.status == "Matched").sum()),
                                       "gross_ic_usd": round(gross, 2), "net_settlement_usd": round(netting.net_position_usd.clip(lower=0).sum(), 2),
                                       "netting_reduction_pct": round((1 - netting.net_position_usd.clip(lower=0).sum() / gross) * 100, 1)},
                           m.round(2), extras={"netting": netting})


if __name__ == "__main__":
    IntercompanyAgent.cli()
