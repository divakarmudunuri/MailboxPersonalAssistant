# Mailbox Personal Assistant

A personal assistant for a Gmail inbox, built as a CMU capstone project. It watches the inbox, triages every new
email with a language model guided by long-term memory, acts on some of them, and writes a start-of-day Quick Overview.
You review and correct it from a small web UI, and teach it rules in a chat.

## Demo

[![Watch the demo on YouTube](https://img.youtube.com/vi/HMPWVJ34wCo/maxresdefault.jpg)](https://www.youtube.com/watch?v=HMPWVJ34wCo)

A walkthrough of the app: triage, the Quick Overview, the inbox manager acting on mail, and the Memory tab.

## What it does

- **Triage.** Each new email gets a category: `ignore`, `notify`, `auto_schedule`, `auto_draft`,
  `user_reply_complete`, or `pending`. Mail Gmail already sorted into Promotions, Social, Forums, or Spam, and
  threads you already replied to, are decided without a model call. Everything else goes to the model with your rules
  and the decision records which rule it applied.
- **Long-term memory.** Base rules live in code; the rules you teach it through the Memory tab's chat live in a JSON
  file and win over the base rules. Ignored senders go on a separate pre-triage ignore list you can edit.
- **Acting.** For `auto_schedule` mail the inbox manager can create a calendar reminder or answer a meeting invitation.
  For `auto_draft` it saves a draft reply on the thread for you to review. The agents never send mail: only
  the Reply button in the Inbox tab does, after the manager drafts the reply and you edit and confirm it.
- **Quick Overview.** The app gathers the last 30 days of stored mail, your Sent folder, and your calendar into one
  snapshot, and a single model call writes the overview: unread count, what needs review, today's calendar with prep
  notes, what is waiting on you and on others, deadlines named in email, money and account notices, and the first
  thing to do. Each item links to the email in the Inbox tab. Rebuilt at startup, every three hours when something
  changed, and on demand.
- **Traces.** Every step the agents take is logged to a trace file and shown in the UI, with the category, the rule,
  and the action.

Mail is read over IMAP with OAuth, so new mail is detected instantly and no Gmail API quota is used. Models can be
local through Ollama or hosted through the Anthropic or OpenAI APIs, chosen per agent.

## Requirements

- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- Node 20 or newer, for the UI
- A Google Cloud project with an OAuth client of type Desktop app and the Google Calendar API enabled
- IMAP enabled in the Gmail account's settings
- One of: [Ollama](https://ollama.com) with a pulled model, an Anthropic API key, or an OpenAI API key

## Run it

```bash
# 1. backend dependencies
cd python-backend
uv sync

# 2. settings: copy the template, then set GMAIL_ADDRESS, the model provider, and any API keys
cp .env.example .env

# 3. local models, if you use Ollama (the default): install it from https://ollama.com, then pull
#    every model named in .env (the minimum profile in .env.example uses these two)
ollama pull qwen3:4b
ollama pull qwen3:8b

# 4. save the OAuth client secrets as .secrets/credentials.json (folder is gitignored), then grant access once
#    (Google Cloud steps: docs/google-setup.md)
uv run mail-assistant-auth

# 5. build the UI once (repeat after UI changes)
cd ../react-frontend && npm install && npm run build

# 6. start everything: mail watcher, triage cron, report cron, API, and the UI on http://localhost:8000
cd ../python-backend
uv run mail-assistant
```

Ollama must be running whenever the app runs; otherwise every email stays `pending`. Any model that supports
structured output works for triage, the memory chat, and the overview; the inbox manager also needs tool calling, and a
hosted model (`MANAGER_LLM_PROVIDER=anthropic` or `openai`) is markedly better at that than the local ones tested. Each agent has
its own provider and model in `.env` (`TRIAGE_`, `MEMORY_CHAT_`, `MANAGER_`, `REPORT_` with `LLM_PROVIDER` and `MODEL`);
`.env.example` ships the all-local minimum profile and describes the hosted maximum one. Skip step 3 entirely if every
agent is on a hosted provider.

To see every agent run, model call, and tool call in [LangSmith](https://smith.langchain.com), set
`LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, and `LANGSMITH_PROJECT` in `.env`. Runs are named after the agents:
`email_triage_router`, `inbox_manager`, `inbox_report`, and `memory_chat`, tagged with the source or category and
carrying the email id.

For development with hot reload, run the API with `uv run uvicorn mail_assistant.api.__app__:app --reload`, the
watcher with `uv run python -m mail_assistant.mail_watcher.__new_mail_watcher__`, the triage cron with
`uv run python -m mail_assistant.cron_job.__triage_cron__`, and the UI with `npm run dev` in
`react-frontend`, which proxies `/api` to port 8000. Details, every setting, and the API routes are in
[python-backend/README.md](python-backend/README.md).

## Documentation

| Page | What it covers |
| --- | --- |
| [docs/google-setup.md](docs/google-setup.md) | Google Cloud project, OAuth consent screen and client, IMAP in Gmail, the Calendar API, granting access, troubleshooting |
| [docs/architecture.md](docs/architecture.md) | Components, the process model, the three agents, memory, categories and rules, repository layout |
| [docs/sequences.md](docs/sequences.md) | Sequence diagrams for a new email, the inbox manager, a manual save, teaching a preference, the Quick Overview, and startup |
| [docs/state-graphs.md](docs/state-graphs.md) | The LangGraph state graphs, generated from the code |
| [docs/data.md](docs/data.md) | Entities, persisted files, rule and action vocabularies, key settings |
| [python-backend/README.md](python-backend/README.md) | Setup, settings, API routes, logs, code style |

## Layout

```
python-backend/   Python package mail_assistant: agents, mailbox and calendar clients, stores, API, entry point
react-frontend/   Vite + React UI: Home, Inbox, Traces, Memory, Graph
docs/             Google setup, architecture, sequence diagrams, state graphs, data reference (diagrams as SVG images)
```

## Status

Capstone work in progress. The triage router, memory, the Quick Overview, and the calendar and draft actions are implemented;
the agents deliberately cannot send mail; you send a drafted reply yourself from the Inbox tab.
