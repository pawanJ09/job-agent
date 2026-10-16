"""
Entry point for the container (see Dockerfile CMD). Runs the full pipeline
once a day on a schedule: alert parser -> job fetcher -> matcher -> drafter
-> mailer.

Logging: every print() from each stage module gets captured into a
persistent, rotating log file under /app/logs (the mounted volume), in
addition to normal stdout -- so logs survive container restarts and don't
rely on `docker logs` history alone.

Resume: at the start of every run, the resume is re-parsed if the parsed copy
(resume_data.json) is missing or older than the resume file, so replacing your
resume file is enough -- the matcher's embedding cache refreshes itself when the
parsed text changes.

Error isolation: if one stage raises an exception, it's logged and the
pipeline moves on to the next stage rather than crashing the whole run.
Stages are naturally resilient to a prior stage failing outright -- e.g. if
the alert parser fails, the fetcher just finds nothing pending and does
nothing, rather than erroring.
"""

import logging
import os
import sys
import time
from datetime import date, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

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
from parser.alert_parser import run as run_alert_parser  # noqa: E402
from fetcher.job_fetcher import run as run_job_fetcher  # noqa: E402
from matcher.matcher import run as run_matcher  # noqa: E402
from drafter.drafter import run as run_drafter  # noqa: E402
from mailer.digest_mailer import run as run_mailer  # noqa: E402
from resume.parser import (  # noqa: E402
    OUTPUT_PATH as PARSED_RESUME_PATH,
    parse_resume,
    save_resume_data,
)


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


def ensure_resume_parsed() -> None:
    """
    Re-parses the resume if the parsed copy is missing or older than the resume
    file. Raises if there is no usable resume at all, or if no text can be
    extracted (the existing parsed copy is then left untouched).
    """
    resume_path = Path(os.environ.get("RESUME_PATH", "/app/data/resume.pdf"))

    if not resume_path.exists():
        if PARSED_RESUME_PATH.exists():
            logger.warning(
                f"Resume file not found at {resume_path}; using the existing parsed resume."
            )
            return
        raise FileNotFoundError(
            f"No resume at {resume_path} and no parsed resume exists. "
            f"Add your resume file and check RESUME_PATH in .env."
        )

    if (
        PARSED_RESUME_PATH.exists()
        and PARSED_RESUME_PATH.stat().st_mtime >= resume_path.stat().st_mtime
    ):
        logger.info("Parsed resume is up to date.")
        return

    logger.info("Resume is new or changed since it was last parsed. Parsing it now.")
    data = parse_resume(str(resume_path))
    if not data["raw_text"].strip():
        raise ValueError(
            f"No text could be extracted from {resume_path}. A scanned/image-only PDF "
            f"is a likely cause; re-export it as a text-based PDF or DOCX."
        )
    save_resume_data(data)


def run_pipeline() -> None:
    logger.info("=== Pipeline run started ===")
    try:
        ensure_resume_parsed()
    except Exception:
        logger.exception("Resume parsing failed; continuing with the existing parsed resume, if any.")
    for name, stage_fn in STAGES:
        logger.info(f"--- Starting stage: {name} ---")
        try:
            stage_fn()
        except Exception:
            logger.exception(f"Stage '{name}' failed; continuing to next stage.")
        else:
            logger.info(f"--- Finished stage: {name} ---")
    logger.info("=== Pipeline run complete ===")


# Remembers the date of the last run, in the mounted data folder so it survives
# container restarts and recreation.
LAST_RUN_FILE = Path("/app/data/last_run.txt")
POLL_SECONDS = 60


