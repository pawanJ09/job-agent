# LinkedIn Job Agent — Setup Guide

A locally-run agent that reads your LinkedIn job alert emails, fetches full posting
details, scores them against your resume, drafts a short outreach message for each
good match, and emails you a daily digest to review and send yourself.

This guide walks through setup from zero — nothing has been run yet — to having the
full pipeline running on a daily schedule in Docker.

**Follow the steps in order.** Several later steps depend on earlier ones having real
data to work with (e.g. the matcher needs jobs the fetcher already processed).

---

## Before you start: what you'll need

- **Docker Desktop** installed **and running** on your machine. Every `docker compose`
  command in this guide needs the Docker engine up; if Docker Desktop is closed you'll
  see an error like "Cannot connect to the Docker daemon." Open it and wait for the
  whale icon in your menu bar to show it as running before continuing. (The only
  step that doesn't need Docker is `save_session.py` in Step 6, which runs directly
  on your machine.)
- **Python 3.11+** installed locally (only for one setup script that needs a visible
  browser window — everything else runs inside Docker).
- A **Gmail account** (used for both reading LinkedIn alerts and sending your digest).
- A **LinkedIn account** with a saved job search.
- An **OpenAI account** with billing enabled (used for matching and drafting; cost at
  this volume is expected to be cents per month, not dollars).
- Your **resume** as a PDF or DOCX file.

---

## Project structure

```
job-agent/
├── docker-compose.yml
├── .env.example          # copy this to .env and fill in real values
├── save_session.py       # run on your HOST machine, not in Docker
├── logs/                 # pipeline logs land here
└── app/
    ├── Dockerfile
    ├── requirements.txt
    ├── main.py            # orchestrator / scheduler — the container's entry point
    ├── data/              # resume, parsed resume JSON, saved LinkedIn session
    ├── db/                # schema + connection helper
    ├── resume/            # resume parser
    ├── gmail/             # alert email parser
    ├── fetcher/           # job detail fetcher + skills list
    ├── matcher/           # resume-to-posting matcher
    ├── drafter/           # message drafter
    └── mailer/            # digest composer + sender
```

---

## Step 1 — Configure your `.env` file

```bash
cp .env.example .env
```

Open `.env` and fill in each value. You won't have everything yet — the next few
steps walk through getting each credential. For now, just know what's coming:

| Variable | Where it comes from |
|---|---|
| `POSTGRES_PASSWORD` | Make up any password |
| `GMAIL_USER` / `GMAIL_APP_PASSWORD` | Step 2 below |
| `GMAIL_LABEL` | The Gmail label you'll create in Step 2 |
| `RESUME_PATH` | Step 3 below |
| `OPENAI_API_KEY` | Step 4 below |
| `LINKEDIN_SESSION_PATH` | Step 5 below |
| `DIGEST_RECIPIENT` | Usually the same as `GMAIL_USER` |
| Everything else | Sensible defaults are already filled in — leave as-is for now |

---

## Step 2 — Set up Gmail

**2a. Create a Gmail app password** (lets the agent log in without your real password):

1. Go to `myaccount.google.com/security` and turn on **2-Step Verification** if it isn't already.
2. Go to `myaccount.google.com/apppasswords`.
3. Create a new app password named something like `job-agent`.
4. Copy the 16-character code immediately — it's shown only once.
5. In `.env`, set `GMAIL_USER` to your full Gmail address and `GMAIL_APP_PASSWORD` to
   the code (remove the spaces).

> If your Gmail account is managed by a work/school organization, an admin may have
> disabled app passwords entirely — if you don't see that option, you'd need an
> OAuth2-based approach instead, which this project doesn't currently implement.

**2b. Create a filter and label** so the agent only reads LinkedIn alert emails:

1. In Gmail, go to **Settings → See all settings → Filters and Blocked Addresses**.
2. Create a filter matching mail from LinkedIn's job alert sender.
3. Apply a label — e.g. `LinkedIn Alerts` — to matching mail.
4. Make sure `GMAIL_LABEL` in `.env` matches the label name exactly.

