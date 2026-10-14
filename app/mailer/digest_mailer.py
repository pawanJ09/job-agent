"""
For every job with status = 'drafted', builds one daily digest email -- a
table of job link, recruiter name, and drafted message -- and sends it via
SMTP. On successful send, advances all included jobs to status = 'sent'.

If there's nothing at status = 'drafted', this is a no-op: no empty digest
gets sent.
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from dotenv import load_dotenv

from db.connection import get_connection

load_dotenv()


def get_jobs_to_send() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id, title, company, link, recruiter_name, drafted_message, match_score
                FROM jobs
                WHERE status = 'drafted'
                ORDER BY created_at
                """
            )
            rows = cur.fetchall()
    return [
        {
            "job_id": r[0],
            "title": r[1],
            "company": r[2],
            "link": r[3],
            "recruiter_name": r[4],
            "drafted_message": r[5],
            "match_score": r[6],
        }
        for r in rows
    ]


def build_html_digest(jobs: list[dict]) -> str:
    rows_html = []
    for job in jobs:
        title_company = escape(job["title"] or "")
        if job["company"]:
            title_company += f" — {escape(job['company'])}"

        recruiter = escape(job["recruiter_name"]) if job["recruiter_name"] else "<em>Not listed — add manually</em>"
        link = escape(job["link"])
        message = escape(job["drafted_message"] or "").replace("\n", "<br>")
        # match_score is a 0-1 similarity; show it as a whole-number percentage.
        match = f"{job['match_score'] * 100:.0f}%" if job["match_score"] is not None else "N/A"

        rows_html.append(f"""
            <tr>
                <td style="padding:10px;border:1px solid #ddd;vertical-align:top;">
                    <a href="{link}">{title_company}</a>
                </td>
                <td style="padding:10px;border:1px solid #ddd;vertical-align:top;white-space:nowrap;">{match}</td>
                <td style="padding:10px;border:1px solid #ddd;vertical-align:top;">{recruiter}</td>
                <td style="padding:10px;border:1px solid #ddd;vertical-align:top;">{message}</td>
            </tr>
        """)

    return f"""
    <html>
    <body style="font-family:Arial,sans-serif;">
        <h2>Daily Job Match Digest — {len(jobs)} posting(s)</h2>
        <table style="border-collapse:collapse;width:100%;">
            <tr style="background:#f2f2f2;">
                <th style="padding:10px;border:1px solid #ddd;text-align:left;">Job Posting</th>
                <th style="padding:10px;border:1px solid #ddd;text-align:left;">Match</th>
                <th style="padding:10px;border:1px solid #ddd;text-align:left;">Recruiter</th>
                <th style="padding:10px;border:1px solid #ddd;text-align:left;">Drafted Message</th>
            </tr>
            {''.join(rows_html)}
        </table>
        <p style="color:#888;font-size:12px;margin-top:20px;">
            Messages are drafts for you to review before sending. Add a greeting
            and your name before posting to LinkedIn.
        </p>
    </body>
    </html>
    """


def send_digest(html_body: str, job_count: int) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Job Match Digest — {job_count} new posting(s)"
    msg["From"] = os.environ["GMAIL_USER"]
    msg["To"] = os.environ["DIGEST_RECIPIENT"]
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"])) as server:
        server.starttls()
        server.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"])
        server.sendmail(msg["From"], [msg["To"]], msg.as_string())


def mark_sent(job_ids: list[str]) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = 'sent', processed_at = now() WHERE job_id = ANY(%s)",
                (job_ids,),
            )
        conn.commit()


def run() -> None:
    jobs = get_jobs_to_send()
    if not jobs:
        print("No drafted jobs to send. Skipping.")
        return

    html_body = build_html_digest(jobs)
    send_digest(html_body, len(jobs))

    job_ids = [job["job_id"] for job in jobs]
    mark_sent(job_ids)
    print(f"Digest sent with {len(jobs)} job(s). Marked as sent: {job_ids}")


if __name__ == "__main__":
    # Run this directly to test:
    #   docker compose run --rm app python mailer/digest_mailer.py
    run()