def _last_run_date() -> date | None:
    try:
        return date.fromisoformat(LAST_RUN_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _record_run(run_date: date) -> None:
    LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(run_date.isoformat())


def _is_due(now: datetime, hour: int, minute: int, last_run: date | None) -> bool:
    """True once today's scheduled time has passed and today's run hasn't happened."""
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return now >= scheduled and last_run != now.date()


PLACEHOLDERS = {
    "you@gmail.com",
    "your_16_char_app_password",
    "your_openai_api_key_here",
    "change_me",
}

# Settings the code cannot run without. None of them has a default.
REQUIRED_SETTINGS = [
    "DATABASE_URL",
    "GMAIL_USER",
    "GMAIL_APP_PASSWORD",
    "OPENAI_API_KEY",
    "DIGEST_RECIPIENT",
    "SMTP_HOST",
    "SMTP_PORT",
]


def _config_problems() -> list[str]:
    """Returns a plain-language list of everything wrong with the configuration."""
    problems: list[str] = []

    for name in REQUIRED_SETTINGS:
        value = os.environ.get(name, "").strip()
        if not value:
            problems.append(f"{name} is not set.")
        elif value in PLACEHOLDERS:
            problems.append(f"{name} still has the placeholder value from .env.example.")

    db_password = os.environ.get("POSTGRES_PASSWORD", "")
    if db_password == "change_me":
        problems.append("POSTGRES_PASSWORD still has the placeholder value from .env.example.")
    elif any(c in db_password for c in "@:/?#%") or any(c.isspace() for c in db_password):
        problems.append(
            "POSTGRES_PASSWORD contains a character that breaks the database connection "
            "(one of @ : / ? # % or a space). Use letters and numbers only."
        )

    def number(name: str, cast, low: float, high: float, label: str) -> None:
        raw = os.environ.get(name)
        if not raw:
            return
        try:
            value = cast(raw)
        except ValueError:
            problems.append(f"{name} must be {label}, but it is '{raw}'.")
            return
        if not low <= value <= high:
            problems.append(f"{name} must be {label}, but it is '{raw}'.")

    number("MATCH_THRESHOLD", float, 0, 1, "a number between 0 and 1")
    number("SCHEDULE_HOUR", int, 0, 23, "a whole number from 0 to 23")
    number("SCHEDULE_MINUTE", int, 0, 59, "a whole number from 0 to 59")
    number("ALERT_LOOKBACK_DAYS", int, 1, 60, "a whole number from 1 to 60")
    number("FETCH_DELAY_MIN_SECONDS", float, 0, 600, "a number of seconds from 0 to 600")
    number("FETCH_DELAY_MAX_SECONDS", float, 0, 600, "a number of seconds from 0 to 600")
    number("SMTP_PORT", int, 1, 65535, "a port number")

    timezone_name = os.environ.get("SCHEDULE_TIMEZONE") or "UTC"
    try:
        ZoneInfo(timezone_name)
    except Exception:
        problems.append(
            f"SCHEDULE_TIMEZONE '{timezone_name}' is not a valid timezone name. "
            f"Use a name like America/New_York or Europe/London."
        )

    resume_path = Path(os.environ.get("RESUME_PATH", "/app/data/resume.pdf"))
    if not resume_path.exists() and not PARSED_RESUME_PATH.exists():
        problems.append(
            f"No resume found at {resume_path}. Add your resume file and check RESUME_PATH."
        )

    return problems


def check_config() -> None:
    """Stops with a clear message if anything in the configuration is missing or wrong."""
    problems = _config_problems()
    if problems:
        logger.error("The app can't start because of problems in your configuration:")
        for problem in problems:
            logger.error(f"  - {problem}")
        logger.error(
            "Fix them in your .env file, then run: docker compose up -d --force-recreate app"
        )
        sys.exit(1)

    if not os.environ.get("SCHEDULE_TIMEZONE"):
        logger.warning(
            "SCHEDULE_TIMEZONE is not set, so the schedule uses UTC. "
            "Set it in .env if you are elsewhere."
        )


def main() -> None:
    check_config()
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
    # IANA timezone name (e.g. Europe/London). Without this, the hour above
    # would be read in the container's clock, which defaults to UTC.
    tz_name = os.environ.get("SCHEDULE_TIMEZONE") or "UTC"
    tz = ZoneInfo(tz_name)

    logger.info(
        f"Scheduler started. Pipeline runs daily at {hour:02d}:{minute:02d} {tz_name}. "
        f"The clock is checked every {POLL_SECONDS}s, so a missed run (machine asleep, "
        f"Docker restarted) starts as soon as the container is running again."
    )
    logger.info(f"Last recorded run: {_last_run_date() or 'never'}")

    while True:
        now = datetime.now(tz)
        if _is_due(now, hour, minute, _last_run_date()):
            logger.info(
                f"Today's run is due (scheduled {hour:02d}:{minute:02d}, now {now:%H:%M}). Starting."
            )
            try:
                run_pipeline()
            except Exception:
                logger.exception("Pipeline run failed unexpectedly.")
            # Record the date even after an unexpected failure, so a persistent
            # error doesn't make the pipeline re-run every minute.
            _record_run(now.date())
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
