"""Sends stored but untriaged emails to the triage agent: every TRIAGE_INTERVAL_SECONDS, oldest first, up to
TRIAGE_WORKERS at a time. Each worker thread keeps its own IMAP and calendar clients (they are not thread-safe)."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from functools import cache

from mail_assistant.agents.__email_triage_router_agent__ import triage_new_email
from mail_assistant.config.__app_config__ import TRIAGE_INTERVAL_SECONDS, TRIAGE_WORKERS, configure_logging
from mail_assistant.db import __email_store__ as email_store
from mail_assistant.gmail_client import GmailImapClient

log = logging.getLogger(__name__)


@cache
def _gmail() -> GmailImapClient:
    """One mailbox client for the batch reply check, created on first use."""
    return GmailImapClient()


def _safely(message, sent) -> None:
    """Run one email through the graph; a failure is logged and must not take the pass down."""
    try:
        triage_new_email(message, sent=sent)
    except Exception:
        log.exception("Triage failed for %s", message.id)
        email_store.note_failed_attempt(message.id)


class TriageRunner:
    """Drains the `pending` rows the mail watcher stored by running the triage graph on each."""

    def __init__(self) -> None:
        self.pool = ThreadPoolExecutor(max_workers=max(1, TRIAGE_WORKERS), thread_name_prefix="triage")

    def run_once(self) -> int:
        """Triage every untriaged email in the database, oldest first and up to TRIAGE_WORKERS at a time; how many."""
        untriaged = email_store.untriaged()
        if not untriaged:
            return 0
        sent = _gmail().sent_threads()  # one Sent-folder search answers the reply check for the whole pass
        list(self.pool.map(lambda m: _safely(m, sent), untriaged))  # each worker logs its own failure; wait for all
        return len(untriaged)

    def run_forever(self) -> None:
        """Check for untriaged mail every TRIAGE_INTERVAL_SECONDS; log and keep going on errors."""
        while True:
            try:
                if handled := self.run_once():
                    log.info("Triaged %d stored email(s)", handled)
            except Exception:
                log.exception("Triage pass failed")
            time.sleep(TRIAGE_INTERVAL_SECONDS)


if __name__ == "__main__":
    configure_logging()
    TriageRunner().run_forever()
