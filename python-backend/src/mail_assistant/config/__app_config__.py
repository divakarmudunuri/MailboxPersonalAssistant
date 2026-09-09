"""Loads .env from the backend root and exposes every setting; file locations are fixed under the backend folder."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[3]
load_dotenv(BACKEND_DIR / ".env")

SECRETS_DIR = BACKEND_DIR / ".secrets"  # OAuth client secrets and the cached token
DATA_DIR = BACKEND_DIR / "data"  # everything the app writes, except logs
LOG_DIR = BACKEND_DIR / "logs"
for _dir in (SECRETS_DIR, DATA_DIR):
    _dir.mkdir(exist_ok=True)
GMAIL_CREDENTIALS_FILE = SECRETS_DIR / "credentials.json"
GMAIL_TOKEN_FILE = SECRETS_DIR / "token.json"
STATE_FILE = DATA_DIR / "mail_check_state.json"  # the watcher's cursor; delete it to start over
DB_FILE = DATA_DIR / "mail_assistant.db"
MEMORY_FILE = DATA_DIR / "long_term_memory.json"
PRE_TRIAGE_IGNORE_FILE = DATA_DIR / "pre_triage_ignore_list.json"
TRACE_FILE = DATA_DIR / "traces.jsonl"
REPORT_FILE = DATA_DIR / "inbox_report.json"
UI_DIST_DIR = BACKEND_DIR.parent / "react-frontend" / "dist"
API_PORT = 8000

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")  # the mailbox; required, it is the IMAP login name
MAIL_BACKFILL_DAYS = int(os.environ.get("MAIL_BACKFILL_DAYS", "0"))  # on a fresh start, triage inbox mail this recent
# Your own Gmail labels whose mail pre_triage ignores without a model call, comma separated (e.g. Newsletters,Alerts)
PRE_TRIAGE_IGNORE_LABELS = [x.strip() for x in os.environ.get("PRE_TRIAGE_IGNORE_LABELS", "").split(",") if x.strip()]
REPORT_INTERVAL_SECONDS = float(os.environ.get("REPORT_INTERVAL_SECONDS", str(3 * 3600)))
TRIAGE_INTERVAL_SECONDS = float(os.environ.get("TRIAGE_INTERVAL_SECONDS", "30"))  # how often stored mail is triaged

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))  # Ollama defaults to 4096 and silently truncates
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")


def _agent_llm(name: str, default_model: str) -> tuple[str, str]:
    """One agent's (provider, model): <NAME>_LLM_PROVIDER (ollama | anthropic | openai) and <NAME>_MODEL."""
    return os.environ.get(f"{name}_LLM_PROVIDER", "ollama").lower(), os.environ.get(f"{name}_MODEL", default_model)


# Each agent runs on its own provider and model. The defaults are the all-local minimum profile.
TRIAGE_LLM = _agent_llm("TRIAGE", "qwen3:4b")
MEMORY_CHAT_LLM = _agent_llm("MEMORY_CHAT", "qwen3:4b")
MANAGER_LLM = _agent_llm("MANAGER", "qwen3:8b")
REPORT_LLM = _agent_llm("REPORT", "qwen3:8b")

# LangSmith tracing of every graph and model call. The langsmith SDK reads LANGSMITH_TRACING, LANGSMITH_API_KEY, and
# LANGSMITH_PROJECT itself (from .env, loaded above); this flag only drives the startup log line.
LANGSMITH_TRACING = os.environ.get("LANGSMITH_TRACING", "false").lower() == "true"
LANGSMITH_PROJECT = os.environ.get("LANGSMITH_PROJECT", "default")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


def configure_logging() -> None:
    """Send all logs to logs/mail_assistant.log and the console at LOG_LEVEL."""
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_DIR / "mail_assistant.log"), logging.StreamHandler()],
    )
