"""Compare TypeSafe Jev vs Claude Haiku 5.5 on bank transaction categorization.

Dataset: Kaggle apoorvwatsky/bank-transaction-data (bank.xlsx, ~116k rows, no labels).

For every sampled transaction both models answer the same two questions:
  1. category        - one of CATEGORIES (cash-flow category)
  2. is_intercompany - transfer between own / group accounts?

Because the dataset has no labels we report:
  - agreement between the two models
  - accuracy on a "rule-labeled" subset (descriptions whose category is unambiguous
    from a keyword, e.g. CASHDEP/... -> cash_deposit). This is a sanity check, not ground truth.
  - confidence-threshold coverage (how many rows could be auto-posted at p >= 0.95)
  - latency (p50/p95) and cost

Env vars:
  TYPESAFE_API_KEY   - Jev (TypeSafe System One) key. Skipped if unset.
  ANTHROPIC_API_KEY  - Claude key. Skipped if unset.

Usage:
  python compare_jev_haiku.py --n 200 --workers 8 --out results
"""
import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import kagglehub
import numpy as np
import pandas as pd
import requests

# ---------------------------------------------------------------- secrets
KEY_NAMES = ("TYPESAFE_API_KEY", "ANTHROPIC_API_KEY")


def mask(v):
    """Show only enough to identify a key: 'sk-ant...wxyz'."""
    return "<unset>" if not v else (v[:6] + "..." + v[-4:] if len(v) > 12 else "****")


def load_keys(env_file, prompt):
    """Keys come from the environment, then a git-ignored .env file, then a hidden prompt.
    They are never printed or written to outputs - only masked forms are logged."""
    if os.path.exists(env_file):
        for line in open(env_file):
            k, _, v = line.strip().partition("=")
            if k in KEY_NAMES and v and not os.environ.get(k):
                os.environ[k] = v.strip().strip("'\"")
    if prompt:
        import getpass

        for k in KEY_NAMES:
            if not os.environ.get(k):
                v = getpass.getpass(f"{k} (hidden, Enter to skip): ").strip()
                if v:
                    os.environ[k] = v
    for k in KEY_NAMES:
        print(f"{k}: {mask(os.environ.get(k))}")


# ---------------------------------------------------------------- categories
CATEGORIES = {
    "customer_receipt": "Incoming payment from a customer / payment gateway settlement (AR collection)",
    "cash_deposit": "Physical cash deposited at a branch or ATM",
    "internal_transfer": "Transfer between the company's own accounts or group entities, incl. sweeps",
    "vendor_payment": "Outgoing payment to a supplier, vendor or service provider",
    "payroll": "Salary or wage payments to employees",
    "tax_payment": "GST, TDS, income tax or other statutory payments",
    "bank_fee_interest": "Bank charges, fees, commissions or interest debit/credit",
    "loan_financing": "Loan disbursement, EMI, repayment or other financing flow",
    "refund_reversal": "Refund, reversal, return or chargeback of an earlier transaction",
    "cash_withdrawal": "Cash withdrawn (ATM/AEPS/branch)",
    "other": "None of the above / not determinable",
}
CAT_LIST = list(CATEGORIES)

# Unambiguous keyword rules -> weak labels for a sanity-check accuracy number.
RULES = [
    (r"^CASHDEP/", "cash_deposit"),
    (r"^SWEEP TRF", "internal_transfer"),
    (r"INTERNAL FUND TRANSFE", "internal_transfer"),
    (r"AEPS NPCI WDL", "cash_withdrawal"),
    (r"\bREVERSAL\b|\bREV\b", "refund_reversal"),
    (r"\bCHRG|\bCHARGES\b|\bCOMMISSION\b", "bank_fee_interest"),
]

INSTRUCTIONS = (
    "This is one line from an Indian corporate bank statement. "
    "Classify it into the single best cash-flow category."
)

# ---------------------------------------------------------------- data
def load_data():
    path = kagglehub.dataset_download("apoorvwatsky/bank-transaction-data")
    print("Path to dataset files:", path)
    df = pd.read_excel(os.path.join(path, "bank.xlsx"))
    df = df.rename(columns=lambda c: c.strip())
    df = df[df["TRANSACTION DETAILS"].notna()].copy()
    df["direction"] = np.where(df["DEPOSIT AMT"].fillna(0) > 0, "credit", "debit")
    df["amount"] = df["DEPOSIT AMT"].fillna(0) + df["WITHDRAWAL AMT"].fillna(0)
    df["details"] = df["TRANSACTION DETAILS"].astype(str).str.strip()
    return df


