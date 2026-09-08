"""Watches the inbox over IMAP IDLE and runs the triage graph on each new email the moment it arrives."""

import json
import logging
import time
from collections.abc import Callable

from mail_assistant.agents.__email_triage_router_agent__ import triage_new_email
from mail_assistant.config.__app_config__ import STATE_FILE, configure_logging
from mail_assistant.gmail_client import GmailImapClient
from mail_assistant.models.__email_message_model__ import EmailMessage

log = logging.getLogger(__name__)
RETRY_SECONDS = 15


class NewMailWatcher:
    """Blocks on IMAP IDLE; every UID that appears after the saved cursor is fetched and handed to `handler`."""

    def __init__(self, client: GmailImapClient, handler: Callable[[EmailMessage], None]) -> None:
        self.client = client
        self.handler = handler
        # The cursor survives restarts so mail that arrived while the app was down is still triaged.
        self.cursor = json.loads(STATE_FILE.read_text()).get("cursor") if STATE_FILE.exists() else None

    def run_once(self) -> None:
        """Wait for the next new mail, triage everything that arrived, and persist the cursor after each message."""
        uids, cursor = self.client.wait_for_new_mail(self.cursor)
        validity = cursor.split(":")[0]
        for uid in uids:
            message = self.client.get_message(uid)
            if message is not None:
                self.handler(message)
            self.cursor = f"{validity}:{uid}"  # a restart mid-batch resumes here instead of re-triaging the batch
            STATE_FILE.write_text(json.dumps({"cursor": self.cursor}))
        self.cursor = cursor
        STATE_FILE.write_text(json.dumps({"cursor": self.cursor}))

    def run_forever(self) -> None:
        """Keep watching; on any error log it, pause briefly, and reconnect by trying again."""
        while True:
            try:
                self.run_once()
            except Exception:
                log.exception("Mail watch failed; retrying in %ss", RETRY_SECONDS)
                time.sleep(RETRY_SECONDS)


def handle_new_email(message: EmailMessage) -> None:
    """Triage the message; the graph stores it and routes it onward."""
    triage_new_email(message)


if __name__ == "__main__":
    configure_logging()
    NewMailWatcher(GmailImapClient(), handle_new_email).run_forever()
