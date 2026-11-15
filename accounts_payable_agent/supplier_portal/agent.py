"""Supplier Portal Agent (POC)

Self-service assistant for suppliers: answers "where is my payment?" queries
from AP data, and screens new-supplier onboarding (bank detail change risk,
missing tax forms, sanctions list hit).
"""
import pandas as pd

from common import AgentResult, BaseAgent, narrate
from common.synth import TODAY, VENDORS, rng

SANCTIONS = {"Shady Trading LLC"}


class SupplierPortalAgent(BaseAgent):
    name = "Supplier Portal Agent"
    category = "Accounts Payable"
    description = "Supplier inquiry bot + onboarding risk screening."

    def sample_data(self):
        r = rng(self.seed)
        n = 25
        ap = pd.DataFrame({"vendor": r.choice(VENDORS, n), "invoice_no": [f"VI-{8800 + i}" for i in range(n)],
                           "amount": r.uniform(500, 30_000, n).round(2),
                           "status": r.choice(["Approved - scheduled", "Paid", "On hold - price variance", "Pending approval"], n),
                           "pay_date": TODAY + pd.to_timedelta(r.integers(-10, 20, n), unit="D")})
        onboarding = pd.DataFrame([
            {"supplier": "Nova Components", "w9_or_tax_form": True, "bank_change_last_30d": False, "domain_matches": True},
            {"supplier": "Shady Trading LLC", "w9_or_tax_form": True, "bank_change_last_30d": False, "domain_matches": True},
            {"supplier": "Apex Steel", "w9_or_tax_form": True, "bank_change_last_30d": True, "domain_matches": False},
            {"supplier": "Orbit Tools", "w9_or_tax_form": False, "bank_change_last_30d": False, "domain_matches": True},
        ])
        queries = ["Where is payment for VI-8803?", "Status of invoice VI-8810", "When will VI-8815 be paid?"]
        return {"ap": ap, "onboarding": onboarding, "queries": pd.DataFrame({"q": queries})}

    def run(self, data=None):
        data = data or self.sample_data()
        ap = data["ap"].set_index("invoice_no")
        answers = []
        for q in data["queries"].q:
            inv = next((t.strip("?") for t in q.split() if t.startswith("VI-")), None)
            if inv in ap.index:
                r = ap.loc[inv]
                fb = f"{inv} ({r.vendor}, ${r.amount:,.2f}) is '{r.status}'; payment date {r.pay_date.date()}."
                answers.append({"query": q, "answer": narrate("You are a supplier help-desk agent. Answer in 1-2 sentences.", {"q": q, "record": r.to_dict()}, fb)})
        ob = data["onboarding"].copy()
        def risk(r):
            flags = []
            if r.supplier in SANCTIONS: flags.append("SANCTIONS HIT")
            if r.bank_change_last_30d and not r.domain_matches: flags.append("Bank-change fraud risk: call-back verification")
            if not r.w9_or_tax_form: flags.append("Missing tax form")
            return flags
        ob["risk_flags"] = ob.apply(risk, axis=1)
        ob["decision"] = ob.risk_flags.map(lambda f: "Approve" if not f else ("Block" if "SANCTIONS HIT" in f else "Hold"))
        return AgentResult(self.name, {"queries_answered": len(answers), "onboarding_reviewed": len(ob),
                                       "blocked_or_held": int((ob.decision != "Approve").sum())},
                           ob, "\n".join(f"Q: {a['query']}\nA: {a['answer']}" for a in answers))


if __name__ == "__main__":
    SupplierPortalAgent.cli()
