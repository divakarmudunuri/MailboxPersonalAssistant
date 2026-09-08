"""Loads .env from the backend root and exposes all environment-derived settings."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[3]
load_dotenv(BACKEND_DIR / ".env")

GMAIL_CREDENTIALS_FILE = Path(os.environ.get("GMAIL_CREDENTIALS_FILE", "credentials.json"))
GMAIL_TOKEN_FILE = Path(os.environ.get("GMAIL_TOKEN_FILE", "token.json"))
STATE_FILE = Path(os.environ.get("MAIL_CHECK_STATE_FILE", ".mail_check_state.json"))
MAIL_BACKFILL_DAYS = int(os.environ.get("MAIL_BACKFILL_DAYS", "0"))  # on a fresh start, triage inbox mail this recent
# Your own Gmail labels whose mail pre_triage ignores without a model call, comma separated (e.g. Newsletters,Alerts)
PRE_TRIAGE_IGNORE_LABELS = [x.strip() for x in os.environ.get("PRE_TRIAGE_IGNORE_LABELS", "").split(",") if x.strip()]
REPORT_INTERVAL_SECONDS = float(os.environ.get("REPORT_INTERVAL_SECONDS", str(3 * 3600)))
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")  # the mailbox; required, it is the IMAP login name
LOG_DIR = BACKEND_DIR / "logs"
DB_FILE = Path(os.environ.get("MAIL_DB_FILE", BACKEND_DIR / "mail_assistant.db"))
MEMORY_FILE = Path(os.environ.get("MEMORY_FILE", BACKEND_DIR / "long_term_memory.json"))
TRACE_FILE = Path(os.environ.get("TRACE_FILE", BACKEND_DIR / "traces.jsonl"))
REPORT_FILE = Path(os.environ.get("REPORT_FILE", BACKEND_DIR / "inbox_report.json"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()  # ollama | anthropic | openai
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))  # Ollama defaults to 4096 and silently truncates
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-nano")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
REPORT_LLM_PROVIDER = os.environ.get("REPORT_LLM_PROVIDER", "ollama").lower()  # the briefing can use its own model
REPORT_MODEL = os.environ.get("REPORT_MODEL", "gemma4:12b")
API_PORT = int(os.environ.get("API_PORT", "8000"))
UI_DIST_DIR = BACKEND_DIR.parent / "react-frontend" / "dist"


def configure_logging() -> None:
    """Send all logs to logs/mail_assistant.log and the console at LOG_LEVEL."""
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_DIR / "mail_assistant.log"), logging.StreamHandler()],
    )
