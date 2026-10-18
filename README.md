# LinkedIn Job Agent — Setup Guide

A locally-run agent that reads your LinkedIn job alert emails, fetches full posting
details, scores them against your resume, drafts a short outreach message for each
good match, and emails you a daily digest to review and send yourself.

This guide walks through setup from zero — nothing has been run yet — to having the
full pipeline running on a daily schedule in Docker.

**Follow the steps in order.** Several later steps depend on earlier ones having real
data to work with (e.g. the matcher needs jobs the fetcher already processed).

---

## Important: LinkedIn's terms and your account

LinkedIn's terms restrict automated access to its service, including scraping. Please
read them yourself. This is not legal advice. Here is what this app does with LinkedIn:

1. **It reads your own job alert emails** from your own Gmail mailbox. It never logs
   into LinkedIn for this.
2. **For each new job, it requests that job's posting page** from LinkedIn to download
   the full description, one request at a time with a pause of 10 to 30 seconds between
   requests, without logging in. This is automated access and may conflict with
   LinkedIn's terms.

Because of that:
- Don't shorten the delays (`FETCH_DELAY_*`) or raise the number of days scanned
  (`ALERT_LOOKBACK_DAYS`) without a good reason.
- Don't use the optional saved-login fallback in Step 6. It sends requests with your
  own LinkedIn login, which ties them to your account.
- LinkedIn can block or slow down requests at any time, and changes to its pages or
  emails can break the app.

You are responsible for how you use this software. It is provided as is, without
warranty.

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
    ├── parser/            # alert email parser
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
| `LINKEDIN_SESSION_PATH` | Optional, Step 6 below (leave the default) |
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

1. Open one of your actual LinkedIn job alert emails and copy its **From** address.
   Use the address from a real alert, since the sender LinkedIn uses can vary.
2. In Gmail, go to **Settings → See all settings → Filters and Blocked Addresses**.
3. Create a filter with that address in the **From** field.
4. On the next screen, tick **Apply the label** and create a label — e.g.
   `LinkedIn Alerts`.
5. Also tick **Also apply filter to matching conversations** if you want alerts
   already in your inbox to be labeled too. A filter only applies to new mail
   arriving after it's created unless you tick this box.
6. Make sure `GMAIL_LABEL` in `.env` matches the label name exactly.

> The alert parser only reads emails from the last 2 days (`ALERT_LOOKBACK_DAYS` in
> `.env`), so older labeled alerts are ignored. If no alert has arrived in the last
> 2 days, the first parser run in Step 8c will report 0 jobs. That doesn't mean
> something is broken. Wait for the next alert, or temporarily raise
> `ALERT_LOOKBACK_DAYS` to cover an older one.

**2c. Check IMAP access**: go to Settings → See all settings → Forwarding and
POP/IMAP and scroll to the **IMAP access** section. What you see depends on your
account type:

- **Personal Gmail account (@gmail.com)**: since January 2025 there is no Enable/
  Disable IMAP choice, because IMAP is always on. Nothing to switch on here.
- **Older layout (the toggle still appears)**: select **Enable IMAP** and click
  **Save Changes** at the bottom of the page.
- **Work or school (Google Workspace) account**: if the IMAP access section is
  missing entirely, IMAP is probably disabled at the organization level and an
  admin has to turn it on in the Google Admin console. This project can't work
  around that.

The most reliable check is running the alert parser in Step 8c. If it connects and
reports a job count, IMAP is working. A login or authentication error usually means
a problem with the app password (check `GMAIL_APP_PASSWORD` has no spaces and
`GMAIL_USER` is your full address). A connection error points more toward IMAP being
blocked at the account level.

---

## Step 3 — Add your resume

Drop your resume file into `app/data/` (e.g. `app/data/resume.pdf`), and set
`RESUME_PATH` in `.env` to match — the default `/app/data/resume.pdf` is correct if
you name the file exactly that.

Only PDF and DOCX are supported. If your resume is a scanned/image-based PDF (not
actual selectable text), extraction will fail silently — re-export as a text-based
PDF or DOCX first.

