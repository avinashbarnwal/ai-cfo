"""AP Automation Agent (POC)

Extracts invoice fields (regex stand-in for OCR/LLM extraction), performs
3-way match (PO / goods receipt / invoice) with tolerances, detects duplicates,
and codes GL accounts.
"""
import re

import pandas as pd

from common import AgentResult, BaseAgent, narrate
from common.synth import VENDORS, rng

GL_MAP = {"Apex Steel": "5000-Raw Materials", "BlueLine Freight": "6100-Freight", "Crest Packaging": "5010-Packaging",
          "Delta IT Services": "6400-IT Services", "Evergreen Paper": "6200-Office Supplies", "Falcon Office": "6200-Office Supplies",
          "Granite Utilities": "6300-Utilities", "Harbor Leasing": "6500-Rent & Leases", "Ion Chemicals": "5000-Raw Materials",
          "Juno Staffing": "6600-Contract Labor"}
PRICE_TOL, QTY_TOL = 0.02, 0.0


class APAutomationAgent(BaseAgent):
    name = "AP Automation Agent"
    category = "Accounts Payable"
    description = "Invoice capture, 3-way match, duplicate detection, GL coding."

    def sample_data(self):
        r = rng(self.seed)
        n = 18
        po = pd.DataFrame({"po": [f"PO-{3000 + i}" for i in range(n)], "vendor": r.choice(VENDORS, n),
                           "qty": r.integers(10, 200, n), "unit_price": r.uniform(5, 120, n).round(2)})
        gr = po[["po", "qty"]].rename(columns={"qty": "received_qty"}).copy()
        gr.loc[3, "received_qty"] -= 5
        raw = []
        for i, p in po.iterrows():
            price = p.unit_price * (1.05 if i == 5 else 1)
            raw.append(f"Vendor: {p.vendor}\nInvoice No: VI-{8800 + i}\nPO: {p.po}\nQty: {p.qty}\nUnit Price: {price:.2f}")
        raw.append(raw[2].replace("VI-8802", "VI-8802"))  # duplicate submission
        return {"po": po, "goods_receipts": gr, "invoice_text": pd.DataFrame({"text": raw})}

    @staticmethod
    def extract(text):
        g = lambda k: re.search(rf"{k}:\s*(.+)", text).group(1).strip()
        return {"vendor": g("Vendor"), "invoice_no": g("Invoice No"), "po": g("PO"),
                "qty": int(g("Qty")), "unit_price": float(g("Unit Price"))}

    def run(self, data=None):
        data = data or self.sample_data()
        inv = pd.DataFrame([self.extract(t) for t in data["invoice_text"].text])
        m = inv.merge(data["po"], on="po", suffixes=("", "_po")).merge(data["goods_receipts"], on="po")
        m["duplicate"] = m.duplicated(["vendor", "invoice_no"], keep="first")
        m["price_var_pct"] = ((m.unit_price - m.unit_price_po) / m.unit_price_po).round(4)
        def status(r):
            if r.duplicate: return "Reject: duplicate"
            if abs(r.price_var_pct) > PRICE_TOL: return "Exception: price variance"
            if r.qty > r.received_qty: return "Exception: qty > received"
            return "Matched -> post"
        m["status"] = m.apply(status, axis=1)
        m["gl_account"] = m.vendor.map(GL_MAP)
        m["amount"] = (m.qty * m.unit_price).round(2)
        ex = m[m.status.str.startswith("Exception")]
        note = narrate("Summarise AP exceptions for the AP manager in 3 bullets with next steps.",
                       ex[["vendor", "invoice_no", "status", "price_var_pct", "qty", "received_qty"]].to_dict("records"),
                       f"{len(ex)} exceptions need buyer review; duplicates auto-rejected.")
        return AgentResult(self.name, {"invoices": len(m), "touchless_pct": round((m.status == "Matched -> post").mean() * 100, 1),
                                       "exceptions": len(ex), "duplicates": int(m.duplicate.sum())},
                           m[["invoice_no", "vendor", "po", "amount", "gl_account", "price_var_pct", "status"]], note)


if __name__ == "__main__":
    APAutomationAgent.cli()
