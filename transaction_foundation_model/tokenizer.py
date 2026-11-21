"""Step 2 - domain tokenizer: one transaction -> a fixed handful of semantic tokens.

A BPE tokenizer spends ~39 tokens per transaction on commas and dollar signs.
This pipeline emits one token per field (amount bin, merchant bucket, MCC,
hour, weekday, month, chip type, ZIP3, state, error flag, time-since-previous,
card), giving ~13 tokens per transaction from a vocabulary of a few thousand.

Each field is a small ``BaseTokenizer`` subclass, so a new schema field (device
id, beneficiary country, ...) is a short addition to ``default_steps()``.
Every transaction starts with a [TXN] marker, so its last token sits at a fixed
offset - that is what the embedding step pools on.
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

SPECIALS = ["[PAD]", "[BOS]", "[EOS]", "[UNK]", "[TXN]"]
PAD_ID, BOS_ID, EOS_ID, UNK_ID, TXN_ID = range(len(SPECIALS))


class BaseTokenizer:
    """One field -> one token. Local id 0 is the field's own UNK."""

    name = "base"

    def fit(self, d: pd.DataFrame) -> "BaseTokenizer":
        return self

    def transform(self, d: pd.DataFrame) -> np.ndarray:  # local ids, 0..size-1
        raise NotImplementedError

    @property
    def tokens(self) -> list[str]:
        raise NotImplementedError

    @property
    def size(self) -> int:
        return len(self.tokens)


class CategoricalStep(BaseTokenizer):
    """Keep the ``max_categories`` most frequent training values; rarer/unseen -> UNK."""

    def __init__(self, column: str, name: str | None = None, max_categories: int = 1000):
        self.column, self.name, self.max_categories = column, name or column, max_categories
        self.categories: list = []

    def fit(self, d):
        self.categories = d[self.column].value_counts().index[: self.max_categories].tolist()
        return self

    def transform(self, d):
        codes = pd.Categorical(d[self.column], categories=self.categories).codes
        return (np.asarray(codes, dtype=np.int64) + 1)

    @property
    def tokens(self):
        return [f"{self.name}_UNK"] + [f"{self.name}_{c}" for c in self.categories]


class HashStep(BaseTokenizer):
    """High-cardinality ids (merchant) hashed into fixed buckets - no vocab growth."""

    def __init__(self, column: str, buckets: int = 2048, name: str | None = None):
        self.column, self.buckets, self.name = column, buckets, name or column

    def transform(self, d):
        h = pd.util.hash_pandas_object(d[self.column].astype(str), index=False).to_numpy()
        return (h % np.uint64(self.buckets)).astype(np.int64) + 1

    @property
    def tokens(self):
        return [f"{self.name}_UNK"] + [f"{self.name}_h{i}" for i in range(self.buckets)]


class LogBinStep(BaseTokenizer):
    """Signed log-scale bins; handles refunds (negative amounts) and missing values (<0 sentinel)."""

    def __init__(self, column: str, name: str | None = None, width: float = 0.25, max_log: float = 12.0,
                 signed: bool = True):
        self.column, self.name, self.width, self.max_log, self.signed = column, name or column, width, max_log, signed
        self.n_half = int(np.ceil(max_log / width)) + 1

    def transform(self, d):
        x = d[self.column].to_numpy(dtype=np.float64)
        mag = np.minimum(np.log1p(np.abs(x)), self.max_log)
        b = np.floor(mag / self.width).astype(np.int64)
        if self.signed:
            b = np.where(x < 0, self.n_half + b, b)
        else:
            b = np.where(x < 0, -1, b)  # sentinel (e.g. first txn has no previous) -> UNK
        return b + 1

    @property
    def tokens(self):
        n = self.n_half * (2 if self.signed else 1)
        return [f"{self.name}_UNK"] + [f"{self.name}_b{i}" for i in range(n)]


def default_steps() -> list[BaseTokenizer]:
    return [
        LogBinStep("amount", "AMT"),
        HashStep("merchant", 2048, "MERCH"),
        CategoricalStep("mcc", "MCC", 500),
        CategoricalStep("hour", "HOUR"),
        CategoricalStep("dow", "DOW"),
        CategoricalStep("month", "MON"),
        CategoricalStep("use_chip", "CHIP"),
        CategoricalStep("zip3", "ZIP3", 1000),
        CategoricalStep("merchant_state", "STATE", 300),
        CategoricalStep("has_error", "ERR"),
        LogBinStep("secs_since_prev", "DT", width=0.5, max_log=18.0, signed=False),
        CategoricalStep("card", "CARD", 16),
    ]


@dataclass
class FinancialTokenizerPipeline:
    steps: list[BaseTokenizer] = field(default_factory=default_steps)
    offsets: list[int] = field(default_factory=list)

    def fit(self, d: pd.DataFrame) -> "FinancialTokenizerPipeline":
        off = len(SPECIALS)
        self.offsets = []
        for s in self.steps:
            s.fit(d)
            self.offsets.append(off)
            off += s.size
        return self

    @property
    def vocab_size(self) -> int:
        return self.offsets[-1] + self.steps[-1].size

    @property
    def tokens_per_txn(self) -> int:
        return 1 + len(self.steps)

    @property
    def vocab(self) -> list[str]:
        return SPECIALS + [t for s in self.steps for t in s.tokens]

    def encode(self, d: pd.DataFrame) -> np.ndarray:
        """(n_txn, tokens_per_txn) int32 matrix of global token ids."""
        cols = [np.full(len(d), TXN_ID, dtype=np.int64)]
        for s, off in zip(self.steps, self.offsets):
            local = np.clip(s.transform(d), 0, s.size - 1)
            cols.append(off + local)
        return np.stack(cols, axis=1).astype(np.int32)

    def decode_txn(self, row: np.ndarray) -> list[str]:
        v = self.vocab
        return [v[i] for i in row]

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: str) -> "FinancialTokenizerPipeline":
        with open(path, "rb") as f:
            return pickle.load(f)


def user_bounds(user_ids: np.ndarray) -> np.ndarray:
    """Start/end row of each user's contiguous block (rows must be sorted by user, ts)."""
    change = np.flatnonzero(np.diff(user_ids)) + 1
    starts = np.concatenate([[0], change])
    ends = np.concatenate([change, [len(user_ids)]])
    return np.stack([starts, ends], axis=1)


def bpe_token_count(d: pd.DataFrame, n: int = 1000) -> float | None:
    """Tokens per transaction under GPT-2 BPE, for the efficiency comparison (needs HF hub access)."""
    try:
        from transformers import AutoTokenizer

        tok = AutoTokenizer.from_pretrained("gpt2")
    except Exception:
        return None
    cols = ["user", "card", "ts", "amount", "use_chip", "merchant", "merchant_city", "merchant_state", "zip", "mcc", "errors"]
    lines = d[cols].head(n).astype(str).agg(",".join, axis=1)
    return float(np.mean([len(tok(x)["input_ids"]) for x in lines]))
