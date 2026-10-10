"""
Scores every job that's been through the fetcher (fetch_status != 'pending')
against your resume, using OpenAI embeddings + cosine similarity, and marks
each one 'matched' or 'skipped' based on MATCH_THRESHOLD.

The resume's embedding is computed once and cached to disk (keyed by a hash
of its text) so re-runs don't re-embed an unchanged resume every time --
only job description embeddings are computed fresh each run.
"""

import hashlib
import json
import math
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from db.connection import get_connection

load_dotenv()

EMBEDDING_MODEL = "text-embedding-3-small"
RESUME_DATA_PATH = Path("/app/data/resume_data.json")
RESUME_EMBEDDING_CACHE_PATH = Path("/app/data/resume_embedding.json")


def get_embedding(text: str, api_key: str) -> list[float]:
    response = requests.post(
        "https://api.openai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": EMBEDDING_MODEL, "input": text[:8000]},  # keep well under the token limit
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def get_resume_embedding(api_key: str) -> list[float]:
    if not RESUME_DATA_PATH.exists():
        raise FileNotFoundError(
            f"No resume data at {RESUME_DATA_PATH}. Run the resume parser (step 2) first."
        )
    resume_text = json.loads(RESUME_DATA_PATH.read_text())["raw_text"]
    text_hash = hashlib.sha256(resume_text.encode()).hexdigest()

    if RESUME_EMBEDDING_CACHE_PATH.exists():
        cached = json.loads(RESUME_EMBEDDING_CACHE_PATH.read_text())
        if cached.get("source_hash") == text_hash:
            return cached["embedding"]

    embedding = get_embedding(resume_text, api_key)
    RESUME_EMBEDDING_CACHE_PATH.write_text(
        json.dumps({"source_hash": text_hash, "embedding": embedding})
    )
    return embedding


def get_jobs_to_match() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id, full_description, snippet
                FROM jobs
                WHERE status = 'new' AND fetch_status != 'pending'
                """
            )
            rows = cur.fetchall()
    return [{"job_id": r[0], "full_description": r[1], "snippet": r[2]} for r in rows]


def update_job(job_id: str, score: float | None, status: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET match_score = %s, status = %s, processed_at = now()
                WHERE job_id = %s
                """,
                (score, status, job_id),
            )
        conn.commit()


def run(threshold: float) -> None:
    api_key = os.environ["OPENAI_API_KEY"]
    resume_embedding = get_resume_embedding(api_key)

    jobs = get_jobs_to_match()
    print(f"{len(jobs)} job(s) to match.")

    for job in jobs:
        text = job["full_description"] or job["snippet"] or ""
        if not text.strip():
            print(f"  [{job['job_id']}] no text to compare, skipping.")
            update_job(job["job_id"], None, "skipped")
            continue

        job_embedding = get_embedding(text, api_key)
        score = cosine_similarity(resume_embedding, job_embedding)
        status = "matched" if score >= threshold else "skipped"

        update_job(job["job_id"], score, status)
        print(f"  [{job['job_id']}] score={score:.3f} -> {status}")


if __name__ == "__main__":
    # Run this directly to test:
    #   docker compose run --rm app python matcher/matcher.py
    run(threshold=float(os.environ.get("MATCH_THRESHOLD", "0.75")))
