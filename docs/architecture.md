# Architecture

Mailbox Personal Assistant watches a Gmail inbox, triages every new email with a language model guided by long-term
memory, acts on some of them, and keeps a start-of-day briefing. It runs as one Python process plus a React UI.

## Components

![components](images/components.svg)

<sub>Source: [diagrams/components.mmd](diagrams/components.mmd)</sub>

## Process model

`uv run mail-assistant` starts three things in one process (`src/mail_assistant/__init__.py`):

| Thread | Module | Job |
| --- | --- | --- |
| Mail watcher | `mail_watcher/__new_mail_watcher__.py` | Blocks on IMAP IDLE; every new inbox message runs the triage router. The cursor (`UIDVALIDITY:lastUID`) is saved after each message, so a restart resumes without repeating work. On a fresh start it backfills `MAIL_BACKFILL_DAYS` of inbox mail. |
| Report cron | `cron_job/__report_generation_cron__.py` | Builds the inbox briefing at startup and every `REPORT_INTERVAL_SECONDS`, writing `inbox_report.json`. |
| API server | `api/__app__.py` on uvicorn | Serves `/api/*` and the built React UI. A PATCH from the Triage tab runs the router with `source = "user"`; Rebuild runs the report agent; the Memory chat rewrites the learned rules. |

All three share one OAuth token with the full-mail and calendar-events scopes (`gmail_client/auth.py`). Each thread opens
its own IMAP connection; connections that Gmail drops are reconnected once and the operation retried, and sockets have a
read timeout so a half-open connection cannot block a thread forever.

## Agents

There are three LangGraph graphs; their state graphs are in [state-graphs.md](state-graphs.md).

| Agent | Trigger | Model use | Writes |
| --- | --- | --- | --- |
| Email triage router | Each new email; each category saved by hand | One structured-output call in `triage`, skipped when `pre_triage` already decided | SQLite row, sender memory, trace lines |
| Inbox manager | Router, for `agentrespond` and `agentdraftonly` | A tool loop with only the category's tools | Calendar event or RSVP (`agentrespond`), a Gmail draft (`agentdraftonly`), the email's `action`, a trace line |
| Inbox report | Cron and Rebuild | A tool loop over read-only mailbox tools | `inbox_report.json` |

Model provider is per agent: triage and the manager use `LLM_PROVIDER` (`ollama`, `anthropic`, `openai`); the briefing
uses `REPORT_LLM_PROVIDER` and `REPORT_MODEL`. Every model call goes through `agents/llm/__structured_llm__.py`.

## Long-term memory

Memory has three parts, all read by the router and the report agent and shown on the Memory tab:

- **Base rules** live in code (`db/__memory_store__.py`, `LONG_TERM_MEMORY`): named rules that only ever yield `ignore`
  or `notify`.
- **Learned rules** live in `long_term_memory.json` as `- name: rule` lines, edited through the Memory tab's chat, which
  has the model rewrite the list. Learned rules win over base rules and are the only way to unlock a reply category.
- **Sender facts** live in the same file: the latest category, reason, and count per sender, written after every
  decision and every manual correction.

## Categories and rules

| Category | Meaning | Who decides |
| --- | --- | --- |
| `ignore` | Not worth reading | `pre_triage` by Gmail label, or the model by a base or learned rule |
| `notify` | Worth knowing, no reply | The model; also the default when it cannot decide |
| `agentrespond` | The assistant may act alone | The model, only with a learned rule that names the sender or kind of mail |
| `agentdraftonly` | The assistant drafts, the person reviews | The model, only with a learned rule |
| `user_reply_complete` | The person already replied | `pre_triage` |
| `pending` | Triage failed | The router on any error |

Every stored email carries `applied_rule` (the rule name, `pre_triage`, `manual`, or empty) and `action` (what the
manager did). The Traces tab shows one line per graph step per email from `traces.jsonl`.

## Repository layout

```
python-backend/src/mail_assistant/
  __init__.py                    entry point: threads + uvicorn
  api/__app__.py                 FastAPI routes, serves react-frontend/dist
  agents/
    __email_triage_router_agent__.py
    __inbox_manager_agent__.py
    __inbox_report_agent__.py
    __memory_chat_agent__.py     Memory tab chat -> learned rules
    llm/__structured_llm__.py    provider switch, structured output
    tools/__gmail_tools__.py     IMAP tools (read and write sets)
    tools/__calendar_tools__.py  Calendar API tools
    skills/*/SKILL.md            prompts for the manager and the report
  gmail_client/                  auth.py (OAuth), imap.py, calendar.py
  mail_watcher/                  IMAP IDLE watcher
  cron_job/                      report cron
  db/                            SQLite store, memory store, trace store
  models/                        EmailMessage, Category, memory records
  config/__app_config__.py       the only module that reads .env
react-frontend/src/              App.jsx (tabs) and views/
docs/                            this folder
```
