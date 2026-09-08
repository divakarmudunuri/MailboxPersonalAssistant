# Mailbox Personal Assistant

A personal assistant for a Gmail inbox, built as a CMU capstone project. It watches the inbox, triages every new
email with a language model guided by long-term memory, acts on some of them, and writes a start-of-day briefing.
You review and correct it from a small web UI, and it learns from those corrections.

## What it does

- **Triage.** Each new email gets a category: `ignore`, `notify`, `agentrespond`, `agentdraftonly`,
  `user_reply_complete`, or `pending`. Mail Gmail already sorted into Promotions, Social, Forums, or Spam, and
  threads you already replied to, are decided without a model call. Everything else goes to the model with your rules
  and what it remembers about the sender, and the decision records which rule it applied.
- **Long-term memory.** Base rules live in code; the rules you teach it through the Memory tab's chat live in a JSON
  file and win over the base rules. Every decision and every correction you make in the UI becomes a remembered fact
  about that sender.
- **Acting.** For `agentrespond` mail the inbox manager can create a calendar reminder or answer a meeting invitation.
  For `agentdraftonly` it saves a draft reply on the thread for you to review. It never sends mail.
- **Briefing.** A report agent reads the last two weeks of mail with read-only tools and writes a short briefing,
  rebuilt at startup, every three hours, and on demand.
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
#    the triage model (OLLAMA_MODEL) and, if REPORT_LLM_PROVIDER=ollama, the briefing model (REPORT_MODEL)
ollama pull gpt-oss:20b
ollama pull gemma4:12b

# 4. put the OAuth client secrets next to .env as credentials.json, then grant access once
#    (Google Cloud steps: docs/google-setup.md)
uv run mail-assistant-auth

# 5. build the UI once (repeat after UI changes)
cd ../react-frontend && npm install && npm run build

# 6. start everything: mail watcher, report cron, API, and the UI on http://localhost:8000
cd ../python-backend
uv run mail-assistant
```

Ollama must be running whenever the app runs; otherwise every email is stored as `pending`. Any model that supports
structured output works for triage; the briefing and the inbox manager also need tool calling, and a hosted model
(`REPORT_LLM_PROVIDER=anthropic` or `openai`) is markedly better at that than the local ones tested. Skip step 3
entirely if you set `LLM_PROVIDER` and `REPORT_LLM_PROVIDER` to a hosted provider.

For development with hot reload, run the API with `uv run uvicorn mail_assistant.api.__app__:app --reload`, the
watcher with `uv run python -m mail_assistant.mail_watcher.__new_mail_watcher__`, and the UI with `npm run dev` in
`react-frontend`, which proxies `/api` to port 8000. Details, every setting, and the API routes are in
[python-backend/README.md](python-backend/README.md).

## Documentation

| Page | What it covers |
| --- | --- |
| [docs/google-setup.md](docs/google-setup.md) | Google Cloud project, OAuth consent screen and client, IMAP in Gmail, the Calendar API, granting access, troubleshooting |
| [docs/architecture.md](docs/architecture.md) | Components, the process model, the three agents, memory, categories and rules, repository layout |
| [docs/sequences.md](docs/sequences.md) | Sequence diagrams for a new email, the inbox manager, a manual save, teaching a preference, the briefing, and startup |
| [docs/state-graphs.md](docs/state-graphs.md) | The LangGraph state graphs, generated from the code |
| [docs/data.md](docs/data.md) | Entities, persisted files, rule and action vocabularies, key settings |
| [python-backend/README.md](python-backend/README.md) | Setup, settings, API routes, logs, code style |

## Layout

```
python-backend/   Python package mail_assistant: agents, mailbox and calendar clients, stores, API, entry point
react-frontend/   Vite + React UI: Home, Triage, Traces, Memory, Graph
docs/             Google setup, architecture, sequence diagrams, state graphs, data reference (diagrams as SVG images)
```

## Status

Capstone work in progress. The triage router, memory, briefing, and the calendar and draft actions are implemented;
sending mail is deliberately not.
