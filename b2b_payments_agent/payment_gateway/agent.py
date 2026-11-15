"""Payment Gateway Agent (POC)

Smart routing for B2B customer payments: picks the cheapest eligible
processor/rail per transaction (card, ACH, RTP, wire) given amount, currency
and authorisation-rate history, and suggests retries for soft declines.
"""
import pandas as pd

from common import AgentResult, BaseAgent
from common.synth import CUSTOMERS, rng

ROUTES = [  # name, method, pct fee, fixed fee, auth rate, currencies, max amount
    ("Stripe", "card", 0.029, 0.30, 0.94, {"USD", "EUR", "GBP"}, 100_000),
    ("Adyen", "card", 0.026, 0.12, 0.96, {"USD", "EUR", "GBP", "INR"}, 250_000),
    ("JPM ACH", "ach", 0.0, 0.25, 0.99, {"USD"}, 5_000_000),
    ("RTP Network", "rtp", 0.0, 0.45, 0.995, {"USD"}, 1_000_000),
    ("SWIFT Wire", "wire", 0.0, 25.0, 0.999, {"USD", "EUR", "GBP", "INR"}, float("inf")),
]


class PaymentGatewayAgent(BaseAgent):
    name = "Payment Gateway Agent"
    category = "B2B Payments"
    description = "Cost- and auth-rate-optimal routing of customer payments."

    def sample_data(self):
        r = rng(self.seed)
        n = 20
        return {"payments": pd.DataFrame({
            "txn_id": [f"PG-{i}" for i in range(n)], "customer": r.choice(CUSTOMERS, n),
            "amount": r.lognormal(8.5, 1.3, n).round(2), "currency": r.choice(["USD", "USD", "EUR", "GBP", "INR"], n),
            "preferred_method": r.choice(["card", "ach", "any"], n), "urgent": r.random(n) < 0.2,
            "last_decline_code": r.choice([None, None, None, "insufficient_funds", "do_not_honor", "issuer_unavailable"], n)})}

    def run(self, data=None):
        p = (data or self.sample_data())["payments"].copy()
        def route(t):
            opts = []
            for name, m, pct, fix, auth, ccys, mx in ROUTES:
                if t.currency not in ccys or t.amount > mx: continue
                if t.preferred_method not in ("any", m): continue
                if t.urgent and m == "ach": continue
                cost = t.amount * pct + fix
                opts.append((cost / auth, name, m, round(cost, 2), auth))  # expected cost per successful payment
            if not opts:
                return pd.Series({"route": "SWIFT Wire", "method": "wire", "fee": 25.0, "auth_rate": 0.999})
            _, name, m, cost, auth = min(opts)
            return pd.Series({"route": name, "method": m, "fee": cost, "auth_rate": auth})
        p = p.join(p.apply(route, axis=1))
        p["retry_plan"] = p.last_decline_code.map({"insufficient_funds": "Retry in 3 days", "issuer_unavailable": "Retry in 1h on alt processor",
                                                  "do_not_honor": "Do not retry - request ACH"}).fillna("-")
        naive = (p.amount * 0.029 + 0.30).sum()
        return AgentResult(self.name, {"txns": len(p), "total_fees": round(p.fee.sum(), 2), "fees_if_all_card": round(naive, 2),
                                       "savings": round(naive - p.fee.sum(), 2), "route_mix": p.route.value_counts().to_dict()},
                           p[["txn_id", "amount", "currency", "preferred_method", "route", "fee", "retry_plan"]])


if __name__ == "__main__":
    PaymentGatewayAgent.cli()
