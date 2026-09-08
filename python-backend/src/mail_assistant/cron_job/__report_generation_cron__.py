"""Builds the inbox briefing on a schedule: once at start, then every REPORT_INTERVAL_SECONDS."""

import logging
import time

from mail_assistant.agents import __inbox_report_agent__ as inbox_report
from mail_assistant.config.__app_config__ import REPORT_INTERVAL_SECONDS, configure_logging

log = logging.getLogger(__name__)


class ReportGenerator:
    """Writes a fresh briefing to REPORT_FILE on an interval; the Home tab reads that file."""

    def run_once(self) -> None:
        """Build one briefing and save it."""
        report = inbox_report.generate()
        log.info("Inbox briefing built: %d rounds, %d tool calls", report["rounds"], report["tool_calls"])

    def run_forever(self) -> None:
        """Build now, then every REPORT_INTERVAL_SECONDS; log and keep going on errors."""
        while True:
            try:
                self.run_once()
            except Exception:
                log.exception("Inbox briefing failed")
            time.sleep(REPORT_INTERVAL_SECONDS)


if __name__ == "__main__":
    configure_logging()
    ReportGenerator().run_forever()
