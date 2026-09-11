# mail-assistant

Python backend for the Mailbox Personal Assistant. A watcher blocks on IMAP IDLE and stores every new inbox message in
SQLite as `pending`; a triage cron hands stored mail to a LangGraph graph. Emails you already replied to, and mail Gmail or
your ignore list has already sorted away, are decided without a model; the rest are categorized by a model as `ignore`,
`notify`, `auto_schedule`, or `auto_draft` with a reason and the rule applied. `auto_schedule` and `auto_draft` mail goes to
the inbox manager agent, which creates reminders, answers invitations, or saves a draft reply. A report agent writes the
Quick Overview for the Home tab. A FastAPI service and a React UI (in `../react-frontend`) let you review the list, change
a category, ignore a sender, and send a drafted reply.

Architecture, sequence diagrams, state graphs, and the data reference are in [`../docs`](../docs/README.md).

## Setup

1. Install [uv](https://docs.astral.sh/uv/), Python 3.13, and Node 20+.
2. Install backend dependencies:
   ```bash
   uv sync
   ```
3. Set up Google access by following [`../docs/google-setup.md`](../docs/google-setup.md): a Google Cloud project with
   the Calendar API enabled, an OAuth consent screen with the `https://mail.google.com/` and `calendar.events` scopes and
   yourself as a test user, a Desktop-app OAuth client saved as `.secrets/credentials.json` in this folder, and IMAP enabled in Gmail. A `token.json` granted for narrower scopes is ignored and the
   consent flow runs again at the next start. To grant or re-grant everything in one go, run:
   ```bash
   uv run mail-assistant-auth
   ```
   It discards `.secrets/token.json`, opens the browser for consent to all required scopes, and saves the new token.
4. Pick a provider and model for each of the four agents (`TRIAGE_`, `MEMORY_CHAT_`, `MANAGER_`, `REPORT_` with
   `LLM_PROVIDER` and `MODEL`). The defaults are local models via [Ollama](https://ollama.com):
   ```bash
   ollama pull qwen3:4b qwen3:8b
   ```
   Ollama must be running whenever the app runs; otherwise every email is stored as `pending` with a "triage failed" reason.
   For a hosted model set an agent's provider to `anthropic` or `openai` with the matching API key in `.env`. The provider
   modules live in `src/mail_assistant/agents/llm/`.
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

One command starts everything. The `mail-assistant` entry point (`src/mail_assistant/__init__.py`) launches the mail
watcher, the triage cron, and the report cron in background threads and then serves the API and the built React UI. The
report cron builds the Quick Overview at startup and every `REPORT_INTERVAL_SECONDS` (three hours by default), skipping
the model when nothing changed; the Home tab shows the saved overview on load, and Rebuild builds a new one on demand.

```bash
cd ../react-frontend && npm run build && cd ../python-backend   # build the UI once, or after UI changes
uv run mail-assistant
```

Open http://localhost:8000. API docs are at http://localhost:8000/docs. You will see `Mail watcher started`, `Triage cron
started`, and `Report cron started` in the log. The first run opens a browser for Google consent and caches the token in
`.secrets/token.json`. With no cursor file it stores the last `MAIL_BACKFILL_DAYS` of inbox mail (0 waits for new mail
only). Each new email is stored in `data/mail_assistant.db` at once as `pending`, triaged within `TRIAGE_INTERVAL_SECONDS`,
and shows up in the UI within its 30 second refresh. Delete `data/mail_check_state.json` to re-baseline.

### Development with hot reload

For code changes without restarts, run the pieces separately. The Vite dev server proxies `/api` to port 8000.

```bash
uv run uvicorn mail_assistant.api.__app__:app --reload                # python-backend: API only, restarts on code changes
uv run python -m mail_assistant.mail_watcher.__new_mail_watcher__     # python-backend: IMAP IDLE watcher, stores new mail as pending
uv run python -m mail_assistant.cron_job.__triage_cron__              # python-backend: triage stored mail every TRIAGE_INTERVAL_SECONDS
uv run python -m mail_assistant.cron_job.__report_generation_cron__   # python-backend: Quick Overview every REPORT_INTERVAL_SECONDS
npm run dev                                                           # react-frontend: UI on http://localhost:5173
```

Stop any process with `Ctrl+C`.

### Troubleshooting

- `ECONNREFUSED` in the Vite terminal: the API is not running. Start it first.
- Every email shows `pending` with reason `triage failed: ...`: Ollama is not running or the model is not pulled. Run
  `ollama serve` and `ollama pull qwen3:4b qwen3:8b`, then restart the server.
- Empty list in the UI: nothing has been stored yet. Send yourself a test email; the watcher stores it at once and the
  triage cron picks it up within `TRIAGE_INTERVAL_SECONDS`. The Inbox tab shows `notify` by default; switch the filter to
  `pending` or all categories to see mail that is still waiting for triage.
- Port 8000 or 5173 already in use: pass `--port 8001` to uvicorn (and update `react-frontend/vite.config.js`) or
  `npm run dev -- --port 5174`.

Settings are read from `.env` in this folder (see `.env.example` for a documented template). File locations are fixed:
`.secrets/` holds `credentials.json` and `token.json`; `data/` holds `mail_assistant.db`, `long_term_memory.json`,
`pre_triage_ignore_list.json`, `traces.jsonl`, `inbox_report.json`, and `mail_check_state.json` (the watcher's cursor,
delete it to start over); `logs/` holds the log. The server port is 8000.

| Variable | Default | Purpose |
| --- | --- | --- |
| `GMAIL_ADDRESS` | | The mailbox address, required: it is the IMAP login name |
| `TRIAGE_LLM_PROVIDER`, `TRIAGE_MODEL` | `ollama`, `qwen3:4b` | Triage router (structured output) |
| `MEMORY_CHAT_LLM_PROVIDER`, `MEMORY_CHAT_MODEL` | `ollama`, `qwen3:4b` | Memory chat (structured output; a small model is enough) |
| `MANAGER_LLM_PROVIDER`, `MANAGER_MODEL` | `ollama`, `qwen3:8b` | Inbox manager (tool calling) |
| `REPORT_LLM_PROVIDER`, `REPORT_MODEL` | `ollama`, `qwen3:8b` | Quick Overview (one structured call over a snapshot gathered by code) |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama server |
| `OLLAMA_NUM_CTX` | `32768` | Context window requested from Ollama for every local model call; the default 4096 truncates the manager's tool results and the overview snapshot |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | | Needed only by agents on that provider |
| `LANGSMITH_TRACING` | `false` | `true` sends every graph run, model call, and tool call to LangSmith; needs `LANGSMITH_API_KEY`, and `LANGSMITH_PROJECT` names the project |
| `MAIL_BACKFILL_DAYS` | `0` | On a fresh start with no cursor, store inbox mail from this many days ago before waiting for new mail |
| `PRE_TRIAGE_IGNORE_LABELS` | | Comma-separated Gmail labels whose mail pre-triage marks `ignore` without a model call; matched case-insensitively, and system labels may be written as Gmail names them (`SENT`, `DRAFT`, `CHAT`, `SPAM`, `TRASH`). Muted threads are always treated that way (rule `gmail_muted`); Gmail's Promotions, Social, and Forums tabs are not used as decisions |
| `TRIAGE_INTERVAL_SECONDS` | `30` | Seconds between passes that send newly stored mail to the triage agent |
| `TRIAGE_WORKERS` | `5` | Emails triaged at the same time within a pass; threads start only when there is work. Each worker holds its own IMAP connection, and Gmail allows 15 per account |
| `REPORT_INTERVAL_SECONDS` | `10800` | Seconds between automatic Quick Overview builds; the first is at startup, and a build is skipped when nothing changed |
| `LOG_LEVEL` | `INFO` | Set to `DEBUG` to log full message contents |

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/emails?category=&page=1&page_size=20` | Paginated list, newest first, optional category filter |
| GET | `/api/emails/{id}` | One email |
| POST | `/api/emails/{id}/read` | Mark the email read in Gmail and drop its `UNREAD` label |
| POST | `/api/emails/{id}/retriage` | Body `{"reason": "..."}`, the person's feedback in prose; the feedback agent keeps or ignores the sender and may add a learned rule, then triage runs again; returns the email plus `reply`, `kept`, `ignored`, `rule_added` |
| GET | `/api/emails/{id}/draft` | The draft already in Gmail's Drafts on the email's thread, by the manager or by hand; 404 when there is none |
| POST | `/api/emails/{id}/draft` | The inbox manager drafts a reply now (saved in Gmail's Drafts); returns `{to, subject, body, draft_message_id}` |
| POST | `/api/emails/{id}/send` | Body: the edited draft; sends it as a reply on the thread over SMTP, discards any Gmail draft on the thread, and files the email as `user_reply_complete` (rule `manual`) |
| PATCH | `/api/emails/{id}` | Body `{"category": "...", "reason": "..."}`; runs the triage graph as a user decision (no re-triage): saved with rule `manual`, traced as `manual_user_input`, an `ignore` with a sender-stable reason puts the sender on the ignore list, and `auto_schedule` or `auto_draft` triggers the inbox manager |
| GET | `/api/memory` | Long-term memory: named base rules (from code) and learned rules (`- name: rule` lines) |
| GET | `/api/ignore-list` | The pre-triage ignore list: senders grouped by reason (`promotions`, `newsletter`, `social`, `spam`, `subscription`, `marketing`, `notification`, `miscellaneous`) |
| POST / DELETE | `/api/ignore-list`, `/api/ignore-list/{sender}` | Add or move one sender (`{"sender": ..., "ignore_reason_label": ...}`), or remove one |
| GET / POST / DELETE | `/api/keep-list`, `/api/keep-list/{entry}` | The keep list of addresses and domains that always reach the triage model; add `{"entry": "53.com"}` or remove one |
| POST | `/api/memory/chat` | Body `{"message": "..."}`; the model returns named additions and removals, code merges them into the learned rules (removals only when the message asks), and the reply plus the new rules come back |
| GET | `/api/home` | Counts and newest items for the Home tab: emails the inbox manager acted on, with the action (the UI shows this one), plus triage items waiting on you (`notify`, `auto_draft`, `pending`), which the UI no longer shows |
| GET | `/api/report` | The last Quick Overview (`briefing` is null until one is built) |
| POST | `/api/report/refresh` | Build a fresh Quick Overview: code gathers the last 30 days of stored mail, the Sent folder, and the calendar into one snapshot, and one model call writes the sections |
| GET | `/api/traces?step=&q=&page=1&page_size=20` | Trace log, newest first, optionally limited to one step (`manual_user_input`, `pre_triage`, `triage`, `inbox_manager`, `inbox_report`, `memory_chat`), with category, rule, reason, duration, and `action_taken` (what the step did, e.g. `created_draft`, `categorized_auto_draft`) |
| GET | `/api/graph` | Every agent graph (triage router, inbox manager, inbox report) with node descriptions and edges, used by the UI's Graph tab |

Categories: `ignore`, `notify`, `auto_schedule`, `user_reply_complete`, `auto_draft`, `pending`. For `auto_schedule` the inbox manager may create a calendar reminder or answer a meeting invitation; for `auto_draft` it saves a draft reply on the thread; what it did is stored in the email's `action` and traced. Base rules decide only `ignore` and `notify`; the assistant acts (`auto_schedule`, `auto_draft`) only for emails covered by a learned rule added through the Memory chat, for example a sender or a kind of email such as meeting requests. Each email also carries `applied_rule`: the base or learned rule the model applied, `pre_triage` when it was skipped as already replied, `gmail_*`, `label_*`, or `ignore_list_*` when pre-triage ignored it, or `manual` after a correction in the UI. Interactive docs at http://localhost:8000/docs.

## Code style

[ruff](https://docs.astral.sh/ruff/) lints and formats the backend; its rules live in `pyproject.toml`. Run it before committing:

```bash
uv run ruff check --fix src && uv run ruff format src
```

## Logs

All logs from every thread are written to `logs/mail_assistant.log` in this folder and also printed to the console.
At `LOG_LEVEL=DEBUG` this includes full message dumps and IMAP chatter.

```bash
tail -f logs/mail_assistant.log
```
