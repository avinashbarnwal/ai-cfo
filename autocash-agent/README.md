# Keeper: Autonomous AR Agent

Keeper is a prototype accounts-receivable agent built on the Claude API. It reads
open invoices and customer history, decides the next best action for each account,
executes low-stakes actions on its own, and routes higher-stakes actions to a human
approval queue. Every decision is recorded in an audit trail.

> [!NOTE]
> This is a prototype. State is held in memory, the dataset is fictional, and the
> API has no authentication. See [Limitations](#limitations) before running it
> anywhere other than your own machine.

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [API reference](#api-reference)
- [Project structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)

## How it works

1. The backend sends every open invoice in [`backend/data.py`](backend/data.py) to
   Claude, along with what's known about the customer (payment pattern, past
   disputes, broken promises, last contact).
2. Claude returns a briefing, a cash-position note, and a worklist ordered by business
   risk. Each item has an action, reasoning, a confidence score (0–100), an optional
   drafted message, and a tier.
3. The backend handles each item according to its tier:

| Tier | Meaning | What Keeper does |
| --- | --- | --- |
| L1 | Read-only observation | Logs it as executed automatically |
| L2 | Low-stakes action, such as a routine reminder | Logs it as executed automatically |
| L3 | Needs human sign-off, such as an escalation or settlement offer | Puts it in the approval queue |
| L4 | Would change financial records or post to the ERP | Flags it for manual action and never executes it |

You can also ask Keeper free-text questions. Its answers are grounded in the account
data and the actions taken so far.

## Requirements

- Python 3.9 or later
- An Anthropic API key
- Any static file server for the frontend (`python3 -m http.server` works)

## Quickstart

### 1. Install the backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Store your API key

The backend reads the key from the system keyring, not from a `.env` file. Store it
once:

```bash
python3 -c "import keyring, getpass; from keyrings.alt.file import PlaintextKeyring; keyring.set_keyring(PlaintextKeyring()); keyring.set_password('anthropic_key', 'key', getpass.getpass('API key: '))"
```

> [!WARNING]
> `PlaintextKeyring` writes the key unencrypted to a file in your home directory.
> Never commit the key or paste it into shared logs.

### 3. Start the backend

```bash
PORT=8765 python3 main.py
```

The API is now running at `http://localhost:8765`, with interactive docs at
`http://localhost:8765/docs`. The server reloads automatically when you edit the code.

### 4. Start the frontend

In a second terminal:

```bash
cd frontend
python3 -m http.server 8766
```

Open `http://localhost:8766` in your browser.

## Configuration

| Setting | Where | Default | Description |
| --- | --- | --- | --- |
| API key | Keyring entry `anthropic_key` / `key` | — | Required. Your Anthropic API key. |
| `PORT` | Environment variable | `3001` | The port the backend listens on. |
| `ANTHROPIC_WORKSPACE_ID` | Environment variable | unset | Required only if your key isn't scoped to a workspace. Sent as the `anthropic-workspace-id` header. |
| `MODEL` | Constant in [`backend/main.py`](backend/main.py) | `claude-haiku-5-5` | The Claude model used for briefings and answers. |
| `API` | Constant in [`frontend/app.js`](frontend/app.js) | `http://localhost:8765` | The backend URL the frontend calls. It must match `PORT`. |

Example with a workspace ID:

```bash
ANTHROPIC_WORKSPACE_ID=wrkspc_... PORT=8765 python3 main.py
```

## API reference

All routes are served under `/api`.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/customers` | Returns the raw customer and invoice dataset. |
| `POST` | `/api/briefing` | Calls Claude, builds the worklist, and resets the audit trail. Returns `briefingSummary`, `cashNote`, `worklist`, and `auditTrail`. |
| `GET` | `/api/worklist` | Returns the current briefing and worklist. |
| `GET` | `/api/audit` | Returns the audit trail, newest entry first. |
| `POST` | `/api/actions/{key}/approve` | Approves a pending item and logs it. `key` is `<customer id>\|<invoice ref>`. |
| `POST` | `/api/actions/{key}/reject` | Rejects a pending item and logs it. |
| `POST` | `/api/ask` | Answers a question. Body: `{"question": "..."}`. Returns `{"answer": "..."}`. |

Example:

```bash
curl -X POST http://localhost:8765/api/briefing
curl -X POST http://localhost:8765/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Which accounts are most at risk this week?"}'
```

## Project structure

```
autocash-agent/
├── backend/
│   ├── main.py              # FastAPI app, Claude calls, routes, in-memory state
│   ├── data.py              # Fictional company, customers, and invoices
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── app.js               # UI logic; set the backend URL in the API constant
│   └── styles.css
├── keeper-ar-agent.html     # Earlier single-file version that calls the API from the browser
└── autocash-agent.yml       # Conda environment export
```

## Troubleshooting

**"Failed to fetch" in the browser**
Either the backend isn't running, or the frontend is calling a different port. Check
that `PORT` matches the `API` constant in `frontend/app.js`.

**`localhost` doesn't respond, but the server is running**
Another process, such as a VS Code extension, may already be bound to that port. Run
`lsof -iTCP:<port> -sTCP:LISTEN` to see what's there, and switch to a free port if
needed. Use `localhost` in the browser, not `0.0.0.0`.

**`This API key is not scoped to a workspace`**
Set `ANTHROPIC_WORKSPACE_ID` to the ID shown under Console → Settings → Workspaces, or
create a workspace-scoped API key (`sk-ant-api03-...`) instead.

**`anthropic-workspace-id header must be a valid workspace ID`**
The ID is wrong or belongs to another organization. Copy it again from the Console.

## Limitations

- **In-memory state.** The worklist and audit trail reset whenever the server restarts.
  Use a database such as SQLite or Postgres if they need to persist.
- **Fictional data.** `backend/data.py` contains a sample dataset. Replace it with a
  real invoice feed or an ERP connector before using Keeper on real accounts.
- **No authentication, open CORS.** No route requires auth, and CORS allows every
  origin (`allow_origins=["*"]`). Lock both down before exposing the API beyond
  localhost.
- **Actions are simulated.** "Executed" and "Approved & executed" are audit-trail
  statuses only. Keeper doesn't send emails or post to any system.
