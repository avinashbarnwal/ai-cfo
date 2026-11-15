"""e-Invoicing Portal Agent (POC)

Validates outgoing invoices against country e-invoice rules (mandatory fields,
tax math, format), builds a UBL-style JSON payload, and picks the delivery channel
(Peppol, customer portal, GST IRP, email PDF).
"""
import pandas as pd

from common import AgentResult, BaseAgent
from common.synth import CUSTOMERS, rng

CHANNEL = {"DE": "Peppol", "FR": "Chorus Pro / PDP", "IN": "GST IRP (IRN + QR)", "IT": "SdI", "US": "Customer AP portal / email PDF"}
REQUIRED = ["buyer_tax_id", "po_number", "line_total", "tax_rate"]


class EInvoicingAgent(BaseAgent):
    name = "e-Invoicing Portal Agent"
    category = "Order to Cash"
    description = "Compliance validation + channel routing for e-invoices."

    def sample_data(self):
        r = rng(self.seed)
        n = 20
        df = pd.DataFrame({
            "invoice_id": [f"EINV-{700 + i}" for i in range(n)],
            "customer": r.choice(CUSTOMERS, n),
            "country": r.choice(list(CHANNEL), n),
            "buyer_tax_id": r.choice(["DE123456789", "", "29ABCDE1234F1Z5", "FR12345678901"], n),
            "po_number": r.choice(["PO-1", "", "PO-77", "PO-9"], n),
            "line_total": r.uniform(1_000, 20_000, n).round(2),
            "tax_rate": r.choice([0.19, 0.18, 0.20, 0.22, 0.0], n),
        })
        df["tax_amount"] = (df.line_total * df.tax_rate).round(2)
        df.loc[::7, "tax_amount"] += 3.5  # inject tax math errors
        return {"invoices": df}

    def run(self, data=None):
        d = (data or self.sample_data())["invoices"].copy()
        def errors(r):
            e = [f for f in REQUIRED if r[f] in ("", None)]
            if abs(r.line_total * r.tax_rate - r.tax_amount) > 0.01:
                e.append("tax_mismatch")
            if r.country != "US" and r.tax_rate == 0:
                e.append("zero_rate_needs_exemption_code")
            return e
        d["errors"] = d.apply(errors, axis=1)
        d["status"] = d.errors.map(lambda e: "Ready" if not e else "Blocked")
        d["channel"] = d.country.map(CHANNEL)
        d["payload"] = d.apply(lambda r: {"cbc:ID": r.invoice_id, "cac:AccountingCustomerParty": r.customer,
                                          "cbc:TaxAmount": r.tax_amount, "cbc:PayableAmount": round(r.line_total + r.tax_amount, 2)}
                               if r.status == "Ready" else None, axis=1)
        return AgentResult(self.name, {"invoices": len(d), "ready": int((d.status == "Ready").sum()),
                                       "blocked": int((d.status == "Blocked").sum())},
                           d[["invoice_id", "country", "channel", "status", "errors"]])


if __name__ == "__main__":
    EInvoicingAgent.cli()
