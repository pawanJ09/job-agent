"""
For every job with fetch_status = 'pending', fetches the posting's description
from LinkedIn's lightweight job-posting endpoint, extracts the skills mentioned
in it, and updates the row.

The full job page can't be used: its data sits in a large script blob with no
readable description markup. The lightweight endpoint returns the description as
a small server-rendered fragment instead.

Each job is fetched anonymously first (no login cookies sent). Only if that fails
and a saved session file exists (created by save_session.py) is the request
retried with that session. If neither works, the alert email's snippet is used
so a failed fetch never leaves a job with nothing to match against.

Rate-limited deliberately: one request per pending job, with a randomized delay
between jobs, rather than hitting LinkedIn in a tight loop.
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
POSTING_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"


def new_anonymous_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def try_load_session(storage_state_path: str) -> requests.Session | None:
    """
    Builds a session from a Playwright storage_state.json (produced by
    save_session.py), or returns None if the file doesn't exist. Only used as a
    fallback when an anonymous fetch fails.
    """
    path = Path(storage_state_path)
    if not path.exists():
        return None
    state = json.loads(path.read_text())
    session = new_anonymous_session()
    for cookie in state.get("cookies", []):
        session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain", ""))
    return session


def fetch_description(session: requests.Session, job_id: str) -> tuple[str | None, str]:
    """Returns (description_text, reason). description_text is None on failure."""
    try:
        response = session.get(POSTING_URL.format(job_id=job_id), timeout=15)
    except requests.RequestException as e:
        return None, f"request error: {e}"

    if response.status_code != 200:
        return None, f"HTTP {response.status_code}"

    soup = BeautifulSoup(response.text, "html.parser")
    container = soup.select_one(".show-more-less-html__markup")
    if not container:
        return None, "description container not found"

    text = container.get_text("\n", strip=True)
    if not text:
        return None, "description empty"
    return text, "ok"


def fetch_with_fallback(
    anonymous: requests.Session, authenticated: requests.Session | None, job_id: str
) -> tuple[str | None, str]:
    """Returns (description_text, how). 'how' says which path worked, or why none did."""
    text, reason = fetch_description(anonymous, job_id)
    if text:
        return text, "anonymous"

    if authenticated is not None:
        text, session_reason = fetch_description(authenticated, job_id)
        if text:
            return text, "session fallback"
        return None, f"anonymous: {reason}; session: {session_reason}"

    return None, f"anonymous: {reason}"


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
    anonymous = new_anonymous_session()
    authenticated = try_load_session(
        os.environ.get("LINKEDIN_SESSION_PATH", "/app/data/auth_state.json")
    )
    print(f"Saved session available as fallback: {authenticated is not None}")

    pending = get_pending_jobs()
    print(f"{len(pending)} job(s) pending fetch.")

    for job in pending:
        time.sleep(random.uniform(min_delay, max_delay))

        description, how = fetch_with_fallback(anonymous, authenticated, job["job_id"])

        if description:
            text_for_skills = description
            fetch_status = "fetched"
        else:
            # Fall back to the snippet captured from the alert email, if any,
            # so there's still something for the matcher to work with.
            text_for_skills = job["snippet"] or ""
            fetch_status = "failed"
            print(f"  [{job['job_id']}] fetch failed ({how}); falling back to snippet.")

        skills = extract_skills(text_for_skills)
        update_job(job["job_id"], description, skills, fetch_status)
        if description:
            print(f"  [{job['job_id']}] fetched via {how} ({len(description)} chars), skills={skills}")
        else:
            print(f"  [{job['job_id']}] status={fetch_status}, skills={skills}")


if __name__ == "__main__":
    # Run this directly to test:
    #   docker compose run --rm app python fetcher/job_fetcher.py
    run(
        min_delay=float(os.environ.get("FETCH_DELAY_MIN_SECONDS", "10")),
        max_delay=float(os.environ.get("FETCH_DELAY_MAX_SECONDS", "30")),
    )
