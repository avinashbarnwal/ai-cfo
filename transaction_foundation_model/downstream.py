"""Step 5 - does the foundation model move a downstream metric? Fraud detection with XGBoost.

Three GPU/CPU XGBoost classifiers scored on the same temporal test split:
    Raw         - 13 hand-engineered features (baseline)
    Embeddings  - foundation-model vectors compressed to 64d with PCA
    Combined    - raw + 64d embeddings (77d)

Judge by Average Precision first: at ~0.1% fraud, ROC-AUC saturates and hides
differences in the high-score region where a review team actually works.
Swap ``y`` for any other event label (churn, default, ...) - same pattern.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.decomposition import PCA
from sklearn.metrics import average_precision_score, roc_auc_score


def _xgb_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def balanced_index(y: np.ndarray, neg_per_pos: int, cap: int, rng: np.random.Generator) -> np.ndarray:
    """All positives + ``neg_per_pos`` negatives each (up to ``cap`` rows) - the blog's balanced sample."""
    pos = np.flatnonzero(y == 1)
    neg = np.flatnonzero(y == 0)
    k = min(len(neg), max(1, len(pos)) * neg_per_pos, max(0, cap - len(pos)))
    return np.sort(np.concatenate([pos, rng.choice(neg, k, replace=False)]))


def stratified_holdout(y: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """Up to ``n`` rows that keep the real fraud prevalence."""
    if len(y) <= n:
        return np.arange(len(y))
    idx = []
    for c in (0, 1):
        g = np.flatnonzero(y == c)
        idx.append(rng.choice(g, max(1, round(n * len(g) / len(y))), replace=False))
    return np.sort(np.concatenate(idx))


def fit_xgb(Xtr, ytr, Xva, yva, seed: int = 0) -> xgb.XGBClassifier:
    m = xgb.XGBClassifier(
        n_estimators=800, learning_rate=0.05, max_depth=6, subsample=0.8, colsample_bytree=0.8,
        tree_method="hist", device=_xgb_device(), eval_metric="aucpr", early_stopping_rounds=50,
        random_state=seed, n_jobs=-1)
    m.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
    return m


def evaluate(raw: pd.DataFrame, emb: np.ndarray, y: np.ndarray, split: np.ndarray, pca_dim: int = 64,
             neg_per_pos: int = 10, train_cap: int = 1_000_000, test_n: int = 100_000, seed: int = 0):
    """Train raw / embeddings / combined models. Returns (results table, test scores, test row index)."""
    rng = np.random.default_rng(seed)
    tr, va, te = (np.flatnonzero(split == s) for s in ("train", "val", "test"))
    tr = tr[balanced_index(y[tr], neg_per_pos, train_cap, rng)]
    te = te[stratified_holdout(y[te], test_n, rng)]

    pca = PCA(n_components=min(pca_dim, emb.shape[1]), random_state=seed).fit(emb[split == "train"][:500_000])
    e64 = pca.transform(emb).astype(np.float32)
    e_cols = [f"fm_{i}" for i in range(e64.shape[1])]
    E = pd.DataFrame(e64, columns=e_cols, index=raw.index)
    feats = {"Raw (baseline)": raw, "Embeddings only": E, "Combined": pd.concat([raw, E], axis=1)}

    rows, scores = [], {}
    for name, X in feats.items():
        m = fit_xgb(X.iloc[tr], y[tr], X.iloc[va], y[va], seed)
        p = m.predict_proba(X.iloc[te])[:, 1]
        scores[name] = p
        rows.append(dict(model=name, feature_dim=X.shape[1],
                         test_roc_auc=roc_auc_score(y[te], p), test_ap=average_precision_score(y[te], p)))
    res = pd.DataFrame(rows)
    base = res.iloc[0]
    res["roc_auc_lift_%"] = 100 * (res["test_roc_auc"] / base["test_roc_auc"] - 1)
    res["ap_lift_%"] = 100 * (res["test_ap"] / base["test_ap"] - 1)
    print(f"[downstream] PCA {e64.shape[1]}d keeps {pca.explained_variance_ratio_.sum():.0%} variance | "
          f"train {len(tr):,} rows ({int(y[tr].sum())} fraud) | test {len(te):,} rows ({int(y[te].sum())} fraud)")
    return res, scores, te