**2c. Confirm IMAP is enabled**: Settings → See all settings → Forwarding and
POP/IMAP → make sure IMAP access is enabled.

---

## Step 3 — Add your resume

Drop your resume file into `app/data/` (e.g. `app/data/resume.pdf`), and set
`RESUME_PATH` in `.env` to match — the default `/app/data/resume.pdf` is correct if
you name the file exactly that.

Only PDF and DOCX are supported. If your resume is a scanned/image-based PDF (not
actual selectable text), extraction will fail silently — re-export as a text-based
PDF or DOCX first.

---

## Step 4 — Get an OpenAI API key

This key is used twice: for computing similarity scores (matcher) and for drafting
messages (drafter) — one key covers both.

1. Go to `platform.openai.com` and sign in (or create an account).
2. Add a payment method under **Billing**.
3. Go to **API keys** and create a new key.
4. Paste it into `.env` as `OPENAI_API_KEY`.

---

## Step 5 — Set up your LinkedIn job alert

If you don't already have a daily job alert configured:

1. Go to `linkedin.com/jobs`, search with your target title/location, and apply filters.
2. Toggle on **Job alert** at the top of the results.
3. Set frequency to **Daily** and make sure **Email** delivery is enabled.
4. Double-check **Settings & Privacy → Notifications → Job alert emails** is on at
   the account level.

Give it a day or so to start generating alert emails before testing the parser in
Step 8.

---

## Step 6 — Save a LinkedIn login session

This step runs on **your own machine, not in Docker** — it needs to open a real,
visible browser window so you can log in manually.

```bash
pip install playwright
playwright install chromium
python save_session.py
```

A browser window opens to the LinkedIn login page. Log in manually (solve any
2FA/captcha prompt), then press Enter in your terminal once you see your feed. This
saves `app/data/auth_state.json`, which the containerized fetcher reads later.

This session will eventually expire — if the fetcher starts failing on everything,
re-run this step.

---

## Step 7 — Build and start the database

```bash
docker compose build app
docker compose up -d db
```

Give it a few seconds, then confirm it's healthy:

```bash
docker compose ps
```

You should see `db` listed as `healthy`.

---

## Step 8 — Test each component individually

Test in this order — each one builds on data the previous one created. Run each
command and check its output before moving to the next.

**8a. Initialize the database schema:**
```bash
docker compose run --rm app python db/connection.py
```
Expect: `Database initialized (jobs table ready).`

**8b. Parse your resume:**
```bash
docker compose run --rm app python resume/parser.py
```
Expect: a line count, and a new file at `app/data/resume_data.json`. Open it and
skim the `lines` array — if it's empty, PDF extraction likely failed (see Step 3).

**8c. Parse LinkedIn alert emails:**
```bash
docker compose run --rm app python gmail/alert_parser.py
```
Expect: a count of parsed and inserted jobs. If you get `0`, confirm you actually
have alert emails in the labeled folder (check the `.eml` files saved to
`app/data/raw_emails/` for debugging).

**8d. Fetch full job descriptions:**
```bash
docker compose run --rm app python fetcher/job_fetcher.py
```
Expect: one line per job with its fetch status and extracted skills. This step only
has work to do if Step 8c inserted new jobs.

**8e. Match jobs against your resume:**
```bash
docker compose run --rm app python matcher/matcher.py
```
Expect: a similarity score per job. Look at the scores — jobs you know are a good
fit vs. a poor fit — and adjust `MATCH_THRESHOLD` in `.env` if needed.

**8f. Draft outreach messages:**
```bash
docker compose run --rm app python drafter/drafter.py
```
Expect: a drafted message per matched job. Read a few critically — tone can drift,
and it's easier to tune the prompt now than after it's unattended.

**8g. Send the digest email:**
```bash
docker compose run --rm app python mailer/digest_mailer.py
```
Expect: an email in your inbox with a table of job/recruiter/message. Check how it
renders in your actual email client.

