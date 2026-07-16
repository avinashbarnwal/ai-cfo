"""HeroCycle MFR API - integration layer.

Wires the three codebases together:

  data/     -> parses & validates the two month-end Excel workbooks
  backend/  -> MFRAgent (Claude API) turns data + CFO answers into cycles & deck
  frontend/ -> React UI consumes these endpoints

Run from the project root:
    uvicorn backend.main:app --reload --port 8000

Workbooks can be uploaded from the UI (POST /api/upload); the bundled
demo files are loaded at startup as a fallback.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Make the sibling `data` codebase importable when run from project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.loader import chart_payload, load_dataset, validate_dataset  # noqa: E402
from backend.agent import MFRAgent  # noqa: E402

app = FastAPI(title="HeroCycle MFR Agent API", version="1.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(tempfile.gettempdir()) / "mfr_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# Mutable app state: demo workbooks at startup, replaced by uploads.
STATE: dict[str, Any] = {"dataset": load_dataset(), "agent": None, "source": "bundled demo"}
STATE["agent"] = MFRAgent(STATE["dataset"])


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


def _save_upload(upload: UploadFile) -> Path:
    if not upload.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, f"{upload.filename}: only .xlsx/.xlsm files are supported")
    dest = UPLOAD_DIR / Path(upload.filename).name
    with open(dest, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return dest


@app.post("/api/upload")
def upload_workbooks(
    financials: UploadFile = File(...),
    drivers: UploadFile = File(...),
) -> dict[str, Any]:
    """Accept the two month-end workbooks, rebuild the dataset,
    and return the S1 validation result."""
    fin_path = _save_upload(financials)
    drv_path = _save_upload(drivers)
    try:
        dataset = load_dataset(fin_path, drv_path)
    except Exception as e:
        raise HTTPException(400, f"Could not parse workbooks: {e}") from e
    validation = validate_dataset(dataset)
    if not validation["can_proceed"]:
        # Report what's missing but don't replace a working dataset.
        return validation
    STATE["dataset"] = dataset
    STATE["agent"] = MFRAgent(dataset)
    STATE["source"] = "uploaded"
    return validation


@app.get("/api/validate")
def validate() -> dict[str, Any]:
    """S1: input-validation checkpoint for the current workbooks."""
    v = validate_dataset(STATE["dataset"])
    v["source"] = STATE["source"]
    return v


@app.get("/api/cycles")
def cycles() -> list[dict[str, str]]:
    """S2: the review-cycle plan."""
    return STATE["agent"].plan()


@app.post("/api/cycle")
def run_cycle(req: CycleRequest) -> dict[str, Any]:
    """S3(i): evidence cards + judgment question for one cycle,
    with render-ready chart data attached from the data layer."""
    agent: MFRAgent = STATE["agent"]
    if req.cycle_index >= len(agent.plan()):
        raise HTTPException(400, "cycle_index out of range")
    try:
        result = agent.run_cycle(req.cycle_index, [a.model_dump() for a in req.answers])
    except Exception as e:  # surface agent errors cleanly to the UI
        raise HTTPException(502, f"Agent call failed: {e}") from e
    result["chart"] = chart_payload(result["chart_key"], STATE["dataset"])
    return result


@app.post("/api/synthesize")
def synthesize(req: SynthesisRequest) -> dict[str, Any]:
    """S4/S5: final MFR deck narrative from the CFO's judgments."""
    try:
        deck = STATE["agent"].synthesize([a.model_dump() for a in req.answers])
    except Exception as e:
        raise HTTPException(502, f"Agent call failed: {e}") from e
    ds = STATE["dataset"]
    deck["period"] = ds["period"]
    deck["company"] = ds["company"]
    deck["source_files"] = ds["source_files"]
    return deck
