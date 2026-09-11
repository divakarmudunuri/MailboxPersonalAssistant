# Documentation

Mailbox Personal Assistant: a Gmail assistant that triages every new email with a language model guided by long-term
memory, acts on some of them, and writes a start-of-day Quick Overview. Diagrams are embedded as SVG images rendered from the
Mermaid sources in `diagrams/`, so they show in any Markdown viewer.

| Page | What it covers |
| --- | --- |
| [google-setup.md](google-setup.md) | Google Cloud project, the OAuth consent screen and Desktop client, enabling IMAP and the Calendar API, granting access with `mail-assistant-auth`, troubleshooting |
| [architecture.md](architecture.md) | Components, the process model, the three agents, long-term memory, categories and rules, repository layout |
| [sequences.md](sequences.md) | Sequence diagrams: a new email, the inbox manager acting, a manual save, teaching a preference, building the Quick Overview, startup and authentication |
| [state-graphs.md](state-graphs.md) | The three LangGraph state graphs as drawn by LangGraph, with their state schemas and node tables |
| [data.md](data.md) | The entities, every persisted file, the `applied_rule` and `action` vocabularies, and the settings that matter most |
| [run-stats-2026-09-11.md](run-stats-2026-09-11.md) | Measured statistics of a full 30-day backfill run: volume, wall-clock, per-step and per-email times |

Running and configuring the app is described in [`../python-backend/README.md`](../python-backend/README.md);
conventions for working on the code are in [`../CLAUDE.md`](../CLAUDE.md).

To update a diagram, edit its source in `diagrams/` and re-render the images with `docs/render_images.sh`. It uses the
Mermaid CLI through `npx`, which downloads it on first use. The Graph tab in the UI always shows the live agent graphs.