---

## Step 9 — Run the full pipeline once, end to end

Once every individual component works, test them chained together:

```bash
docker compose run --rm -e RUN_MODE=once app python main.py
```

This runs all five stages in order and exits. Watch the output (or check
`logs/pipeline.log` afterward) to confirm each stage ran and handed off to the next
correctly.

---

## Step 10 — Start it running for real

```bash
docker compose up -d
```

Both `db` and `app` now run in the background, with `restart: always` — meaning they
come back up automatically if the container crashes or your machine reboots (as long
as Docker itself is running). `app` sits idle until `SCHEDULE_HOUR:SCHEDULE_MINUTE`
(default `08:00`) each day, then runs the full pipeline automatically.

Check it's running:
```bash
docker compose ps
docker compose logs -f app
```

**To keep it running reliably, two things must stay true:**

1. **Docker Desktop must be running.** `restart: always` only works while the Docker
   engine is up. If you quit Docker Desktop, or your machine reboots and Docker
   Desktop doesn't launch, the containers stay down and the daily run won't happen.
   To avoid this, open Docker Desktop → Settings → General and enable **Start Docker
   Desktop when you sign in to your computer**. After a reboot and login, Docker
   Desktop starts and brings `db` and `app` back up automatically.
2. **Your machine must wake up within the catch-up window.** If it's asleep at
   `SCHEDULE_HOUR:SCHEDULE_MINUTE` (for example, the laptop lid is closed), the
   pipeline runs as soon as the machine wakes, as long as that's within
   `CATCHUP_GRACE_HOURS` of the scheduled time (default 12). If it wakes after the
   window has passed, that day's run is skipped. Missed runs never pile up: several
   missed days collapse into a single catch-up run. This only covers sleep and wake.
   If Docker Desktop itself was quit or restarted, the scheduler starts fresh and
   does not remember what it missed.

---

## Day-to-day maintenance

- **Logs**: `logs/pipeline.log` on your host machine, or `docker compose logs app`.
- **LinkedIn session expired**: re-run `save_session.py` (Step 6).
- **Match threshold feels off**: check recent scores in the logs, adjust
  `MATCH_THRESHOLD` in `.env`, then `docker compose up -d` to restart `app` with the
  new value.
- **Skills list needs updating**: edit `SKILLS` in `app/fetcher/skills.py`, then
  `docker compose build app` to rebuild.
- **Changed `requirements.txt` or the `Dockerfile`**: always rebuild explicitly —
  `docker compose build app` — since Docker won't detect those changes on its own.
- **Stop everything**: `docker compose down` (add `-v` only if you also want to wipe
  the Postgres data volume — not recommended unless you're starting fresh).

---

## Troubleshooting

- **`psycopg2-binary` fails to build locally**: you likely don't need to `pip
  install` on your host at all — everything runs inside Docker, where this isn't an
  issue. If you do want a local dev environment, try `pip install --upgrade pip`
  first, or install PostgreSQL locally to provide `pg_config`.
- **"Cannot connect to the Docker daemon"**: Docker Desktop isn't running. Open it,
  wait for it to finish starting, and retry.
- **Daily digest arrived late**: expected if your machine was asleep at the scheduled
  time. The pipeline runs when it wakes, within the `CATCHUP_GRACE_HOURS` window.
- **Daily digest didn't arrive**: check Docker Desktop is running, and that your
  machine woke within the catch-up window (`CATCHUP_GRACE_HOURS`). Then look at
  `logs/pipeline.log` for that day.
- **A stage reports 0 items to process**: check that the stage before it in the
  pipeline actually produced data — most stages depend on the previous one's output.
- **Fetcher failing on every job**: your saved LinkedIn session has likely expired —
  re-run Step 6.
- **Drafted messages sound off-tone**: adjust `SYSTEM_PROMPT` in
  `app/drafter/drafter.py` and rebuild.
