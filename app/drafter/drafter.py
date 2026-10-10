"""
For every job with status = 'matched', drafts a 4-5 sentence recruiter
outreach message using the job's required_skills/description and your
resume, via OpenAI's chat completions API. Stores the result and advances
status to 'drafted'.
"""

import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from db.connection import get_connection

load_dotenv()

CHAT_MODEL = "gpt-4o-mini"
RESUME_DATA_PATH = Path("/app/data/resume_data.json")
RESUME_TEXT_CHAR_LIMIT = 3000  # keep prompt size/cost reasonable

SYSTEM_PROMPT = """You help a job seeker draft short outreach messages to recruiters on LinkedIn.

Rules:
- Write exactly 4 to 5 sentences. No more, no less.
- Tone: formal but not stiff -- professional and warm, like a real person, not corporate boilerplate.
- Reference the specific skills/requirements from the job posting that genuinely match the candidate's resume, framed as strengths.
- You may weave in one other relevant strength from the resume even if not explicitly requested in the posting, if it strengthens the pitch.
- Never invent experience, skills, or qualifications not present in the resume.
- Do not address the message to a specific name -- the recruiter's name is often unknown. Open naturally without "Dear [Name]" or similar.
- Do not include a signature or sign-off line (no "Best regards," no name at the end) -- this is just the message body, the candidate will add their own closing when sending it.
- Output only the message text. No preamble, no quotation marks, no markdown."""


def load_resume_text() -> str:
    data = json.loads(RESUME_DATA_PATH.read_text())
    return data["raw_text"][:RESUME_TEXT_CHAR_LIMIT]


def get_jobs_to_draft() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id, title, company, full_description, snippet, required_skills
                FROM jobs
                WHERE status = 'matched'
                """
            )
            rows = cur.fetchall()
    return [
        {
            "job_id": r[0],
            "title": r[1],
            "company": r[2],
            "full_description": r[3],
            "snippet": r[4],
            "required_skills": r[5] or [],
        }
        for r in rows
    ]


def build_user_prompt(job: dict, resume_text: str) -> str:
    description = job["full_description"] or job["snippet"] or "(no description available)"
    skills_line = ", ".join(job["required_skills"]) if job["required_skills"] else "(none detected)"

    return f"""JOB POSTING
Title: {job['title']}
Company: {job['company'] or 'Unknown'}
Skills detected in posting: {skills_line}
Description:
{description}

CANDIDATE RESUME
{resume_text}

Draft the outreach message now, following all the rules."""


def call_llm(system_prompt: str, user_prompt: str, api_key: str) -> str:
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": CHAT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.6,
            "max_tokens": 250,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def update_job(job_id: str, drafted_message: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET drafted_message = %s, status = 'drafted', processed_at = now()
                WHERE job_id = %s
                """,
                (drafted_message, job_id),
            )
        conn.commit()


def run() -> None:
    api_key = os.environ["OPENAI_API_KEY"]
    resume_text = load_resume_text()

    jobs = get_jobs_to_draft()
    print(f"{len(jobs)} job(s) to draft.")

    for job in jobs:
        user_prompt = build_user_prompt(job, resume_text)
        try:
            message = call_llm(SYSTEM_PROMPT, user_prompt, api_key)
        except requests.RequestException as e:
            print(f"  [{job['job_id']}] draft failed, leaving status='matched' for retry: {e}")
            continue

        update_job(job["job_id"], message)
        print(f"  [{job['job_id']}] drafted ({len(message.split())} words)")


if __name__ == "__main__":
    # Run this directly to test:
    #   docker compose run --rm app python drafter/drafter.py
    run()
