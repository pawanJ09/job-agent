"""
Entry point for the container (see Dockerfile CMD). Runs the full pipeline
once a day on a schedule: alert parser -> job fetcher -> matcher -> drafter
-> mailer.

Logging: every print() from each stage module gets captured into a
persistent, rotating log file under /app/logs (the mounted volume), in
addition to normal stdout -- so logs survive container restarts and don't
rely on `docker logs` history alone.

Error isolation: if one stage raises an exception, it's logged and the
pipeline moves on to the next stage rather than crashing the whole run.
Stages are naturally resilient to a prior stage failing outright -- e.g. if
the alert parser fails, the fetcher just finds nothing pending and does
nothing, rather than erroring.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

LOG_DIR = Path("/app/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(LOG_DIR / "pipeline.log", maxBytes=5 * 1024 * 1024, backupCount=5),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("job_agent")


class _StreamToLogger:
    """Redirects writes (e.g. from the print() calls in each stage module)
    into the logger, so existing stage code didn't need to be rewritten to
    use logging directly -- it all ends up in the same rotating log file."""

    def __init__(self, target_logger, level):
        self.logger = target_logger
        self.level = level

    def write(self, message):
        message = message.strip()
        if message:
            self.logger.log(self.level, message)

    def flush(self):
        pass


sys.stdout = _StreamToLogger(logger, logging.INFO)
sys.stderr = _StreamToLogger(logger, logging.ERROR)

# Imports happen after the stdout/stderr redirect so that any print()
# statements run at import time (there shouldn't be any, but just in case)
# are captured too.
from db.connection import init_db  # noqa: E402
from gmail.alert_parser import run as run_alert_parser  # noqa: E402
from fetcher.job_fetcher import run as run_job_fetcher  # noqa: E402
from matcher.matcher import run as run_matcher  # noqa: E402
from drafter.drafter import run as run_drafter  # noqa: E402
from mailer.digest_mailer import run as run_mailer  # noqa: E402


def run_fetcher_stage() -> None:
    run_job_fetcher(
        min_delay=float(os.environ.get("FETCH_DELAY_MIN_SECONDS", "10")),
        max_delay=float(os.environ.get("FETCH_DELAY_MAX_SECONDS", "30")),
    )


def run_matcher_stage() -> None:
    run_matcher(threshold=float(os.environ.get("MATCH_THRESHOLD", "0.75")))


STAGES = [
    ("alert_parser", run_alert_parser),
    ("job_fetcher", run_fetcher_stage),
    ("matcher", run_matcher_stage),
    ("drafter", run_drafter),
    ("mailer", run_mailer),
]


def run_pipeline() -> None:
    logger.info("=== Pipeline run started ===")
    for name, stage_fn in STAGES:
        logger.info(f"--- Starting stage: {name} ---")
        try:
            stage_fn()
        except Exception:
            logger.exception(f"Stage '{name}' failed; continuing to next stage.")
        else:
            logger.info(f"--- Finished stage: {name} ---")
    logger.info("=== Pipeline run complete ===")


def main() -> None:
    init_db()

    run_mode = os.environ.get("RUN_MODE", "schedule")
    if run_mode == "once":
        # One-off full pipeline run, for testing -- exits after completion
        # instead of starting the scheduler.
        #   docker compose run --rm -e RUN_MODE=once app python main.py
        run_pipeline()
        return

    hour = int(os.environ.get("SCHEDULE_HOUR", "8"))
    minute = int(os.environ.get("SCHEDULE_MINUTE", "0"))

    grace_hours = float(os.environ.get("CATCHUP_GRACE_HOURS", "12"))

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_pipeline,
        CronTrigger(hour=hour, minute=minute),
        misfire_grace_time=int(grace_hours * 3600),  # still run if this late
        coalesce=True,  # several missed runs collapse into one
    )
    logger.info(
        f"Scheduler started. Pipeline will run daily at {hour:02d}:{minute:02d}, "
        f"with a {grace_hours:g}-hour catch-up window if the machine was asleep."
    )
    scheduler.start()


if __name__ == "__main__":
    main()
