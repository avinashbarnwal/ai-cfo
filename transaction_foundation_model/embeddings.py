"""Step 4 - turn the pretrained backbone into a feature extractor.

Last-token pooling: with causal attention only the final position has seen the
whole history, so the hidden state at the last token of transaction *t* is an
embedding of the user's history up to and including *t* (never the future, and
never the fraud label - labels are not tokenized).

One forward pass over a user window therefore yields an embedding for every
transaction in it. Long histories are covered with overlapping windows so each
transaction keeps at least half a window of prior context.
"""
from __future__ import annotations

import numpy as np
import torch

from .model import device_auto
from .tokenizer import BOS_ID, PAD_ID, user_bounds


def _windows(user_ids: np.ndarray, win_txn: int) -> list[tuple[int, int, int]]:
    """(start, end, keep_from) row ranges; rows [keep_from, end) take their embedding from this window."""
    out, half = [], max(1, win_txn // 2)
    for s, e in user_bounds(user_ids):
        start = s
        out.append((s, min(e, s + win_txn), s))
        while start + win_txn < e:
            start += half
            out.append((start, min(e, start + win_txn), start + win_txn - half))
    return out


@torch.no_grad()
def extract_embeddings_batched(model, tokens: np.ndarray, user_ids: np.ndarray, seq_len: int = 1024,
                               batch_size: int = 64, show_progress: bool = True) -> np.ndarray:
    """(n_txn, hidden_size) float32 array aligned with ``tokens`` rows (sorted by user, ts)."""
    dev = device_auto()
    model.to(dev).eval()
    tpt = tokens.shape[1]
    win_txn = max(2, (seq_len - 1) // tpt)
    wins = _windows(user_ids, win_txn)
    out = np.zeros((len(tokens), model.config.hidden_size), dtype=np.float32)
    amp = dict(device_type=dev.type, dtype=torch.bfloat16, enabled=dev.type == "cuda")

    for b in range(0, len(wins), batch_size):
        chunk = wins[b:b + batch_size]
        L = 1 + max(e - s for s, e, _ in chunk) * tpt
        ids = np.full((len(chunk), L), PAD_ID, dtype=np.int64)
        for i, (s, e, _) in enumerate(chunk):
            ids[i, 0] = BOS_ID
            ids[i, 1:1 + (e - s) * tpt] = tokens[s:e].reshape(-1)
        t = torch.from_numpy(ids).to(dev)
        with torch.autocast(**amp):
            h = model(input_ids=t, attention_mask=(t != PAD_ID).long(), output_hidden_states=True).hidden_states[-1]
        h = h.float().cpu().numpy()
        for i, (s, e, keep) in enumerate(chunk):
            j = np.arange(keep - s, e - s)
            out[keep:e] = h[i, 1 + j * tpt + (tpt - 1)]  # last token of each transaction
        if show_progress and (b // batch_size) % 20 == 0:
            print(f"[embed] {min(b + batch_size, len(wins))}/{len(wins)} windows")
    return out
