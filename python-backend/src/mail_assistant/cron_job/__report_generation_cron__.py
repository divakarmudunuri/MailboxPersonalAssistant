"""Builds the Quick Overview on a schedule: once at start, then every REPORT_INTERVAL_SECONDS (skipped when nothing
changed since the last build)."""

import logging
import time

from mail_assistant.agents import __inbox_report_agent__ as inbox_report
from mail_assistant.config.__app_config__ import REPORT_INTERVAL_SECONDS, configure_logging

log = logging.getLogger(__name__)


class ReportGenerator:
    """Writes a fresh overview to REPORT_FILE on an interval; the Home tab reads that file."""

    def run_once(self) -> None:
        """Build one overview and save it."""
        report = inbox_report.generate()
        log.info("Quick Overview ready: %s", report["counts"])

    def run_forever(self) -> None:
        """Build now, then every REPORT_INTERVAL_SECONDS; log and keep going on errors."""
        while True:
            try:
                self.run_once()
            except Exception:
                log.exception("Quick Overview failed")
            time.sleep(REPORT_INTERVAL_SECONDS)


if __name__ == "__main__":
    configure_logging()
    ReportGenerator().run_forever()
