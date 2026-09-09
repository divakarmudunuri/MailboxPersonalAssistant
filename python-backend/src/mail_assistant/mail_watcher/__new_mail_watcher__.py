"""Watches the inbox over IMAP IDLE; each new email is downloaded and stored as `pending`. The triage cron picks it up
from the database (`cron_job/__triage_cron__.py`), so a slow model never holds up the mailbox cursor."""

import json
import logging
import time

from mail_assistant.config.__app_config__ import STATE_FILE, configure_logging
from mail_assistant.db import __email_store__ as email_store
from mail_assistant.gmail_client import GmailImapClient

log = logging.getLogger(__name__)
RETRY_SECONDS = 15


class NewMailWatcher:
    """Blocks on IMAP IDLE; every UID that appears after the saved cursor is fetched and stored."""

    def __init__(self, client: GmailImapClient) -> None:
        self.client = client
        # The cursor survives restarts so mail that arrived while the app was down is still stored.
        self.cursor = json.loads(STATE_FILE.read_text()).get("cursor") if STATE_FILE.exists() else None

    def run_once(self) -> None:
        """Wait for the next new mail, store everything that arrived, and persist the cursor after each message."""
        uids, cursor = self.client.wait_for_new_mail(self.cursor)
        validity = cursor.split(":")[0]
        for uid in uids:
            message = self.client.get_message(uid)
            if message is not None:
                email_store.save(message)  # category `pending`, empty reason: what the triage cron looks for
                log.info("Stored %s from %s: %r", message.id, message.sender, message.subject)
            self.cursor = f"{validity}:{uid}"  # a restart mid-batch resumes here instead of re-storing the batch
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


if __name__ == "__main__":
    configure_logging()
    NewMailWatcher(GmailImapClient()).run_forever()
