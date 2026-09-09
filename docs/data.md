# Data reference

Everything the app persists lives under `python-backend/` as files at fixed locations, all gitignored: OAuth material
in `.secrets/`, everything the app writes in `data/`, and the log in `logs/`.

## Entities

![entities](images/entities.svg)

<sub>Source: [diagrams/entities.mmd](diagrams/entities.mmd)</sub>

## Files

| File | Written by | Read by |
| --- | --- | --- |
| `data/mail_assistant.db` | Watcher (new mail as `pending`), router `save`, manager `handle`, API PATCH and send | Triage cron, Inbox tab, Home panel, report `gather` |
| `data/long_term_memory.json` | Memory chat | Router `recall`, report `write`, manager `recall`, Memory tab |
| `data/pre_triage_ignore_list.json` | Router `remember` for sender-stable ignores, Memory tab edits | Router `pre_triage`, Memory tab |
| `data/traces.jsonl` | Router steps, manager `handle` | Traces tab |
| `data/inbox_report.json` | Report agent `generate` | Home tab |
| `data/mail_check_state.json` | Watcher, after every message | Watcher at start |
| `.secrets/credentials.json` | You, from Google Cloud | OAuth consent flow |
| `.secrets/token.json` | OAuth consent flow | Every mailbox and calendar client |
| `logs/mail_assistant.log` | All modules | You |

### `emails` table

One row per email, keyed by Gmail's message id. Columns mirror `EmailMessage`; `label_ids` is JSON, `received_at` is
ISO text. `applied_rule` and `action` are added to older files on first connect.

| `applied_rule` value | Meaning |
| --- | --- |
| a base rule name | The model cited that base rule, e.g. `marketing_promotions` |
| a learned rule name | The model cited a rule you taught it |
| `gmail_promotions`, `gmail_social`, `gmail_forums`, `gmail_spam`, `gmail_muted`, `label_<name>` | `pre_triage` ignored it by Gmail category or your label, no model call |
| `ignore_list_<reason>` | `pre_triage` ignored it because the sender is on the pre-triage ignore list under that reason |
| `pre_triage` | You had already replied in the thread |
| `manual` | You set the category in the Inbox tab |
| `none` | The model applied no rule, or a reply was downgraded to `notify` |
| empty | Triage failed; category is `pending` |

`action` is empty until the inbox manager runs, then holds the write tools' results (`save_draft: ...`,
`create_reminder: ...`, `respond_to_invite: ...`), `no action: <the model's sentence>`, or `failed: <error>`.

### `long_term_memory.json`

```json
{
  "learned_preferences": "- team_meeting_replies: Confirm meeting requests from team.com yourself (auto_schedule)
- ignore_github: Ignore GitHub notifications, overriding github_notifications"
}
```

The base rules are not in this file; they are the `LONG_TERM_MEMORY` list in `db/__memory_store__.py` and appear in
the prompt above the learned rules. There is no per-sender memory: ignored senders live in the pre-triage ignore list.

### `pre_triage_ignore_list.json`

```json
[
  {"ignore_reason_label": "promotions", "senders": ["deals@shop.com", "ea@e.ea.com"]},
  {"ignore_reason_label": "newsletter", "senders": ["access@interactive.wsj.com"]}
]
```

Labels: `promotions`, `newsletter`, `social`, `spam`, `subscription`, `marketing`, `notification`, `miscellaneous`. A
sender appears under one label. `remember` adds senders from ignore decisions whose rule is about the sender rather than
one email; the Memory tab adds, moves, and removes them.

### `traces.jsonl`

One JSON object per line, newest last. `step` is `manual_user_input` (a category saved by hand in the Inbox tab, written by the router's `check_source` node), `pre_triage`, `triage`, `inbox_manager`,
`inbox_report`, or `memory_chat`. For the manager, `rule` holds the tools used and `reason` the action. The last two are
not about one email, so their email fields are empty: the overview line has `write` or `unchanged` as `rule` and a
summary (items, threads, first thing) as `reason`; the memory chat line has your message as `subject`, `rules_updated` or `rules_unchanged` as `rule`, and the
reply as `reason`.

### `inbox_report.json`

```json
{"generated_at": "...", "counts": {"unread": 12, "needs_review": 7, "events_today": 1, "pending_invites": 0, "candidates": 9}, "fingerprint": "...", "item_ids": ["1a08..."], "briefing": "**Unread email:** ..."}
```

## Settings

All settings are read once in `config/__app_config__.py` from `.env`. The full list with defaults is in
`python-backend/.env.example` and the table in `python-backend/README.md`. The ones that change behaviour most:

| Setting | Effect |
| --- | --- |
| `TRIAGE_`, `MEMORY_CHAT_`, `MANAGER_`, `REPORT_` + `LLM_PROVIDER` / `MODEL` | Each agent's provider and model |
| `OLLAMA_NUM_CTX` | Context window requested from Ollama; the default 4096 truncates tool-heavy prompts |
| `MAIL_BACKFILL_DAYS` | On a fresh start, how far back the watcher stores mail |
| `TRIAGE_INTERVAL_SECONDS` | How often stored mail is sent to the triage graph |
| `PRE_TRIAGE_IGNORE_LABELS` | Your labels that pre-triage treats as `ignore` |
| `REPORT_INTERVAL_SECONDS` | Quick Overview cadence |
| `GMAIL_ADDRESS` | The mailbox; the IMAP login name |
