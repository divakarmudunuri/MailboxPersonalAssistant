import json
import logging
import threading

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from mail_assistant.config.__app_config__ import GMAIL_CREDENTIALS_FILE as CREDENTIALS_FILE
from mail_assistant.config.__app_config__ import GMAIL_TOKEN_FILE as TOKEN_FILE

log = logging.getLogger(__name__)
_lock = threading.Lock()  # several threads open clients at startup; only one may run the consent flow

# Full mailbox access (required for IMAP) plus calendar events (reminders and invitation answers by the inbox manager).
SCOPES = ["https://mail.google.com/", "https://www.googleapis.com/auth/calendar.events"]


def _cached() -> Credentials | None:
    """The token on disk, unless it was granted for narrower scopes than SCOPES (then the consent flow must rerun)."""
    if not TOKEN_FILE.exists():
        return None
    granted = set(json.loads(TOKEN_FILE.read_text()).get("scopes", []))
    if not set(SCOPES) <= granted:
        log.warning("token.json was granted %s but %s is needed; re-running consent", sorted(granted), SCOPES)
        return None
    return Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)


def load_credentials() -> Credentials:
    """Return cached OAuth credentials, refreshing or running the browser consent flow if needed."""
    with _lock:
        creds = _cached()
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES).run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())
        return creds


def main() -> None:
    """`uv run mail-assistant-auth`: discard the saved token and run the consent flow for every scope the app needs."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
        print(f"removed {TOKEN_FILE}")
    print("opening the browser for consent to:", *SCOPES, sep="\n  ")
    creds = load_credentials()
    print("granted:", *(creds.granted_scopes or creds.scopes or []), sep="\n  ")
    print(f"saved {TOKEN_FILE}")
