# State graphs

These are the three LangGraph `StateGraph`s in the app. The diagram sources in `diagrams/graph-*.mmd` were produced by
LangGraph itself (`compiled.get_graph().draw_mermaid()`) and rendered to the images below. After changing a graph, update
the matching `.mmd` file (the Graph tab in the UI always shows the live graph) and re-render with `docs/render_images.sh`.

Dashed edges are conditional edges chosen at run time. The Graph tab in the UI draws the same graphs from `GET /api/graph`.

## Email triage router

`agents/__email_triage_router_agent__.py`. Runs once per new email from the watcher, and once per category saved by
hand in the Inbox tab (with `source = "user"`).

![graph-triage-router](images/graph-triage-router.svg)

<sub>Source: [diagrams/graph-triage-router.mmd](diagrams/graph-triage-router.mmd)</sub>

### State

| Field | Type |
| --- | --- |
| `message` | `EmailMessage` |
| `source` | `Literal` |
| `preferences` | `str` |
| `learned_rules` | `dict` |

### Nodes

| Node | What it does | Model call |
| --- | --- | --- |
| `check_source` | A category set by hand in the UI skips everything and goes to `save`, after a `manual_user_input` trace line. | no |
| `pre_triage` | Already replied (a later message of yours in the thread) becomes `user_reply_complete`; a sender on the keep list always goes to the model; one of your `PRE_TRIAGE_IGNORE_LABELS`, a muted thread, or a sender on the pre-triage ignore list becomes `ignore` (Gmail's Promotions, Social, and Forums tabs are not used as decisions); an automated sender (no-reply, notification, alert, receipt, mailer-daemon) that no learned rule names becomes `notify` (rule `automated_sender`). Any of these skips to `save`. | no |
| `recall` | Loads the preferences block (base rules from code plus learned rules). | no |
| `triage` | Asks the configured model for category, reason, and the rule applied; downgrades a reply category that no learned rule supports to `notify`. On failure the email is stored `pending`. | yes |
| `save` | Writes the email to SQLite. | no |
| `remember` | Puts the sender of a sender-stable `ignore` on the pre-triage ignore list; nothing else is kept. | no |
| `inbox_manager` | For `auto_schedule` and `auto_draft`, runs the inbox manager graph below. | via manager |

## Inbox manager

`agents/__inbox_manager_agent__.py`. Runs from the router's `inbox_manager` node. `manage` calls the model with only
the tools its category allows; each tool is its own node. At most 6 model calls.

![graph-inbox-manager](images/graph-inbox-manager.svg)

<sub>Source: [diagrams/graph-inbox-manager.mmd](diagrams/graph-inbox-manager.mmd)</sub>

### Tools by category

| Category | Tools |
| --- | --- |
| `auto_schedule` | `get_thread`, `search_threads`, `now`, `invite_details`, `find_calendar_events`, `create_reminder`, `respond_to_invite` |
| `auto_draft` | `get_thread`, `search_threads`, `now`, `save_draft` |

`unknown_tool` answers calls to tools that do not exist or are not allowed for the category; `repeat` answers a call
identical to an earlier one without running it again.

### State

| Field | Type |
| --- | --- |
| `messages` | `ForwardRef('Annotated[list[AnyMessage], add_messages]', module='langgraph.graph.message')` |
| `message` | `EmailMessage` |
| `memory` | `str` |
| `rounds` | `int` |
| `allowed` | `list` |

## Inbox report

`agents/__inbox_report_agent__.py`. Runs at startup, every `REPORT_INTERVAL_SECONDS`, and on Rebuild from the Home tab.
`gather` builds the snapshot from stored mail, the Sent folder, and the calendar with no model call, and the graph
ends there when nothing changed since the last build; `write` is one structured model call, retried once, whose result
is rendered to markdown in code.

![graph-inbox-report](images/graph-inbox-report.svg)

<sub>Source: [diagrams/graph-inbox-report.mmd](diagrams/graph-inbox-report.mmd)</sub>

### State

| Field | Type |
| --- | --- |
| `force` | `bool` (Rebuild from the Home tab) |
| `snapshot` | `dict` (counts, lists, candidate bodies, previous ids, fingerprint) |
| `overview` | `Overview \| None` (None when the build was skipped as unchanged) |
