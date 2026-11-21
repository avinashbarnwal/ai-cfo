"""Step 3 - pretrain a decoder-only transaction foundation model (next-token prediction).

Architecture matches the NVIDIA example (configs/pretrain_financial_decoder.yaml):
a compact Llama decoder, ~29M params - hidden 512, 8 layers, GQA with 8 query /
2 KV heads, RoPE context 8,192, SwiGLU + RMSNorm. Built with Hugging Face
``LlamaForCausalLM`` and trained with a plain PyTorch loop, so the checkpoint is
standard safetensors and loads with ``AutoModelForCausalLM.from_pretrained``.

Multi-GPU: ``torchrun --nproc-per-node 8 -m transaction_foundation_model.pipeline ...``
(DDP is switched on automatically when WORLD_SIZE > 1).
"""
from __future__ import annotations

import math
import os
import time

import numpy as np
import torch
from transformers import LlamaConfig, LlamaForCausalLM

from .tokenizer import BOS_ID, PAD_ID, EOS_ID, user_bounds

PRESETS = {
    # the configuration from the NVIDIA blog (~29M params with the TabFormer vocab)
    "paper": dict(hidden_size=512, intermediate_size=1536, num_hidden_layers=8,
                  num_attention_heads=8, num_key_value_heads=2, max_position_embeddings=8192),
    # laptop / CI smoke-test size
    "small": dict(hidden_size=128, intermediate_size=384, num_hidden_layers=2,
                  num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=2048),
}


def build_model(vocab_size: int, preset: str = "paper", **overrides) -> LlamaForCausalLM:
    cfg = LlamaConfig(vocab_size=vocab_size, pad_token_id=PAD_ID, bos_token_id=BOS_ID, eos_token_id=EOS_ID,
                      hidden_act="silu", rms_norm_eps=1e-5, rope_theta=10000.0,
                      tie_word_embeddings=False, **{**PRESETS[preset], **overrides})
    return LlamaForCausalLM(cfg)


def device_auto() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda", int(os.environ.get("LOCAL_RANK", 0)))
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


class WindowSampler:
    """Random transaction-aligned windows from users' token histories: [BOS] txn txn txn ..."""

    def __init__(self, tokens: np.ndarray, user_ids: np.ndarray, seq_len: int, seed: int = 0):
        self.tokens, self.tpt = tokens, tokens.shape[1]
        self.win_txn = max(1, (seq_len - 1) // self.tpt)
        b = user_bounds(user_ids)
        self.bounds = b[(b[:, 1] - b[:, 0]) >= 2]
        lens = (self.bounds[:, 1] - self.bounds[:, 0]).astype(float)
        self.p = lens / lens.sum()
        self.seq_len = 1 + self.win_txn * self.tpt
        self.rng = np.random.default_rng(seed)

    def batch(self, batch_size: int) -> torch.Tensor:
        ids = np.full((batch_size, self.seq_len), PAD_ID, dtype=np.int64)
        users = self.rng.choice(len(self.bounds), size=batch_size, p=self.p)
        for i, u in enumerate(users):
            s, e = self.bounds[u]
            n = e - s
            start = s + (self.rng.integers(0, n - self.win_txn + 1) if n > self.win_txn else 0)
            chunk = self.tokens[start:min(e, start + self.win_txn)].reshape(-1)
            ids[i, 0] = BOS_ID
            ids[i, 1:1 + len(chunk)] = chunk
        return torch.from_numpy(ids)


def pretrain(model: LlamaForCausalLM, tokens: np.ndarray, user_ids: np.ndarray, out_dir: str,
             max_steps: int = 3000, batch_size: int = 32, seq_len: int = 1024, lr: float = 3e-4,
             warmup: int = 100, grad_accum: int = 1, log_every: int = 10, seed: int = 0) -> list[float]:
    """Causal-LM pretraining on unlabeled histories. Returns the loss curve."""
    ddp = int(os.environ.get("WORLD_SIZE", 1)) > 1
    if ddp:
        torch.distributed.init_process_group("nccl")
    rank = int(os.environ.get("RANK", 0))
    dev = device_auto()
    torch.manual_seed(seed)
    model.to(dev).train()
    core = model
    if ddp:
        model = torch.nn.parallel.DistributedDataParallel(model, device_ids=[dev.index])

    sampler = WindowSampler(tokens, user_ids, seq_len, seed=seed + rank)
    opt = torch.optim.AdamW(core.parameters(), lr=lr, betas=(0.9, 0.95), weight_decay=0.1, fused=dev.type == "cuda")
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / warmup) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / max(1, max_steps)))))
    amp = dict(device_type=dev.type, dtype=torch.bfloat16, enabled=dev.type == "cuda")

    if rank == 0:
        n_params = sum(p.numel() for p in core.parameters())
        print(f"[pretrain] {n_params / 1e6:.1f}M params | vocab {core.config.vocab_size} | "
              f"window {sampler.seq_len} tokens ({sampler.win_txn} txns) | device {dev} | "
              f"random-guess loss ln(V)={math.log(core.config.vocab_size):.2f}")
    losses, t0 = [], time.time()
    for step in range(max_steps):
        opt.zero_grad(set_to_none=True)
        tot = 0.0
        for _ in range(grad_accum):
            ids = sampler.batch(batch_size).to(dev)
            labels = ids.masked_fill(ids == PAD_ID, -100)
            with torch.autocast(**amp):
                loss = model(input_ids=ids, attention_mask=(ids != PAD_ID).long(), labels=labels).loss / grad_accum
            loss.backward()
            tot += loss.item()
        torch.nn.utils.clip_grad_norm_(core.parameters(), 1.0)
        opt.step()
        sched.step()
        losses.append(tot)
        if rank == 0 and (step % log_every == 0 or step == max_steps - 1):
            print(f"[pretrain] step {step:5d}/{max_steps} loss {tot:.4f} lr {sched.get_last_lr()[0]:.2e} "
                  f"({time.time() - t0:.0f}s)")

    if rank == 0:
        os.makedirs(out_dir, exist_ok=True)
        core.save_pretrained(out_dir, safe_serialization=True)
    if ddp:
        torch.distributed.destroy_process_group()
    core.eval()
    return losses
