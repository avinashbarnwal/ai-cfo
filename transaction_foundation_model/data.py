"""Step 1 - load transactions, split them in time order, and build the raw-feature baseline.

Works with the IBM TabFormer card-transaction CSV (``card_transaction.v1.csv``,
~24.4M rows) or a synthetic generator, so the whole pipeline runs with no setup.

Standard schema used everywhere downstream:
    user, card, ts, amount, use_chip, merchant, merchant_city, merchant_state,
    zip, mcc, errors, is_fraud
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RAW_FEATURES = [
    "amount", "hour", "dow", "day", "month", "mcc", "merchant_hash", "chip_code",
    "zip3", "state_code", "has_error", "card", "secs_since_prev",
]  # 13 hand-engineered features = the XGBoost baseline


# --------------------------------------------------------------------------- loaders
def load_tabformer(path: str, nrows: int | None = None) -> pd.DataFrame:
    """Read the IBM TabFormer CSV and map it to the standard schema."""
    df = pd.read_csv(path, nrows=nrows, dtype={"Zip": "float64", "MCC": "int64"})
    hhmm = df["Time"].str.split(":", expand=True).astype(int)
    ts = pd.to_datetime(
        dict(year=df["Year"], month=df["Month"], day=df["Day"], hour=hhmm[0], minute=hhmm[1])
    )
    out = pd.DataFrame({
        "user": df["User"].astype(np.int64),
        "card": df["Card"].astype(np.int64),
        "ts": ts,
        "amount": df["Amount"].str.replace("$", "", regex=False).astype(float),
        "use_chip": df["Use Chip"].astype(str),
        "merchant": df["Merchant Name"].astype(str),
        "merchant_city": df["Merchant City"].astype(str),
        "merchant_state": df["Merchant State"].fillna("NA").astype(str),
        "zip": df["Zip"].fillna(0).astype(np.int64),
        "mcc": df["MCC"].astype(np.int64),
        "errors": df["Errors?"].fillna("").astype(str),
        "is_fraud": (df["Is Fraud?"].astype(str).str.strip() == "Yes").astype(np.int8),
    })
    return _sort(out)


def synthetic_transactions(n_users: int = 400, days: int = 365, fraud_user_share: float = 0.35,
                           seed: int = 7) -> pd.DataFrame:
    """Card histories where fraud is only obvious *relative to the user's own history*.

    Each user has a home state/zip, favourite merchants, a spend scale and active
    hours. Fraud episodes are bursts of card-not-present spend in a foreign state
    at odd hours. Legit travel episodes look similar, so a single row is ambiguous
    and sequence context is what separates them - the case foundation models fix.
    """
    r = np.random.default_rng(seed)
    states = np.array(["CA", "NY", "TX", "FL", "IL", "WA", "GA", "MA", "AZ", "CO", "NJ", "OH"])
    n_merch = 600
    merch_mcc = r.choice([5411, 5812, 5541, 5912, 4121, 5732, 5999, 4829, 7011, 5311, 5814, 4900], n_merch)
    merch_state = r.choice(states, n_merch)
    start = pd.Timestamp("2025-01-01")
    rows: list[dict] = []

    for u in range(n_users):
        home = r.integers(len(states))
        home_zip = int(r.integers(10000, 99999))
        local = np.where(merch_state == states[home])[0]
        favs = r.choice(local if len(local) >= 8 else np.arange(n_merch), size=8, replace=False)
        scale = r.lognormal(3.4, 0.7)
        peak = r.integers(0, 24)  # some users are night owls - hour alone is not a fraud signal
        n_cards = r.integers(1, 3)
        per_day = r.uniform(0.6, 2.0)
        online_rate = r.uniform(0.05, 0.6)

        n = r.poisson(per_day * days)
        t = np.sort(r.uniform(0, days, n))
        hours = np.mod(r.normal(peak, 3, n), 24)
        ts = start + pd.to_timedelta(np.floor(t) * 86400 + hours * 3600, unit="s")
        merch = np.where(r.random(n) < 0.8, r.choice(favs, n), r.integers(0, n_merch, n))
        online = r.random(n) < online_rate
        for i in range(n):
            m = merch[i]
            rows.append(dict(user=u, card=int(r.integers(n_cards)), ts=ts[i],
                             amount=round(float(r.lognormal(np.log(scale), 0.6)), 2),
                             use_chip="Online Transaction" if online[i] else r.choice(["Chip Transaction", "Swipe Transaction"], p=[0.8, 0.2]),
                             merchant=f"M{m}", merchant_state=states[home], zip=home_zip,
                             mcc=int(merch_mcc[m]), errors=("Insufficient Balance," if r.random() < 0.01 else ""),
                             is_fraud=0))

        def episode(fraud: bool) -> None:
            """Fraud and legit travel share the same row-level look: a burst in another state at new merchants.
            What differs is the user's own history: amounts far above their usual scale, a channel
            they rarely use, and an hour far from their routine."""
            t0 = start + pd.Timedelta(days=float(r.uniform(5, days - 1)))
            away = r.choice(np.delete(states, home))
            k = int(r.integers(3, 9))
            hour0 = (peak + (r.integers(8, 16) if fraud else r.integers(-2, 3))) % 24
            amt_mult = r.uniform(2.5, 5) if fraud else r.uniform(0.8, 1.5)
            for j in range(k):
                rows.append(dict(
                    user=u, card=0,
                    ts=t0.normalize() + pd.Timedelta(hours=float(hour0)) + pd.Timedelta(minutes=float(j * r.uniform(3, 40))),
                    amount=round(float(r.lognormal(np.log(scale * amt_mult), 0.5)), 2),
                    use_chip=("Online Transaction" if (r.random() < (1 - online_rate if fraud else online_rate))
                              else "Chip Transaction"),
                    merchant=f"M{int(r.integers(n_merch))}", merchant_state=away,
                    zip=int(r.integers(10000, 99999)), mcc=int(r.choice(merch_mcc)),
                    errors=("Bad CVV," if r.random() < (0.05 if fraud else 0.02) else ""), is_fraud=int(fraud)))

        if r.random() < fraud_user_share:
            for _ in range(int(r.integers(1, 3))):
                episode(fraud=True)
        for _ in range(int(r.poisson(2.5))):
            episode(fraud=False)

    df = pd.DataFrame(rows)
    df["merchant_city"] = df["merchant_state"] + "_city"
    df["is_fraud"] = df["is_fraud"].astype(np.int8)
    return _sort(df)


def _sort(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["user", "ts"], kind="stable").reset_index(drop=True)


# --------------------------------------------------------------------------- splits + features
def temporal_split(df: pd.DataFrame, train: float = 0.8, val: float = 0.1) -> pd.Series:
    """First 80% of transactions by time -> train, next 10% -> val, last 10% -> test."""
    rank = df["ts"].rank(method="first").to_numpy() / len(df)
    return pd.Series(np.select([rank <= train, rank <= train + val], ["train", "val"], "test"),
                     index=df.index, name="split")


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Calendar, geography and recency columns shared by the tokenizer and the baseline.

    Assumes ``df`` is sorted by (user, ts), which every loader guarantees.
    """
    d = df.copy()
    d["hour"] = d["ts"].dt.hour
    d["dow"] = d["ts"].dt.dayofweek
    d["day"] = d["ts"].dt.day
    d["month"] = d["ts"].dt.month
    d["zip3"] = (d["zip"] // 100).astype(np.int64)
    d["has_error"] = (d["errors"].str.len() > 0).astype(np.int8)
    prev = d.groupby("user")["ts"].shift()
    d["secs_since_prev"] = (d["ts"] - prev).dt.total_seconds().fillna(-1.0)
    return d


def raw_features(d: pd.DataFrame) -> pd.DataFrame:
    """The 13 hand-engineered numeric features for the XGBoost baseline."""
    x = pd.DataFrame(index=d.index)
    x["amount"] = d["amount"]
    for c in ["hour", "dow", "day", "month", "mcc", "zip3", "has_error", "card", "secs_since_prev"]:
        x[c] = d[c]
    x["merchant_hash"] = (pd.util.hash_pandas_object(d["merchant"], index=False) % 100_003).astype(np.int64)
    x["chip_code"] = d["use_chip"].astype("category").cat.codes
    x["state_code"] = d["merchant_state"].astype("category").cat.codes
    return x[RAW_FEATURES].astype(np.float32)
