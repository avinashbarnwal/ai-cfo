"""Thin Claude wrapper shared by every POC agent.

The agents are deterministic first: rules / stats produce the decision, Claude
only writes the human-facing narrative (email draft, memo, explanation).
If no API key is configured the agent still runs and returns a template text.

Key lookup order (matches the rest of the ai-cfo repo):
  1. keyring  ->  keyring.set_password("anthropic_key", "key", "<sk-ant-...>")
  2. env var  ->  ANTHROPIC_API_KEY
"""
from __future__ import annotations

import json
import os

MODEL = os.environ.get("AGENT_MODEL", "claude-haiku-5-5")
API_URL = "https://api.anthropic.com/v1/messages"


def _api_key() -> str | None:
    try:
        import keyring
        from keyrings.alt.file import PlaintextKeyring

        keyring.set_keyring(PlaintextKeyring())
        key = keyring.get_password("anthropic_key", "key")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


def narrate(system: str, payload: dict | list | str, fallback: str, max_tokens: int = 600) -> str:
    """Ask Claude to turn structured agent output into prose; fall back offline."""
    key = _api_key()
    if not key or os.environ.get("AGENT_OFFLINE") == "1":
        return fallback
    try:
        import httpx

        body = payload if isinstance(payload, str) else json.dumps(payload, default=str, indent=2)
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if os.environ.get("ANTHROPIC_WORKSPACE_ID"):
            headers["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
        r = httpx.post(
            API_URL,
            headers=headers,
            json={
                "model": MODEL,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": body}],
            },
            timeout=60,
        )
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"]).strip()
    except Exception as exc:  # never let the LLM break the POC
        return f"{fallback}\n\n[LLM unavailable: {exc.__class__.__name__}]"
