# Keeper — Autonomous AR Agent (prototype)

A working prototype of an autonomous accounts-receivable agent, in the spirit of
Transformance's Vero: it reads invoice/customer data, decides what to do about
each account, auto-executes low-stakes actions, and routes anything higher-stakes
to a human approval queue — with a full audit trail.

- **backend/** — Python (FastAPI) server. Holds the Anthropic API key and does
  all the reasoning. Nothing sensitive ever reaches the browser.
- **frontend/** — static HTML/CSS/JavaScript that talks to the backend over a
  small REST API. No build step.

## Run it

### 1. Backend (Python)

Requires Python 3.10+.

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and paste in your ANTHROPIC_API_KEY
python3 main.py
```

This starts the API on `http://localhost:3001`. Interactive API docs are
available at `http://localhost:3001/docs` (FastAPI's built-in Swagger UI).

### 2. Frontend (JavaScript)

Serve the `frontend/` folder with any static server, for example:

```bash
cd frontend
npx serve . -l 5173
# or: python3 -m http.server 5173
```

Then open `http://localhost:5173` in your browser. If your backend runs on a
different host or port, update the `API` constant at the top of `frontend/app.js`.

## API endpoints

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/api/customers` | Raw customer/invoice dataset |
| POST | `/api/briefing` | Calls Claude, generates the prioritized worklist, stores it server-side |
| GET | `/api/worklist` | Current briefing + worklist |
| GET | `/api/audit` | Current audit trail |
| POST | `/api/actions/{key}/approve` | Approve an L3 item, logs it |
| POST | `/api/actions/{key}/reject` | Reject an L3 item, logs it |
| POST | `/api/ask` | Ask a free-text question grounded in the data + audit trail |

## Notes on this being a prototype

- Worklist and audit trail are held **in memory** on the backend — they reset if
  the server restarts. Swap in a real database (Postgres, SQLite, etc.) for anything
  persistent.
- The dataset in `backend/data.py` is fictional. Replace it with your real
  invoice/customer feed (or wire up a proper ERP connector) when you're ready
  to move past the prototype stage.
- There's no auth on the API routes, and CORS is wide open (`allow_origins=["*"]`)
  for local development. Lock both down before exposing this beyond localhost.
