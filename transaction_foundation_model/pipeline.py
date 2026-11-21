"""End-to-end: transactions -> domain tokens -> pretrained decoder -> embeddings -> fraud lift.

Re-implements NVIDIA's "Build Your Own Transaction Foundation Model" developer
example with portable libraries (pandas / PyTorch / Hugging Face / XGBoost).
Runs on CPU, a single GPU, or many GPUs.

    # zero-setup smoke test on synthetic card histories (CPU, a few minutes)
    python -m transaction_foundation_model.pipeline --synthetic --preset small --max-steps 300

    # the blog setup on IBM TabFormer (GPU; download card_transaction.v1.csv first)
    python -m transaction_foundation_model.pipeline --data data/card_transaction.v1.csv \
        --preset paper --max-steps 3000 --seq-len 4096 --batch-size 16

    # reuse a trained backbone, only redo embeddings + XGBoost
    python -m transaction_foundation_model.pipeline --data ... --skip-pretrain

    # 8 GPUs
    torchrun --nproc-per-node 8 -m transaction_foundation_model.pipeline --data ... --pretrain-only

Set TFM_CUDF=1 to run the pandas steps on the GPU through cudf.pandas (RAPIDS).
"""
from __future__ import annotations

import os

if os.environ.get("TFM_CUDF") == "1":  # must run before pandas is imported anywhere
    import cudf.pandas

    cudf.pandas.install()

import argparse
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import add_derived, load_tabformer, raw_features, synthetic_transactions, temporal_split
from .downstream import evaluate
from .embeddings import extract_embeddings_batched
from .model import build_model, pretrain
from .tokenizer import FinancialTokenizerPipeline, bpe_token_count


@dataclass
class RunConfig:
    data: str | None = None
    synthetic: bool = False
    nrows: int | None = None
    n_users: int = 400
    out: str = "artifacts/tfm"
    preset: str = "paper"
    max_steps: int = 3000
    batch_size: int = 32
    seq_len: int = 1024
    lr: float = 3e-4
    embed_batch_size: int = 64
    pca_dim: int = 64
    neg_per_pos: int = 10
    skip_pretrain: bool = False
    pretrain_only: bool = False
    bpe_compare: bool = False
    seed: int = 7


def load(cfg: RunConfig) -> pd.DataFrame:
    if cfg.synthetic or not cfg.data:
        df = synthetic_transactions(n_users=cfg.n_users, seed=cfg.seed)
    else:
        df = load_tabformer(cfg.data, nrows=cfg.nrows)
    d = add_derived(df)
    d["split"] = temporal_split(d)
    return d


def run(cfg: RunConfig) -> dict:
    os.makedirs(cfg.out, exist_ok=True)
    model_dir = os.path.join(cfg.out, "decoder-foundation-model")
    rank0 = int(os.environ.get("RANK", 0)) == 0

    # 1. data + temporal split
    d = load(cfg)
    split = d["split"].to_numpy()
    y = d["is_fraud"].to_numpy()
    if rank0:
        print(f"[data] {len(d):,} txns | {d['user'].nunique():,} users | fraud rate {y.mean():.3%} | "
              + " ".join(f"{s}={int((split == s).sum()):,}" for s in ("train", "val", "test")))

    # 2. domain tokenizer (vocab fit on train only)
    tok_path = os.path.join(cfg.out, "tokenizer.pkl")
    if cfg.skip_pretrain and os.path.exists(tok_path):
        tok = FinancialTokenizerPipeline.load(tok_path)
    else:
        tok = FinancialTokenizerPipeline().fit(d[split == "train"])
        if rank0:
            tok.save(tok_path)
    tokens = tok.encode(d)
    users = d["user"].to_numpy()
    if rank0:
        msg = f"[tokenize] {tok.tokens_per_txn} tokens/txn | vocab {tok.vocab_size:,}"
        if cfg.bpe_compare and (bpe := bpe_token_count(d)):
            msg += f" | GPT-2 BPE would use {bpe:.1f} tokens/txn (vocab 50,257)"
        print(msg)
        print("[tokenize] example:", " ".join(tok.decode_txn(tokens[0])))

    # 3. pretrain on train-period histories only (no labels involved)
    if cfg.skip_pretrain:
        from transformers import AutoModelForCausalLM

        model = AutoModelForCausalLM.from_pretrained(model_dir)
    else:
        tr = split == "train"
        model = build_model(tok.vocab_size, cfg.preset)
        losses = pretrain(model, tokens[tr], users[tr], model_dir, max_steps=cfg.max_steps,
                          batch_size=cfg.batch_size, seq_len=cfg.seq_len, lr=cfg.lr, seed=cfg.seed)
        if rank0:
            print(f"[pretrain] loss {losses[0]:.3f} -> {np.mean(losses[-10:]):.3f}")
    if cfg.pretrain_only or not rank0:
        return {}

    # 4. embeddings for every transaction (history up to and including it)
    emb = extract_embeddings_batched(model, tokens, users, seq_len=cfg.seq_len, batch_size=cfg.embed_batch_size)
    for s in ("train", "val", "test"):
        np.save(os.path.join(cfg.out, f"embeddings_{s}.npy"), emb[split == s])
    meta = dict(n_rows=len(d), dim=int(emb.shape[1]), order="rows sorted by (user, ts)",
                splits={s: int((split == s).sum()) for s in ("train", "val", "test")})
    json.dump(meta, open(os.path.join(cfg.out, "metadata.json"), "w"), indent=2)

    # 5. downstream fraud model lift
    raw = raw_features(d)
    res, scores, te = evaluate(raw, emb, y, split, pca_dim=cfg.pca_dim, neg_per_pos=cfg.neg_per_pos, seed=cfg.seed)
    res.to_csv(os.path.join(cfg.out, "results.csv"), index=False)
    with pd.option_context("display.width", 160, "display.float_format", "{:.4f}".format):
        print("\n" + res.to_string(index=False))

    flagged = d.iloc[te][["user", "ts", "amount", "merchant", "merchant_state", "use_chip", "is_fraud"]].copy()
    flagged["score_raw"] = scores["Raw (baseline)"]
    flagged["score_combined"] = scores["Combined"]
    flagged = flagged.sort_values("score_combined", ascending=False)
    flagged.head(200).to_csv(os.path.join(cfg.out, "top_flagged_test.csv"), index=False)
    return dict(results=res, flagged=flagged, embeddings=emb, frame=d, tokenizer=tok, model=model)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", help="path to TabFormer card_transaction.v1.csv")
    p.add_argument("--synthetic", action="store_true", help="use generated card histories")
    p.add_argument("--nrows", type=int)
    p.add_argument("--n-users", type=int, default=400)
    p.add_argument("--out", default="artifacts/tfm")
    p.add_argument("--preset", choices=["paper", "small"], default="paper")
    p.add_argument("--max-steps", type=int, default=3000)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--seq-len", type=int, default=1024)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--embed-batch-size", type=int, default=64)
    p.add_argument("--pca-dim", type=int, default=64)
    p.add_argument("--neg-per-pos", type=int, default=10)
    p.add_argument("--skip-pretrain", action="store_true")
    p.add_argument("--pretrain-only", action="store_true")
    p.add_argument("--bpe-compare", action="store_true", help="also count GPT-2 BPE tokens per txn")
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args()
    run(RunConfig(**{k: v for k, v in vars(a).items()}))


if __name__ == "__main__":
    main()