def sample(df, n, seed):
    """Half random rows, half drawn so each distinct description prefix is represented."""
    df = df.copy()
    df["prefix"] = df["details"].str.upper().str[:12]
    diverse = df.sample(frac=1, random_state=seed).drop_duplicates("prefix")
    diverse = diverse.sample(min(n // 2, len(diverse)), random_state=seed)
    rest = df.drop(diverse.index).sample(n - len(diverse), random_state=seed)
    out = pd.concat([diverse, rest]).reset_index().rename(columns={"index": "row_id"})
    return out.drop(columns="prefix")


def rule_label(details):
    d = details.upper()
    for pat, cat in RULES:
        if re.search(pat, d):
            return cat
    return None


def state_for(row):
    return {
        "account_no": str(row["Account No"]).strip("'"),
        "date": str(row["DATE"])[:10],
        "transaction_details": row["details"],
        "direction": row["direction"],
        "amount_inr": float(row["amount"]),
        "cheque_no": None if pd.isna(row["CHQ.NO."]) else str(int(row["CHQ.NO."])),
    }


# ---------------------------------------------------------------- Jev
JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_PRICE_PER_MTOK = 0.042  # input only; output currently free


def run_jev(row, session, model):
    body = {
        "model": model,
        "state": state_for(row),
        "questions": {
            "category": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": CATEGORIES},
            "is_intercompany": {
                "type": "noul",
                "instructions": "Is this a transfer between the company's own accounts or group entities?",
            },
        },
    }
    t0 = time.perf_counter()
    r = session.post(JEV_URL, json=body, timeout=60)
    ms = (time.perf_counter() - t0) * 1000
    r.raise_for_status()
    j = r.json()
    cat = j["answers"]["category"]
    probs = cat.get("probabilities", {})
    in_tok = j.get("usage", {}).get("input_tokens", 0)
    return {
        "jev_category": cat["choice"],
        "jev_p": probs.get(cat["choice"]),
        "jev_confidence": cat.get("confidence"),
        "jev_is_interco_p": j["answers"]["is_intercompany"]["noul"],
        "jev_ms": ms,
        "jev_in_tok": in_tok,
        "jev_cost": in_tok * JEV_PRICE_PER_MTOK / 1e6,
        "jev_model": j.get("model"),
    }


# ---------------------------------------------------------------- Claude Haiku
HAIKU_MODEL = "claude-haiku-5-5"
HAIKU_IN, HAIKU_OUT = 0.10, 0.50  # $/MTok (prompts <=100K)

SYSTEM = (
    INSTRUCTIONS
    + "\nCategories:\n"
    + "\n".join(f"- {k}: {v}" for k, v in CATEGORIES.items())
    + "\nAlso say whether it is intercompany (between own/group accounts), and give your "
    "probability (0-1) that the chosen category is correct."
)
SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": CAT_LIST},
        "confidence": {"type": "number"},
        "is_intercompany": {"type": "boolean"},
    },
    "required": ["category", "confidence", "is_intercompany"],
    "additionalProperties": False,
}


def run_haiku(row, client, effort):
    t0 = time.perf_counter()
    resp = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(state_for(row))}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    ms = (time.perf_counter() - t0) * 1000
    if resp.stop_reason == "refusal":
        raise RuntimeError("refusal")
    text = next(b.text for b in resp.content if b.type == "text")
    d = json.loads(text)
    u = resp.usage
    return {
        "haiku_category": d["category"],
        "haiku_p": d["confidence"],
        "haiku_is_interco": d["is_intercompany"],
        "haiku_ms": ms,
        "haiku_in_tok": u.input_tokens,
        "haiku_out_tok": u.output_tokens,
        "haiku_cost": (u.input_tokens * HAIKU_IN + u.output_tokens * HAIKU_OUT) / 1e6,
    }


# ---------------------------------------------------------------- runner
def run_model(name, fn, rows, workers):
    def safe(row):
        try:
            return fn(row)
        except Exception as e:  # keep going; record the error per row
            msg = str(e)
            for k in KEY_NAMES:
                if os.environ.get(k):
                    msg = msg.replace(os.environ[k], mask(os.environ[k]))
            return {f"{name}_error": f"{type(e).__name__}: {msg[:200]}"}

    t0 = time.perf_counter()
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(safe, [r for _, r in rows.iterrows()]))
    out = pd.DataFrame(res, index=rows.index)
    n_err = out[f"{name}_error"].notna().sum() if f"{name}_error" in out else 0
    print(f"{name}: {len(rows)} rows in {time.perf_counter() - t0:.1f}s, errors={n_err}")
    if n_err:
        print("  first error:", out[f"{name}_error"].dropna().iloc[0])
    return out


