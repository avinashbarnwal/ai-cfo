# HeroCycle MFR Agent

An AI-agent Monthly Financial Review: the CFO's month-end Excel workbooks in,
a guided evidence-first review out, ending in a management-ready deck narrative.
Built as three separate codebases integrated over a REST API.

```
┌─────────────────────┐      ┌──────────────────────────┐      ┌───────────────────┐
│  data/              │      │  backend/                │      │  frontend/        │
│  Excel workbooks    │─────▶│  MFRAgent (Claude API)   │◀────▶│  React UI (Vite)  │
│  + loader.py        │ dict │  + FastAPI endpoints     │ REST │  cards · charts · │
│  parse & validate   │      │  state machine S1→S5     │ JSON │  questions · deck │
└─────────────────────┘      └──────────────────────────┘      └───────────────────┘
```

## 1. Data codebase — `data/`

Input is the two normal month-end close files (no LLM-specific tabs):

- `HeroCycle_Financials_Jun2026.xlsx` — P&L Summary, Monthly Trend, EBITDA Bridge, Cash & WC
- `HeroCycle_Drivers_Jun2026.xlsx` — Revenue by Channel, Revenue by Segment, Operating KPIs

`loader.py` is the only module that knows workbook structure. It finds sheets by
fuzzy name match and tables by header labels, and returns one canonical dataset
dict plus `validate_dataset()` (S1 checkpoint) and `chart_payload()` (render-ready
chart data for the UI). To run a new month, drop in the new workbooks and point
the loader at them — the agent and UI don't change.

`generate_workbooks.py` regenerates the demo files (formulas recalculated,
zero errors).

## 2. AI agent codebase — `backend/`

- `agent.py` — `MFRAgent`: a stateless agent over the Anthropic Messages API
  (`claude-sonnet-4-6` by default). Implements the review state machine:
  plan cycles → per-cycle evidence cards + a data-grounded judgment question
  (3–4 interpretations, never invented causes) → synthesis of the CFO's answers
  into the final deck narrative. Strict-JSON prompting with one auto-retry on
  malformed output.
- `main.py` — FastAPI integration layer: loads the dataset once, exposes
  `GET /api/validate`, `GET /api/cycles`, `POST /api/cycle`, `POST /api/synthesize`,
  and attaches chart payloads from the data layer to each cycle response.

## 3. UI codebase — `frontend/`

React + Vite + recharts. The UI is deliberately dumb about finance data: it
renders whatever the API sends — metric cards, a chart payload by `kind`
(`trend` / `grouped_bar` / `bridge`), the judgment question with options and a
free-text context field, and finally the deck (signal, key messages, sections,
management agenda, appendix). `vite.config.js` proxies `/api/*` to the backend,
so there are no CORS issues in dev.

## Run it

```bash
# 0) prerequisites: Python 3.11+, Node 18+, an Anthropic API key
# export ANTHROPIC_API_KEY=...

# 1) backend (from the project root)
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000

# 2) frontend (second terminal)
cd frontend
npm install
npm run dev          # opens http://localhost:5173
```

Optional: `export MFR_MODEL=claude-opus-4-8` to use a different model.

## Extending

- **New month**: replace the two xlsx files (or pass paths to `load_dataset`).
- **Real company files**: adjust only `data/loader.py` sheet/header matching.
- **Upload flow**: add a `POST /api/upload` that saves workbooks and rebuilds
  the dataset; nothing in the agent or UI changes.
- **Deck export**: the deck JSON from `/api/synthesize` maps 1:1 onto a
  standalone HTML template if you want a downloadable file.
