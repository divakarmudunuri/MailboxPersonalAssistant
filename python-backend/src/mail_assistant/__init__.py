"""Entry point for `uv run mail-assistant`: starts the mail watcher, the triage cron, and the report cron, then serves
the API and UI."""

import logging
import threading

# Imports of the app's own modules live inside the functions below. Every `mail_assistant.*` import runs this
# file first, so importing submodules here would create a circular import through the package itself.
log = logging.getLogger(__name__)


def _run_mail_watcher() -> None:
    """Watch the inbox over IMAP IDLE forever, storing new mail; if it cannot even start, log it and keep the API up."""
    from mail_assistant.gmail_client import GmailImapClient
    from mail_assistant.mail_watcher.__new_mail_watcher__ import NewMailWatcher

    try:
        NewMailWatcher(GmailImapClient()).run_forever()
    except Exception:
        log.exception("Mail watcher stopped")


def _run_triage_cron() -> None:
    """Triage stored mail every TRIAGE_INTERVAL_SECONDS; if it cannot start, log it and keep the API up."""
    from mail_assistant.cron_job.__triage_cron__ import TriageRunner

    try:
        TriageRunner().run_forever()
    except Exception:
        log.exception("Triage cron stopped")


def _run_report_cron() -> None:
    """Build the briefing now and every REPORT_INTERVAL_SECONDS; if it cannot start, log it and keep the API up."""
    from mail_assistant.cron_job.__report_generation_cron__ import ReportGenerator

    try:
        ReportGenerator().run_forever()
    except Exception:
        log.exception("Report cron stopped")


def _run_api_server() -> None:
    """Serve the API and the built UI on API_PORT; blocks until the server stops."""
    import uvicorn

    from mail_assistant.config.__app_config__ import API_PORT

    uvicorn.run("mail_assistant.api.__app__:app", host="127.0.0.1", port=API_PORT)


def main() -> None:
    from mail_assistant.config import __app_config__ as cfg

    cfg.configure_logging()
    for agent in ("TRIAGE", "MANAGER", "MEMORY_CHAT", "REPORT"):
        provider, model = getattr(cfg, f"{agent}_LLM")
        log.info("%s model: %s %s", agent.lower(), provider, model or "(provider default)")
    if cfg.LANGSMITH_TRACING:
        log.info("LangSmith tracing on, project %r", cfg.LANGSMITH_PROJECT)
    threading.Thread(target=_run_mail_watcher, name="mail-watcher", daemon=True).start()
    log.info("Mail watcher started")
    threading.Thread(target=_run_triage_cron, name="triage-cron", daemon=True).start()
    log.info("Triage cron started")
    threading.Thread(target=_run_report_cron, name="report-cron", daemon=True).start()
    log.info("Report cron started")
    _run_api_server()
