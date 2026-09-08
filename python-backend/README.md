# mail-assistant

Python backend for the Mailbox Personal Assistant. A poller watches Gmail for new inbox messages and hands each one to a
LangGraph graph. Emails the user has already replied to are stored as `user_reply_complete` without further work; the rest are
categorized by a local model as `ignore`, `notify`, `agentrespond`, or `agentdraftonly` with a reason, stored in SQLite, and the
two `agent*` categories are routed to the inbox manager agent. A FastAPI service and a React UI
(in `../react-frontend`) let you review the list and change a message's category. Messages in `agentrespond` or `agentdraftonly` are
handed to the inbox manager agent (a placeholder for now).

Architecture, sequence diagrams, state graphs, and the data reference are in [`../docs`](../docs/README.md).

## Setup

1. Install [uv](https://docs.astral.sh/uv/), Python 3.13, and Node 20+.
2. Install backend dependencies:
   ```bash
   uv sync
   ```
3. Set up Google access by following [`../docs/google-setup.md`](../docs/google-setup.md): a Google Cloud project with
   the Calendar API enabled, an OAuth consent screen with the `https://mail.google.com/` and `calendar.events` scopes and
   yourself as a test user, a Desktop-app OAuth client saved as `credentials.json` in this folder (or pointed at by
   `GMAIL_CREDENTIALS_FILE`), and IMAP enabled in Gmail. A `token.json` granted for narrower scopes is ignored and the
   consent flow runs again at the next start. To grant or re-grant everything in one go, run:
   ```bash
   uv run mail-assistant-auth
   ```
   It discards `token.json`, opens the browser for consent to all required scopes, and saves the new token.
4. Pick a model backend for triage. The default is a local model via [Ollama](https://ollama.com):
   ```bash
   ollama pull gpt-oss:20b
   ```
   Ollama must be running whenever the poller runs; otherwise every email is stored as `pending` with a "triage failed" reason.
   To use a cloud model instead, set `LLM_PROVIDER=anthropic` with `ANTHROPIC_API_KEY`, or `LLM_PROVIDER=openai` with
   `OPENAI_API_KEY`, in `.env`. The provider modules live in `src/mail_assistant/agents/llm/`.
5. Create your local settings file from the template and fill in any API keys:
   ```bash
   cp .env.example .env
   ```
   `.env` is gitignored. Every setting is optional and documented in the template; the full list is in the table below.
6. Install the UI:
   ```bash
   cd ../react-frontend && npm install
   ```

## Run

One command starts everything. The `mail-assistant` entry point (`src/mail_assistant/__init__.py`) launches the Gmail
poller and the report cron in background threads and then serves the API and the built React UI. The report cron
builds the inbox briefing at startup and every `REPORT_INTERVAL_SECONDS` (three hours by default); the Home tab shows
the saved briefing on load, and Rebuild builds a new one on demand.

```bash
cd ../react-frontend && npm run build && cd ../python-backend   # build the UI once, or after UI changes
uv run mail-assistant
```

Open http://localhost:8000. API docs are at http://localhost:8000/docs. You will see `Mail poller started` in the log.
The first run opens a browser for Google consent and caches the token in `token.json`. It only records the current mailbox
position, so the list stays empty until new mail arrives. Each new email is triaged, stored in `mail_assistant.db`, and shows
up in the UI within its 30 second refresh. Delete `.mail_check_state.json` to re-baseline.

### Development with hot reload

For code changes without restarts, run the three pieces separately. The Vite dev server proxies `/api` to port 8000.

```bash
uv run uvicorn mail_assistant.api.__app__:app --reload                # python-backend: API only, restarts on code changes
uv run python -m mail_assistant.mail_watcher.__new_mail_watcher__     # python-backend: IMAP IDLE watcher + triage agent
uv run python -m mail_assistant.cron_job.__report_generation_cron__   # python-backend: inbox briefing every REPORT_INTERVAL_SECONDS
npm run dev                                                           # react-frontend: UI on http://localhost:5173
```

Stop any process with `Ctrl+C`.

### Troubleshooting

- `ECONNREFUSED` in the Vite terminal: the API is not running. Start it first.
- Every email shows `pending` with reason `triage failed: ...`: Ollama is not running or the model is not pulled. Run
  `ollama serve` and `ollama pull gpt-oss:20b`, then restart the server.
- Empty list in the UI: nothing has been triaged yet. Send yourself a test email and wait one poll interval.
- Port 8000 or 5173 already in use: pass `--port 8001` to uvicorn (and update `react-frontend/vite.config.js`) or
  `npm run dev -- --port 5174`.

Settings are read from `.env` in this folder (see `.env.example` for a documented template):

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_PROVIDER` | `ollama` | Which model backend triages mail: `ollama`, `anthropic`, or `openai` |
| `OLLAMA_MODEL` | `gpt-oss:20b` | Ollama model (when `LLM_PROVIDER=ollama`) |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama server |
| `OLLAMA_NUM_CTX` | `32768` | Context window requested from Ollama for every local model call; the default 4096 truncates the briefing prompt |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5` | Claude model (when `LLM_PROVIDER=anthropic`); needs `ANTHROPIC_API_KEY` |
| `OPENAI_MODEL` | `gpt-5-nano` | OpenAI model (when `LLM_PROVIDER=openai`); needs `OPENAI_API_KEY` |
| `REPORT_LLM_PROVIDER` | `ollama` | Provider for the inbox briefing, independent of triage |
| `REPORT_MODEL` | `gemma4:12b` | Model for the inbox briefing; must support tool calling |
| `GMAIL_CREDENTIALS_FILE` | `credentials.json` | OAuth client secrets |
| `GMAIL_TOKEN_FILE` | `token.json` | Cached user token |
| `MAIL_CHECK_STATE_FILE` | `.mail_check_state.json` | Stores the watcher's cursor so mail that arrives while the app is down is still triaged; delete it to start over |
| `MAIL_BACKFILL_DAYS` | `0` | On a fresh start with no cursor, triage inbox mail from this many days ago before waiting for new mail |
| `PRE_TRIAGE_IGNORE_LABELS` | | Comma-separated Gmail labels of yours whose mail pre-triage marks `ignore` without a model call. Gmail's Promotions, Social, Forums, Spam, and muted mail are always treated that way (rules `gmail_promotions`, `gmail_social`, `gmail_forums`, `gmail_spam`, `gmail_muted`) |
| `REPORT_INTERVAL_SECONDS` | `10800` | Seconds between automatic inbox briefings; the first is built at startup |
| `GMAIL_ADDRESS` | | The mailbox address, required: it is the IMAP login name |
| `MAIL_DB_FILE` | `mail_assistant.db` | SQLite database |
| `REPORT_FILE` | `inbox_report.json` | Last inbox briefing, shown on the Home tab |
| `TRACE_FILE` | `traces.jsonl` | Trace log written by the triage graph, one JSON line per step per email |
| `MEMORY_FILE` | `long_term_memory.json` | Long-term memory: learned preferences prose plus the latest category and reason per sender |
| `LOG_LEVEL` | `INFO` | Set to `DEBUG` to log full message contents |
| `API_PORT` | `8000` | Port used by `uv run mail-assistant` |

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/emails?category=&page=1&page_size=20` | Paginated list, newest first, optional category filter |
| GET | `/api/emails/{id}` | One email |
| PATCH | `/api/emails/{id}` | Body `{"category": "...", "reason": "..."}`; runs the triage graph as a user decision (no re-triage): saved with rule `manual`, remembered for the sender, traced, and `agentrespond` or `agentdraftonly` triggers the inbox manager |
| GET | `/api/memory` | Long-term memory: named base rules (from code), learned rules (`- name: rule` lines), and per-sender facts |
| POST | `/api/memory/chat` | Body `{"message": "..."}`; the model rewrites the learned preferences per the message and returns a reply |
| GET | `/api/home` | Counts and newest items for the Home tab: triage items waiting on you (`notify`, `agentdraftonly`, `pending`) and emails the inbox manager acted on, with the action |
| GET | `/api/report` | The last inbox briefing (`briefing` is null until one is built) |
| POST | `/api/report/refresh` | Build a fresh briefing: the report agent reads the last 14 days of mail with read-only tools and writes prose; several model calls |
| GET | `/api/traces?q=&page=1&page_size=20` | Trace log of every `pre_triage` and `triage` step, newest first, with category, rule, reason, and duration |
| GET | `/api/graph` | Every agent graph (triage router, inbox manager, inbox report) with node descriptions and edges, used by the UI's Graph tab |

Categories: `ignore`, `notify`, `agentrespond`, `user_reply_complete`, `agentdraftonly`, `pending`. For `agentrespond` the inbox manager may create a calendar reminder or answer a meeting invitation; for `agentdraftonly` it saves a draft reply on the thread; what it did is stored in the email's `action` and traced. Base rules decide only `ignore` and `notify`; the assistant replies (`agentrespond`, `agentdraftonly`) only for emails covered by a learned rule added through the Memory chat, for example a sender or a kind of email such as meeting requests. Each email also carries `applied_rule`: the base or learned rule the model applied, `pre_triage` when it was skipped as already replied, or `manual` after a correction in the UI. Interactive docs at http://localhost:8000/docs.

## Code style

[ruff](https://docs.astral.sh/ruff/) lints and formats the backend; its rules live in `pyproject.toml`. Run it before committing:

```bash
uv run ruff check --fix src && uv run ruff format src
```

## Logs

All logs from the poller and the API are written to `logs/mail_assistant.log` in this folder and also printed to the console.
At `LOG_LEVEL=DEBUG` this includes full message dumps and Gmail API chatter.

```bash
tail -f logs/mail_assistant.log
```