**Updating your resume later:** just replace the file in `app/data/`. At the start of
every pipeline run, the app compares the file's modified time with the parsed copy
(`resume_data.json`) and re-parses it automatically if the resume is newer. The matcher
then re-embeds it on its own, because its cache is keyed to the resume text. If the
app can't extract any text, it logs an error and keeps using the previous parsed
resume. To force a re-parse, delete `app/data/resume_data.json`. (A file copied with an
older timestamp than the parsed copy won't be noticed; deleting `resume_data.json` fixes
that too.)

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

## Step 6 — Save a LinkedIn login session (optional)

**You can skip this step, and I recommend you do** (see "LinkedIn's terms" above). The
job fetcher requests each posting anonymously, with no
login. A saved session is only used as a fallback if an anonymous request fails, so the
pipeline works without one. Do this step only if you see anonymous fetches failing in
Step 8d (the output says whether each job was fetched "anonymous" or via "session
fallback").

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

This session will eventually expire. It only matters if you rely on the fallback, in
which case re-run this step when fetches that need it start failing.

---

## Step 7 — Build and start the database

**First, start Docker Desktop.** This is the first step that needs it. Open the
Docker Desktop app and wait until it reports that the engine is running (the whale
icon in your menu bar stops animating). Then confirm from your terminal:

```bash
docker info
```

If that prints details about your Docker setup, you're good. If it says "Cannot
connect to the Docker daemon," Docker Desktop isn't running yet. Wait a little
longer or reopen it. From here on, every `docker compose` command in this guide
needs Docker Desktop running.

Then build the app image and start the database:

```bash
docker compose build app
docker compose up -d db
```

The first build downloads the Python base image and installs the dependencies, so
it can take a few minutes.

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
You only need to run this by hand for testing: `main.py` does the same thing
automatically at the start of each run when the resume is new or changed.

**8c. Parse LinkedIn alert emails:**
```bash
docker compose run --rm app python parser/alert_parser.py
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
Expect: an email in your inbox with a table of job, match percentage, recruiter and
message. Check how it
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
(default `08:00`) each day, then runs the full pipeline automatically. That time is
read in the timezone set by `SCHEDULE_TIMEZONE` in `.env` (default
`UTC`). Set it to your own IANA timezone name, since containers
otherwise default to UTC. Log timestamps in `logs/pipeline.log` are still in UTC.

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
2. **Your machine can sleep, but it has to be awake for the run to happen.** The app
   checks the real clock once a minute and records the date of its last run in
   `app/data/last_run.txt`. If your machine was asleep (or Docker Desktop was closed)
   at `SCHEDULE_HOUR:SCHEDULE_MINUTE`, the pipeline starts within a minute of the
   container running again, as long as no run has happened yet that day. Several missed
   days still produce just one run. The run time is only a "not before" time: starting
   the container late in the day with no run recorded triggers an immediate run.

---

## Day-to-day maintenance

- **Logs**: `logs/pipeline.log` on your host machine, or `docker compose logs app`.
- **Fetches failing**: check the reason printed per job in `logs/pipeline.log`. If you
  use the optional saved session as a fallback and it expired, re-run `save_session.py`
  (Step 6).
- **Match threshold feels off**: check recent scores in the logs, adjust
  `MATCH_THRESHOLD` in `.env`, then `docker compose up -d` to restart `app` with the
  new value.
- **Skills list needs updating**: edit `SKILLS` in `app/fetcher/skills.py`, then
  `docker compose build app` to rebuild.
- **Changed any code, `requirements.txt`, or the `Dockerfile`**: always rebuild
  explicitly — `docker compose build app` — since the code is copied into the image
  at build time and Docker won't detect those changes on its own. (Only `./logs` and
  `./app/data` are live-mounted from your machine.)
- **Stop everything**: `docker compose down` (add `-v` only if you also want to wipe
  the Postgres data volume — not recommended unless you're starting fresh).

---

## Releasing a new version (GitHub Actions)

Pushing a version tag publishes everything for you: it builds the image, runs the
personal-data check, pushes the image to GitHub's container registry (ghcr.io) for Intel
and Apple Silicon, builds the kit zip, and creates a GitHub release with the zip attached.
The image lives in GitHub Packages, and the kit is a zip, so it goes on the release page.
The workflow is `.github/workflows/release.yml`.

**One-time setup**
1. The image package was first pushed by hand, so the workflow has to be given access to
   it. On GitHub, open your profile, then Packages, then `job-agent`, then Package
   settings. Under Manage Actions access, add this repository with the Write role.
2. Commit and push `.github/workflows/release.yml`, the `kit/` folder, and the rest of the
   project to GitHub.

**Each release**

```bash
git tag -a v1.0.1 -m "Release 1.0.1: what changed"
git push origin v1.0.1
```

The `-a` makes an annotated tag, which records who made it, when, and your message. The
workflow works with plain tags too, but annotated tags are the usual choice for releases.

Then watch the run in the repository's Actions tab. It takes roughly 10 to 20 minutes, mostly
the Apple Silicon build. When it finishes, the release page has the new zip, and
`releases/latest` points to it.

**Rules**
- The version comes from the tag: `v1.0.1` becomes image tag `1.0.1`. Tags must look like
  `v1.2.3`.
- Never reuse a version. The workflow stops if that image tag already exists.
- The `latest` image tag moves to each new release.

**If a run fails**
- It stopped before pushing the image: fix the problem, then delete the tag and tag again.
  `git push --delete origin v1.0.1` and `git tag -d v1.0.1` remove it.
- It failed after the image was pushed: that version number is used up. Fix the problem
  and release the next number, for example `v1.0.2`. Delete any half-made release on GitHub.
- An error like "Resource not accessible by integration" or a 403 while pushing means the
  package access in step 1 above is missing.

The manual commands in the Makefile (`make push`, `make kit`) still work if you ever need
them.

---

## Troubleshooting

- **`psycopg2-binary` fails to build locally**: you likely don't need to `pip
  install` on your host at all — everything runs inside Docker, where this isn't an
  issue. If you do want a local dev environment, try `pip install --upgrade pip`
  first, or install PostgreSQL locally to provide `pg_config`.
- **`docker compose build app` fails with `pg_config executable not found`**: the
  Dockerfile's base image is a Python version too new for the pinned
  `psycopg2-binary` (e.g. 3.14). The first line of `app/Dockerfile` must be
  `FROM python:3.11-slim`. Fix it, then rebuild with `docker compose build app
  --no-cache`.
- **"Cannot connect to the Docker daemon"**: Docker Desktop isn't running. Open it,
  wait for it to finish starting, and retry.
- **Daily digest arrived late**: expected if your machine was asleep at the scheduled
  time. The pipeline starts within a minute of the machine waking.
- **The app container keeps restarting, or `docker compose logs app` starts with "The
  app can't start because of problems in your configuration"**: the app checks your
  `.env` at startup and lists exactly what is missing or wrong (a setting that is
  missing, a leftover placeholder from `.env.example`, a database password containing
  `@ : / ? # %` or a space, an invalid number or timezone, or no resume file). Fix each item in
  `.env`, then run `docker compose up -d --force-recreate app`.
- **Daily digest didn't arrive**: check Docker Desktop is running and the machine was
  awake at some point after the scheduled time. Then look at `logs/pipeline.log` for
  that day, and at `app/data/last_run.txt` (the date of the last run). To force a run
  today, delete that file and run `docker compose up -d --force-recreate app`.
- **`ModuleNotFoundError: No module named 'db'` (or `parser`, `fetcher`, ...)**: two
  possible causes. (1) The image was built before `ENV PYTHONPATH=/app` was added to
  `app/Dockerfile`: rebuild with `docker compose build app`. (2) A folder is in the
  wrong place or misnamed. `main.py` imports `parser.alert_parser`, so the alert
  parser must be at `app/parser/alert_parser.py`. Compare your
  folders against the project structure.
- **A stage reports 0 items to process**: check that the stage before it in the
  pipeline actually produced data — most stages depend on the previous one's output.
- **Fetcher failing on every job**: the fetcher prints the reason for each failure
  (for example `HTTP 429` means LinkedIn is rate-limiting you; wait and retry with longer
  `FETCH_DELAY_*` values). Failed jobs are not retried automatically. To retry them:
  `docker compose exec db psql -U job_agent -d jobs -c "UPDATE jobs SET fetch_status
  = 'pending', status = 'new', match_score = NULL WHERE fetch_status = 'failed';"`
- **Drafted messages sound off-tone**: adjust `SYSTEM_PROMPT` in
  `app/drafter/drafter.py` and rebuild.
