"""Sends stored but untriaged emails to the triage agent: every TRIAGE_INTERVAL_SECONDS, oldest first."""

import logging
import time

from mail_assistant.agents.__email_triage_router_agent__ import triage_new_email
from mail_assistant.config.__app_config__ import TRIAGE_INTERVAL_SECONDS, configure_logging
from mail_assistant.db import __email_store__ as email_store

log = logging.getLogger(__name__)


class TriageRunner:
    """Drains the `pending` rows the mail watcher stored by running the triage graph on each."""

    def run_once(self) -> int:
        """Triage every untriaged email in the database, oldest first; how many were handled."""
        untriaged = email_store.untriaged()
        for message in untriaged:
            triage_new_email(message)
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
