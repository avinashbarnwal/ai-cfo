"""Cash Application Agent (POC)

Matches incoming bank receipts / remittances to open invoices:
exact reference match -> amount match within customer -> subset-sum (multi-invoice)
-> fuzzy customer-name match. Unmatched items go to an exceptions queue.
"""
from difflib import SequenceMatcher
from itertools import combinations

import numpy as np
import pandas as pd

from common import AgentResult, BaseAgent
from common.synth import invoices, rng


class CashApplicationAgent(BaseAgent):
    name = "Cash Application Agent"
    category = "Order to Cash"
    description = "Auto-matches payments to invoices; routes exceptions."

    def sample_data(self):
        inv = invoices(self.seed)
        open_inv = inv[inv.open_amount > 0].reset_index(drop=True)
        r = rng(self.seed + 1)
        rows, used = [], set()
        for i in range(25):
            k = r.integers(1, 3)
            pool = open_inv[~open_inv.invoice_id.isin(used)]
            picked = pool[pool.customer == r.choice(pool.customer.unique())].head(k)
            used.update(picked.invoice_id)
            if picked.empty:
                continue
            payer = picked.customer.iloc[0]
            kind = i % 4
            ref = " ".join(picked.invoice_id) if kind == 0 else ""
            amt = picked.open_amount.sum() - (round(r.uniform(5, 50), 2) if kind == 3 else 0)
            name = payer.upper().replace(" ", "") + " INC" if kind == 2 else payer
            rows.append({"receipt_id": f"RCPT-{500 + i}", "payer_name": name, "amount": round(amt, 2), "reference": ref})
        return {"open_invoices": open_inv, "receipts": pd.DataFrame(rows)}

    @staticmethod
    def _best_customer(name, customers):
        scores = {c: SequenceMatcher(None, name.lower().replace(" ", ""), c.lower().replace(" ", "")).ratio() for c in customers}
        c = max(scores, key=scores.get)
        return c, scores[c]

    def run(self, data=None):
        data = data or self.sample_data()
        inv, rec = data["open_invoices"].copy(), data["receipts"]
        out = []
        for _, p in rec.iterrows():
            refs = [t for t in p.reference.split() if t in set(inv.invoice_id)]
            if refs:
                out.append((p.receipt_id, "reference", refs, 1.0))
                inv = inv[~inv.invoice_id.isin(refs)]
                continue
            cust, sim = self._best_customer(p.payer_name, inv.customer.unique())
            cand = inv[inv.customer == cust]
            match, method = None, None
            for k in (1, 2, 3):
                for combo in combinations(cand.itertuples(), k):
                    if np.isclose(sum(c.open_amount for c in combo), p.amount, atol=0.01):
                        match, method = [c.invoice_id for c in combo], f"amount (k={k})"
                        break
                if match:
                    break
            if match:
                out.append((p.receipt_id, method, match, round(sim, 2)))
                inv = inv[~inv.invoice_id.isin(match)]
            else:
                out.append((p.receipt_id, "EXCEPTION: short-pay / no match -> deductions", [], round(sim, 2)))
        df = pd.DataFrame(out, columns=["receipt_id", "match_method", "invoices", "confidence"])
        auto = (~df.match_method.str.startswith("EXCEPTION")).mean()
        return AgentResult(self.name, {"receipts": len(df), "auto_match_rate_pct": round(auto * 100, 1),
                                       "exceptions": int((df.match_method.str.startswith("EXCEPTION")).sum())}, df)


if __name__ == "__main__":
    CashApplicationAgent.cli()
