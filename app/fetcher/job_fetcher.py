"""
For every job with fetch_status = 'pending', fetches the full posting page
using a saved, authenticated session, extracts the description text and the
skills mentioned in it, and updates the row.

Rate-limited deliberately: this makes one HTTP request per pending job, with
a randomized delay between requests, rather than hitting LinkedIn in a tight
loop. See the session-export helper (save_session.py) for how the saved
session this depends on gets created -- that part runs on your own machine,
not inside the container, since it needs an interactive login.

Falls back to the alert email's snippet (already stored) if the fetch or
the description extraction fails, so a bad fetch never leaves a job with
nothing to match against later.
"""

import json
import os
import random
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from db.connection import get_connection
from fetcher.skills import extract_skills

load_dotenv()

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def load_session(storage_state_path: str) -> requests.Session:
    """
    Builds a requests.Session from a Playwright storage_state.json file
    (the same format produced by save_session.py). Only the cookies are
    used here -- a plain HTTP session doesn't need the "origins" data
    Playwright also stores.
    """
    path = Path(storage_state_path)
    if not path.exists():
        raise FileNotFoundError(
            f"No saved session at {path}. Run save_session.py locally first "
            f"(see the README) to create it."
        )

    state = json.loads(path.read_text())
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    for cookie in state.get("cookies", []):
        session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain", ""))
    return session


def fetch_description(session: requests.Session, url: str) -> str | None:
    response = session.get(url, timeout=15)
    if response.status_code != 200:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    # NOTE: LinkedIn's page markup can change. This selector has been a
    # reasonably stable container for the job description, but if
    # full_description keeps coming back empty, inspect a real page
    # (view-source) and update this selector.
    container = soup.select_one(".show-more-less-html__markup") or soup.select_one(
        '[class*="description"]'
    )
    if not container:
        return None

    text = container.get_text("\n", strip=True)
    return text or None


def get_pending_jobs() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT job_id, link, snippet FROM jobs WHERE fetch_status = 'pending'"
            )
            rows = cur.fetchall()
    return [{"job_id": r[0], "link": r[1], "snippet": r[2]} for r in rows]


def update_job(job_id: str, full_description: str | None, skills: list[str], fetch_status: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET full_description = %s, required_skills = %s, fetch_status = %s
                WHERE job_id = %s
                """,
                (full_description, skills, fetch_status, job_id),
            )
        conn.commit()


def run(min_delay: float = 10, max_delay: float = 30) -> None:
    session_path = os.environ.get("LINKEDIN_SESSION_PATH", "/app/data/auth_state.json")
    session = load_session(session_path)

    pending = get_pending_jobs()
    print(f"{len(pending)} job(s) pending fetch.")

    for job in pending:
        time.sleep(random.uniform(min_delay, max_delay))

        try:
            description = fetch_description(session, job["link"])
        except requests.RequestException as e:
            print(f"  [{job['job_id']}] fetch error: {e}")
            description = None

        if description:
            text_for_skills = description
            fetch_status = "fetched"
        else:
            # Fall back to the snippet captured from the alert email, if any,
            # so there's still something for the matcher to work with.
            text_for_skills = job["snippet"] or ""
            fetch_status = "failed"
            print(f"  [{job['job_id']}] no description extracted, falling back to snippet.")

        skills = extract_skills(text_for_skills)
        update_job(job["job_id"], description, skills, fetch_status)
        print(f"  [{job['job_id']}] status={fetch_status}, skills={skills}")


if __name__ == "__main__":
    # Run this directly to test:
    #   docker compose run --rm app python fetcher/job_fetcher.py
    run(
        min_delay=float(os.environ.get("FETCH_DELAY_MIN_SECONDS", "10")),
        max_delay=float(os.environ.get("FETCH_DELAY_MAX_SECONDS", "30")),
    )
