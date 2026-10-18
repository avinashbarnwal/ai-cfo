import json
import os
import re
from datetime import datetime
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from data import COMPANY, CUSTOMERS
import keyring
import keyring
from keyrings.alt.file import PlaintextKeyring
keyring.set_keyring(PlaintextKeyring())

# load_dotenv()

ANTHROPIC_API_KEY = keyring.get_password("anthropic_key", "key")
# Needed only when the API key isn't scoped to a workspace (e.g. sk-ant-usr- keys).
ANTHROPIC_WORKSPACE_ID = os.environ.get("ANTHROPIC_WORKSPACE_ID")

MODEL = "claude-haiku-5-5"
PORT = int(os.environ.get("PORT", 3001))

if not ANTHROPIC_API_KEY:
    print("WARNING: ANTHROPIC_API_KEY is not set. Store it in the keyring (see README → Quickstart).")

app = FastAPI(title="Keeper backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory state — resets when the server restarts. Swap for a real
# database if you want the worklist/audit trail to persist.
worklist: list[dict] = []
audit_trail: list[dict] = []
briefing_summary: Optional[str] = None
cash_note: Optional[str] = None

BRIEFING_SYSTEM = f"""You are Keeper, an autonomous accounts receivable agent working for {COMPANY}. You read open invoices and everything known about each customer, then decide the single best next action for each one.

Tier definitions:
L1 = read-only observation. No outreach, just a flag worth knowing about.
L2 = low-stakes autonomous action, no approval needed (e.g. a routine reminder email).
L3 = an action that needs a human's sign-off before it happens (e.g. an escalation call, a settlement offer, routing a dispute).
L4 = would change financial records or post to the ERP. Always human-in-the-loop; you only flag it, you never execute it.

For every invoice given to you, decide the single best next action, its tier, and a confidence score from 0-100. Ground your reasoning in the specific facts you were given about that account (payment pattern, days overdue, disputes, broken promises) — do not write generic reasoning that could apply to any account. For L2 and L3 actions that involve outreach, draft the actual message (a short email, or call talking points) in that customer's specific context. Order the worklist by business risk (amount at risk combined with likelihood of further delay), highest risk first.

Return ONLY valid JSON, with no markdown fences and no commentary before or after, matching exactly this shape:
{{"briefing_summary": "2-3 sentence summary of the overall AR picture this morning", "cash_position_note": "1 sentence on what's collectible soon vs at risk", "worklist": [{{"id": "customer id you were given", "customer": "name", "invoice_ref": "id", "amount": 0, "days_overdue": 0, "tier": "L1", "action": "short label, under 6 words", "reasoning": "2-3 sentences, specific to this account", "confidence": 0, "draft_message": "the drafted message, or null if this action has no outreach"}}]}}"""


async def call_claude(system: str, user_text: str, max_tokens: int = 3000) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY or "",
                "anthropic-version": "2023-06-01",
                **({"anthropic-workspace-id": ANTHROPIC_WORKSPACE_ID} if ANTHROPIC_WORKSPACE_ID else {}),
            },
            json={
                "model": MODEL,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user_text}],
            },
        )
    if res.status_code != 200:
        raise RuntimeError(f"Anthropic API error {res.status_code}: {res.text}")
    data = res.json()
    text_block = next((b for b in data.get("content", []) if b.get("type") == "text"), None)
    if not text_block:
        raise RuntimeError("No text block in Claude's response")
    return text_block["text"]


def strip_fences(t: str) -> str:
    t = re.sub(r"^```json\s*", "", t.strip(), flags=re.IGNORECASE)
    t = re.sub(r"^```\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"```\s*$", "", t)
    return t.strip()


def now_label() -> str:
    return datetime.now().strftime("%I:%M %p").lstrip("0")


class AskRequest(BaseModel):
    question: str


# ---- Routes ----

@app.get("/api/customers")
def get_customers():
    return CUSTOMERS


@app.post("/api/briefing")
async def post_briefing():
    global worklist, audit_trail, briefing_summary, cash_note

    payload = json.dumps([
        {"id": c["id"], "customer": c["name"], "segment": c["segment"], "invoice": c["invoice"], "memory": c["memory"]}
        for c in CUSTOMERS
    ])

    try:
        raw = await call_claude(BRIEFING_SYSTEM, "Here is today's open AR data:\n" + payload, 3000)
        parsed = json.loads(strip_fences(raw))
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))

    briefing_summary = parsed.get("briefing_summary")
    cash_note = parsed.get("cash_position_note")

    new_worklist = []
    for item in parsed.get("worklist", []):
        tier = item.get("tier")
        if tier in ("L1", "L2"):
            status = "auto_executed"
        elif tier == "L3":
            status = "pending_approval"
        else:
            status = "flagged"
        item = {**item, "status": status, "key": f"{item.get('id')}|{item.get('invoice_ref')}", "ts": now_label()}
        new_worklist.append(item)
    worklist = new_worklist

    audit_trail = []
    for item in worklist:
        if item["status"] in ("auto_executed", "flagged"):
            audit_trail.insert(0, {
                "time": item["ts"], "customer": item["customer"], "action": item["action"], "tier": item["tier"],
                "reasoning": item["reasoning"], "confidence": item["confidence"],
                "status": "Executed automatically" if item["status"] == "auto_executed" else "Flagged — needs manual ERP action",
            })

    return {"briefingSummary": briefing_summary, "cashNote": cash_note, "worklist": worklist, "auditTrail": audit_trail}


@app.get("/api/worklist")
def get_worklist():
    return {"briefingSummary": briefing_summary, "cashNote": cash_note, "worklist": worklist}


@app.get("/api/audit")
def get_audit():
    return audit_trail


@app.post("/api/actions/{key}/approve")
def approve_action(key: str):
    item = next((i for i in worklist if i["key"] == key), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item["status"] = "approved"
    entry = {
        "time": now_label(), "customer": item["customer"], "action": item["action"], "tier": item["tier"],
        "reasoning": item["reasoning"], "confidence": item["confidence"], "status": "Approved & executed",
    }
    audit_trail.insert(0, entry)
    return {"item": item, "entry": entry}


@app.post("/api/actions/{key}/reject")
def reject_action(key: str):
    item = next((i for i in worklist if i["key"] == key), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item["status"] = "rejected"
    entry = {
        "time": now_label(), "customer": item["customer"], "action": item["action"], "tier": item["tier"],
        "reasoning": item["reasoning"], "confidence": item["confidence"], "status": "Rejected",
    }
    audit_trail.insert(0, entry)
    return {"item": item, "entry": entry}


@app.post("/api/ask")
async def post_ask(body: AskRequest):
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    data_summary = "\n".join(
        f"{c['name']} ({c['segment']}): invoice {c['invoice']['id']} for ${c['invoice']['amount']}, "
        f"{c['invoice']['daysOverdue']} days overdue. Pattern: {c['memory']['paymentPattern']}"
        for c in CUSTOMERS
    )
    audit_summary = "\n".join(
        f"{a['time']} — {a['customer']}: {a['status']} ({a['action']})" for a in audit_trail
    ) or "No actions taken yet."

    system = (
        f"You are Keeper, an autonomous AR agent for {COMPANY}. Answer the finance user's question directly and "
        "concisely in plain text, no markdown headers, no JSON. Cite specific customers, amounts, or days overdue "
        "where relevant. If something isn't in the data given to you, say so plainly rather than guessing."
    )
    user = f"Account data:\n{data_summary}\n\nActions taken so far today:\n{audit_summary}\n\nQuestion: {question}"

    try:
        answer = await call_claude(system, user, 500)
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))

    return {"answer": answer.strip()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
