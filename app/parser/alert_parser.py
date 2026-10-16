"""
Connects to Gmail over IMAP, pulls recent LinkedIn job alert emails from a
labeled folder, extracts job postings (title, company, location, link,
snippet), and inserts new ones into the jobs table.

Deliberately does NOT rely on the \\Seen (read/unread) flag to decide what's
"already processed" -- if you open an alert email yourself before the agent
runs, an unread-only search would silently skip it. Instead this searches a
rolling date window (ALERT_LOOKBACK_DAYS, default 2) every run, and leans on
job_id deduplication in the database to make re-scanning the same emails
safe and cheap: a posting already in the table is just skipped, not
duplicated.
"""

import email
import imaplib
import os
import re
from datetime import datetime, timedelta
from email.message import Message
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv

from db.connection import get_connection

load_dotenv()

RAW_EMAIL_DEBUG_DIR = Path("/app/data/raw_emails")
RAW_EMAIL_DEBUG_LIMIT = 5  # save at most this many raw emails for inspection


def _get_html_body(msg: Message) -> str | None:
    """Walk a (possibly multipart) email and return its HTML body, if any."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace")
        return None
    if msg.get_content_type() == "text/html":
        charset = msg.get_content_charset() or "utf-8"
        return msg.get_payload(decode=True).decode(charset, errors="replace")
    return None


def _save_raw_email_for_debugging(raw_bytes: bytes, index: int) -> None:
    """
    Dumps the first few raw alert emails to disk so you can open them and
    see LinkedIn's actual current markup. Useful once, then safe to ignore
    (or delete the files) once _parse_job_links below is tuned correctly.
    """
    if index >= RAW_EMAIL_DEBUG_LIMIT:
        return
    RAW_EMAIL_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_EMAIL_DEBUG_DIR / f"alert_{index}.eml"
    out_path.write_bytes(raw_bytes)


def _parse_job_links(html: str) -> list[dict]:
    """
    Extracts job postings from a LinkedIn alert email's HTML body.

    Each job appears as several links to the same posting: an image link with
    no text, a full "card" link whose text holds title, "company · location"
    and salary as separate pieces, and a link containing only the title. Links
    are grouped per job id. The title comes from the shortest text, and
    company/location from the card link's "company · location" piece.

    NOTE: LinkedIn's email markup can change without notice. If postings come
    through with missing fields, compare against the raw .eml files saved in
    /app/data/raw_emails.
    """
    soup = BeautifulSoup(html, "html.parser")
    button_labels = {"view job", "view", "apply", "easy apply", "see job"}

    texts_by_job: dict[str, list[list[str]]] = {}
    for anchor in soup.select('a[href*="/jobs/view/"]'):
        job_id = job_id_from_link(anchor["href"].split("?")[0])
        parts = [p.strip() for p in anchor.get_text("\n", strip=True).split("\n") if p.strip()]
        if not parts or " ".join(parts).lower() in button_labels:
            continue  # image-only link or a "View job" button
        texts_by_job.setdefault(job_id, []).append(parts)

    jobs = []
    for job_id, candidates in texts_by_job.items():
        card_parts = max(candidates, key=lambda p: len(" ".join(p)))
        if len(candidates) == 1:
            title_parts = card_parts[:1]  # only the card link exists: first piece is the title
        else:
            title_parts = min(candidates, key=lambda p: len(" ".join(p)))

        company, location = None, None
        for part in card_parts:
            if "\u00b7" in part:
                left, _, right = part.partition("\u00b7")
                company, location = left.strip() or None, right.strip() or None
                break

        jobs.append({
            "title": " ".join(title_parts),
            "link": f"https://www.linkedin.com/jobs/view/{job_id}",
            "company": company,
            "location": location,
            "snippet": None,  # alert emails don't include a real snippet
        })

    return jobs


def job_id_from_link(link: str) -> str:
    match = re.search(r"/jobs/view/(\d+)", link)
    return match.group(1) if match else link


def fetch_linkedin_alerts(
    imap_host: str,
    user: str,
    app_password: str,
    label: str,
    lookback_days: int = 2,
) -> list[dict]:
    conn = imaplib.IMAP4_SSL(imap_host)
    conn.login(user, app_password)
    conn.select(f'"{label}"')

    since_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
    _, data = conn.search(None, f'(SINCE "{since_date}")')
    message_ids = data[0].split()
    print(f"Found {len(message_ids)} email(s) in '{label}' since {since_date}.")

    jobs = []
    for i, num in enumerate(message_ids):
        _, msg_data = conn.fetch(num, "(RFC822)")
        raw_bytes = msg_data[0][1]
        _save_raw_email_for_debugging(raw_bytes, i)

        msg = email.message_from_bytes(raw_bytes)
        html = _get_html_body(msg)
        if html:
            jobs.extend(_parse_job_links(html))

    conn.logout()
    return jobs


def save_new_jobs(jobs: list[dict]) -> int:
    """Inserts jobs not already in the table. Returns how many were new."""
    inserted = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for job in jobs:
                job_id = job_id_from_link(job["link"])
                cur.execute("SELECT 1 FROM jobs WHERE job_id = %s", (job_id,))
                if cur.fetchone() is not None:
                    continue  # already seen this posting

                cur.execute(
                    """
                    INSERT INTO jobs (job_id, title, company, location, link, snippet, status, fetch_status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'new', 'pending')
                    """,
                    (job_id, job["title"], job["company"], job["location"], job["link"], job["snippet"]),
                )
                inserted += 1
        conn.commit()
    return inserted


def run() -> None:
    jobs = fetch_linkedin_alerts(
        imap_host="imap.gmail.com",
        user=os.environ["GMAIL_USER"],
        app_password=os.environ["GMAIL_APP_PASSWORD"],
        label=os.environ.get("GMAIL_LABEL", "LinkedIn Alerts"),
        lookback_days=int(os.environ.get("ALERT_LOOKBACK_DAYS", "2")),
    )
    print(f"Parsed {len(jobs)} job posting(s) from alert emails.")

    new_count = save_new_jobs(jobs)
    print(f"Inserted {new_count} new job(s) into the database.")


if __name__ == "__main__":
    # Run this directly to test:
    #   docker compose run --rm app python parser/alert_parser.py
    run()