def summarize(df, models):
    lines = [f"Rows: {len(df)}"]
    labeled = df[df["rule_label"].notna()]
    for m in models:
        c, p, ms, cost = f"{m}_category", f"{m}_p", f"{m}_ms", f"{m}_cost"
        if c not in df:
            continue
        ok = df[c].notna()
        err = (~ok).sum()
        lines.append(f"\n== {m} ==  ok={ok.sum()} errors={err}")
        lines.append(
            f"latency ms p50={df.loc[ok, ms].median():.0f} p95={df.loc[ok, ms].quantile(.95):.0f}"
        )
        per_m = df.loc[ok, cost].mean() * 1e6
        lines.append(f"cost total=${df.loc[ok, cost].sum():.5f}  per 1M txns=${per_m:,.2f}")
        if len(labeled):
            acc = (labeled[c] == labeled["rule_label"]).mean()
            lines.append(f"accuracy on rule-labeled subset (n={len(labeled)}): {acc:.1%}")
        for th in (0.8, 0.9, 0.95):
            hi = df[ok & (df[p] >= th)]
            cov = len(hi) / max(ok.sum(), 1)
            lab = hi[hi["rule_label"].notna()]
            acc = (lab[c] == lab["rule_label"]).mean() if len(lab) else float("nan")
            lines.append(f"  p>={th}: coverage {cov:.1%}, rule-subset acc {acc:.1%} (n={len(lab)})")
        lines.append("category distribution:\n" + df[c].value_counts().to_string())
    if {"jev_category", "haiku_category"} <= set(df.columns):
        both = df["jev_category"].notna() & df["haiku_category"].notna()
        agree = (df.loc[both, "jev_category"] == df.loc[both, "haiku_category"]).mean()
        lines.append(f"\n== Jev vs Haiku category agreement: {agree:.1%} (n={both.sum()})")
        lines.append(pd.crosstab(df.loc[both, "jev_category"], df.loc[both, "haiku_category"]).to_string())
        ic = (df.loc[both, "jev_is_interco_p"] >= 0.5) == df.loc[both, "haiku_is_interco"]
        lines.append(f"\nintercompany flag agreement: {ic.mean():.1%}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--jev_model", default="jev-latest")
    ap.add_argument("--haiku_effort", default="low", choices=["low", "medium", "high"])
    ap.add_argument("--out", default="results")
    ap.add_argument("--env_file", default=".env")
    ap.add_argument("--prompt_keys", action="store_true", help="ask for missing keys (hidden input)")
    a = ap.parse_args()
    load_keys(a.env_file, a.prompt_keys)
    os.makedirs(a.out, exist_ok=True)

    df = load_data()
    print("Loaded", df.shape)
    rows = sample(df, a.n, a.seed)
    rows["rule_label"] = rows["details"].map(rule_label)
    print(f"Sampled {len(rows)}; rule-labeled {rows['rule_label'].notna().sum()}")

    parts, models = [rows], []
    if os.environ.get("TYPESAFE_API_KEY"):
        s = requests.Session()
        s.headers["Authorization"] = f"Bearer {os.environ['TYPESAFE_API_KEY']}"
        parts.append(run_model("jev", lambda r: run_jev(r, s, a.jev_model), rows, a.workers))
        models.append("jev")
    else:
        print("TYPESAFE_API_KEY not set -> skipping Jev")

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("ANTHROPIC_API_KEY not set -> skipping Haiku")
    else:
        import anthropic

        client = anthropic.Anthropic()  # ANTHROPIC_API_KEY or `ant auth login` profile
        parts.append(run_model("haiku", lambda r: run_haiku(r, client, a.haiku_effort), rows, a.workers))
        models.append("haiku")

    res = pd.concat(parts, axis=1)
    csv = os.path.join(a.out, "predictions.csv")
    res.to_csv(csv, index=False)
    summary = summarize(res, models)
    with open(os.path.join(a.out, "summary.txt"), "w") as f:
        f.write(summary)
    print(summary)
    print("\nWrote", csv)


if __name__ == "__main__":
    main()
