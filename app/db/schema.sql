-- Single table tracking a job posting through every stage of the pipeline.
-- status lifecycle: new -> fetched -> matched -> drafted -> sent (or skipped at any stage)

CREATE TABLE IF NOT EXISTS jobs (
    job_id            TEXT PRIMARY KEY,       -- LinkedIn's numeric job id, parsed from the link
    title             TEXT NOT NULL,
    company           TEXT,
    location          TEXT,
    link              TEXT NOT NULL,
    recruiter_name    TEXT,                   -- often NULL; filled in later stages if findable
    snippet           TEXT,                   -- short teaser text from the alert email
    full_description  TEXT,                   -- populated by the job detail fetcher (step 4)
    required_skills   TEXT[],                 -- skills parsed out of full_description (step 4)
    fetch_status      TEXT NOT NULL DEFAULT 'pending',  -- pending | fetched | failed
    match_score       REAL,                   -- populated by the job matcher (step 5)
    drafted_message   TEXT,                   -- populated by the message drafter (step 6)
    status            TEXT NOT NULL DEFAULT 'new',       -- new | matched | skipped | drafted | sent
    processed_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_required_skills ON jobs USING GIN (required_skills);
