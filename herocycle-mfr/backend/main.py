"""HeroCycle MFR API - integration layer.

Wires the three codebases together:

  data/     -> loads & validates the two month-end Excel workbooks
  backend/  -> MFRAgent (Claude API) turns data + CFO answers into cycles & deck
  frontend/ -> React UI consumes these endpoints

Run from the project root:
    uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Make the sibling `data` codebase importable when run from project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.loader import chart_payload, load_dataset, validate_dataset  # noqa: E402
from backend.agent import MFRAgent  # noqa: E402

app = FastAPI(title="HeroCycle MFR Agent API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Loaded once at startup; swap workbook files and restart for a new month.
DATASET = load_dataset()
AGENT = MFRAgent(DATASET)


class Answer(BaseModel):
    cycle: str
    question: str
    choice: str
    context: str = ""


class CycleRequest(BaseModel):
    cycle_index: int = Field(ge=0)
    answers: list[Answer] = []


class SynthesisRequest(BaseModel):
    answers: list[Answer]


@app.get("/api/validate")
def validate() -> dict[str, Any]:
    """S1: input-validation checkpoint from the Excel workbooks."""
    return validate_dataset(DATASET)


@app.get("/api/cycles")
def cycles() -> list[dict[str, str]]:
    """S2: the review-cycle plan."""
    return AGENT.plan()


@app.post("/api/cycle")
def run_cycle(req: CycleRequest) -> dict[str, Any]:
    """S3(i): evidence cards + judgment question for one cycle,
    with render-ready chart data attached from the data layer."""
    plan = AGENT.plan()
    if req.cycle_index >= len(plan):
        raise HTTPException(400, "cycle_index out of range")
    try:
        result = AGENT.run_cycle(req.cycle_index, [a.model_dump() for a in req.answers])
    except Exception as e:  # surface agent errors cleanly to the UI
        raise HTTPException(502, f"Agent call failed: {e}") from e
    result["chart"] = chart_payload(result["chart_key"], DATASET)
    return result


@app.post("/api/synthesize")
def synthesize(req: SynthesisRequest) -> dict[str, Any]:
    """S4/S5: final MFR deck narrative from the CFO's judgments."""
    try:
        deck = AGENT.synthesize([a.model_dump() for a in req.answers])
    except Exception as e:
        raise HTTPException(502, f"Agent call failed: {e}") from e
    deck["period"] = DATASET["period"]
    deck["company"] = DATASET["company"]
    deck["source_files"] = DATASET["source_files"]
    return deck
