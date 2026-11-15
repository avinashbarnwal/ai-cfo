"""Cash Forecasting Agent (POC)

13-week direct cash forecast by flow category. Each category is forecast with
seasonal-naive + trend (stand-in for HighRadius' per-category ML models),
AR receipts are layered from open invoices using customer pay behaviour, and
the agent reports forecast accuracy (MAPE) on a back-test window.
"""
import numpy as np
import pandas as pd

from common import AgentResult, BaseAgent, narrate
from common.synth import TODAY, rng

CATS = {"AR receipts": 900_000, "Other inflows": 60_000, "Payroll": -420_000, "AP vendors": -380_000, "Rent & utilities": -60_000, "Tax": -90_000}


class CashForecastingAgent(BaseAgent):
    name = "Cash Forecasting Agent"
    category = "Treasury & Risk"
    description = "13-week category-level forecast with back-tested accuracy."

    def sample_data(self):
        r = rng(self.seed)
        weeks = pd.date_range(end=TODAY, periods=52, freq="W-FRI")
        rows = []
        for i, w in enumerate(weeks):
            for c, base in CATS.items():
                season = 1 + 0.15 * np.sin(2 * np.pi * i / 13)
                v = base * season * (1 + 0.003 * i) * r.normal(1, 0.08)
                if c == "Payroll" and i % 2:
                    v = base * 0.1
                if c == "Tax" and i % 13 != 0:
                    v = 0
                rows.append({"week": w, "category": c, "amount": round(v, 0)})
        return {"history": pd.DataFrame(rows), "opening_cash": pd.DataFrame({"v": [3_500_000]})}

    @staticmethod
    def _fc(series, h, season=26):
        trend = (series.iloc[-season:].mean() / max(abs(series.iloc[-2 * season:-season].mean()), 1)) if series.abs().sum() else 1
        trend = np.clip(trend if series.iloc[-season:].mean() * series.iloc[-2 * season:-season].mean() > 0 else 1, 0.8, 1.2)
        return np.array([series.iloc[-season + (k % season)] for k in range(h)]) * trend

    def run(self, data=None, horizon=13):
        data = data or self.sample_data()
        h = data["history"].pivot(index="week", columns="category", values="amount")
        # back-test: train on all but last 13, compare
        test = h.iloc[-13:]
        bt = pd.DataFrame({c: self._fc(h[c].iloc[:-13], 13) for c in h}, index=test.index)
        mape = {c: round(float(np.mean(np.abs(bt[c] - test[c])) / max(np.mean(np.abs(test[c])), 1) * 100), 1) for c in h}
        fut_idx = pd.date_range(h.index[-1] + pd.Timedelta(weeks=1), periods=horizon, freq="W-FRI")
        fc = pd.DataFrame({c: self._fc(h[c], horizon) for c in h}, index=fut_idx).round(0)
        fc["net_flow"] = fc.sum(axis=1)
        fc["closing_cash"] = float(data["opening_cash"].v.iloc[0]) + fc.net_flow.cumsum()
        low = fc.closing_cash.idxmin()
        note = narrate("Summarise a 13-week cash forecast for the CFO in 4 bullets; mention low point and accuracy.",
                       {"low_week": str(low.date()), "low_cash": fc.closing_cash.min(), "mape_by_category": mape},
                       f"Lowest projected cash ${fc.closing_cash.min()/1e6:,.2f}M in week of {low.date()}. Back-test MAPE: {mape}.")
        return AgentResult(self.name, {"horizon_weeks": horizon, "ending_cash": float(fc.closing_cash.iloc[-1]),
                                       "low_point": {"week": str(low.date()), "cash": float(fc.closing_cash.min())},
                                       "backtest_mape_pct": mape},
                           fc.reset_index(names="week"), note)


if __name__ == "__main__":
    CashForecastingAgent.cli()
