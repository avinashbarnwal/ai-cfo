"""Treasury Payments Agent (POC)

Screens outgoing treasury payments before release: sanctions / beneficiary
checks, duplicate detection, anomaly score vs. beneficiary history, approval
matrix (dual control by amount), and generates pain.001-style output.
"""
import numpy as np
import pandas as pd

from common import AgentResult, BaseAgent
from common.synth import VENDORS, rng

APPROVAL_MATRIX = [(50_000, ["Treasury Analyst"]), (500_000, ["Treasury Analyst", "Treasury Manager"]),
                   (float("inf"), ["Treasury Manager", "CFO"])]
WATCHLIST = {"Blocked Corp"}


class TreasuryPaymentsAgent(BaseAgent):
    name = "Treasury Payments Agent"
    category = "Treasury & Risk"
    description = "Pre-release payment screening, fraud anomaly scoring, approval routing."

    def sample_data(self):
        r = rng(self.seed)
        hist = pd.DataFrame({"beneficiary": r.choice(VENDORS, 400), "amount": r.lognormal(9.5, 0.5, 400)})
        n = 15
        batch = pd.DataFrame({"pay_id": [f"TP-{100 + i}" for i in range(n)], "beneficiary": r.choice(VENDORS, n),
                              "amount": r.lognormal(9.5, 0.5, n).round(2), "iban_changed": r.random(n) < 0.1})
        batch.loc[3, "amount"] = 950_000.0
        batch.loc[n] = ["TP-200", "Blocked Corp", 12_000.0, False]
        batch.loc[n + 1] = batch.loc[5].copy(); batch.loc[n + 1, "pay_id"] = "TP-201"
        return {"history": hist, "batch": batch}

    def run(self, data=None):
        data = data or self.sample_data()
        hist, b = data["history"], data["batch"].copy()
        stats = hist.assign(la=np.log(hist.amount)).groupby("beneficiary").la.agg(["mean", "std"])
        b = b.join(stats, on="beneficiary")
        b["anomaly_z"] = ((np.log(b.amount) - b["mean"]) / b["std"]).round(2)
        b["duplicate"] = b.duplicated(["beneficiary", "amount"], keep="first")
        def screen(r):
            if r.beneficiary in WATCHLIST: return "BLOCK: watchlist"
            if r.duplicate: return "HOLD: duplicate"
            if r.iban_changed: return "HOLD: bank details changed - call-back"
            if pd.notna(r.anomaly_z) and abs(r.anomaly_z) > 3: return "HOLD: amount anomaly"
            return "Clear"
        b["screen"] = b.apply(screen, axis=1)
        b["approvers"] = b.amount.map(lambda a: next(ap for lim, ap in APPROVAL_MATRIX if a <= lim))
        clear = b[b.screen == "Clear"]
        pain001 = {"GrpHdr": {"NbOfTxs": len(clear), "CtrlSum": round(clear.amount.sum(), 2)},
                   "CdtTrfTxInf": [{"EndToEndId": r.pay_id, "Cdtr": r.beneficiary, "InstdAmt": r.amount} for r in clear.itertuples()]}
        return AgentResult(self.name, {"payments": len(b), "cleared": len(clear), "held_or_blocked": int((b.screen != "Clear").sum()),
                                       "release_value": round(clear.amount.sum(), 2)},
                           b[["pay_id", "beneficiary", "amount", "anomaly_z", "screen", "approvers"]], extras={"pain001": pain001})


if __name__ == "__main__":
    TreasuryPaymentsAgent.cli()
