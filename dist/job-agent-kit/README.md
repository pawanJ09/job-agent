# Job Agent: Setup Guide

This app runs on your own computer, in Docker. Once a day it:

1. reads your LinkedIn job alert emails from your Gmail,
2. scores each job against your resume,
3. drafts a short note to the recruiter for the best matches, and
4. emails you one digest with the job links, match percentages and drafts.

It only emails the digest to you. It never contacts a recruiter. You read the drafts,
edit them, and send anything yourself.

Built and tested on a Mac. It should work on Windows and Linux anywhere Docker runs,
but that has not been tested.

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

Because of that, don't shorten the delays (`FETCH_DELAY_*`) or raise the number of days
scanned (`ALERT_LOOKBACK_DAYS`) without a good reason. LinkedIn can block or slow down
requests at any time, and changes to its pages or emails can break the app. You are
responsible for how you use this software. It is provided as is, without warranty.

---

## What you need

- A computer that can run **Docker Desktop**.
- A **Gmail** account that receives your LinkedIn job alerts.
- An **OpenAI** account with a little credit. At typical volumes the cost is small, but
  check your usage on the OpenAI dashboard.
- A **LinkedIn** account with a saved job search.
- Your **resume** as a PDF or Word file. It must contain real text, not a scan.

Set aside about 30 minutes for the first setup.

---

## Step 1: Install and start Docker Desktop

Install Docker Desktop, open it, and wait until it says Docker is running. Then open a
terminal and check:

```bash
docker info
```

If it prints details about your Docker setup, you're ready. If it says it can't connect
to the Docker daemon, Docker Desktop isn't running yet.

In a terminal, go into this kit's folder. Every command below is run from there.

## Step 2: Set up Gmail

**2a. Make an app password.** This lets the app log in to your mailbox without your real
password.

1. Go to `myaccount.google.com/security` and turn on **2-Step Verification**.
2. Go to `myaccount.google.com/apppasswords` and create an app password named
   `job-agent`.
3. Copy the 16-character code right away, because it is only shown once. Write it
   without spaces.

If you use a work or school account, an admin may have turned app passwords off. In that
case, use a personal Gmail account.

**2b. Make a label and a filter** so the app reads only LinkedIn alerts:

1. Open one of your LinkedIn job alert emails and note the **From** address.
2. In Gmail, go to **Settings, See all settings, Filters and Blocked Addresses** and
   create a filter with that address in the **From** field.
3. Tick **Apply the label** and create a label, for example `LinkedIn Alerts`.
4. Tick **Also apply filter to matching conversations** so alerts already in your inbox
   are labeled too.

IMAP, the way the app reads mail, is always on for personal Gmail accounts.

## Step 3: Get an OpenAI API key

1. Go to `platform.openai.com` and sign in.
2. Add a payment method and some credit under **Billing**. The API is billed separately
   from ChatGPT, so a ChatGPT subscription doesn't cover it. Setting a monthly spending
   limit there is a good idea.
3. Under **API keys**, create a key and copy it.

## Step 4: Create a daily LinkedIn alert

On LinkedIn, search for the jobs you want, switch on **Job alert**, set it to **Daily**,
and make sure **Email** delivery is on. Alerts need to be arriving before the app has
anything to read.

## Step 5: Add your resume and fill in `.env`

1. Put your resume in the `data` folder, named `resume.pdf`. For a Word file, name it
   `resume.docx` and set `RESUME_PATH=/app/data/resume.docx` in `.env`.
2. In the terminal, copy the settings template:
   ```bash
   cp .env.example .env
   ```
   Files that start with a dot are hidden in Finder, so use the terminal.
3. Open `.env` in a text editor and fill in every value marked REQUIRED: the database
   password (letters and numbers only), your Gmail address, the app password, your
   OpenAI key, and where the digest should be sent. Set `SCHEDULE_TIMEZONE` to your own
   timezone.

When the app starts it checks all of this and lists anything missing or wrong.

## Step 6: Run it once

```bash
docker compose pull
docker compose run --rm -e RUN_MODE=once app python main.py
```

This runs the whole process one time. It takes several minutes, because the app waits
10 to 30 seconds between jobs on purpose. Watch the output. Afterwards you should have a
digest in your inbox.

Some outcomes are normal:
- **"0 job posting(s)":** no alert email arrived in the last 2 days. Wait for the next
  alert, or temporarily raise `ALERT_LOOKBACK_DAYS` in `.env`.
- **"No drafted jobs to send":** no job scored high enough. See "Adjusting the match
  score" below.

## Step 7: Start it for real

```bash
docker compose up -d
```

Check that it is running:

```bash
docker compose ps
docker compose logs --tail 30 app
```

You should see a line saying the pipeline runs daily at your chosen time. If it is
already past that time and no run is recorded for today, it runs once straight away. It
finds nothing new and doesn't send a second digest.

---

## Keeping it running

- **Docker Desktop must be running.** Turn on its setting to start when you sign in.
- **Your computer must be awake at some point after the scheduled time.** If it was
  asleep or off, the day's run starts soon after Docker is running again.

## Adjusting the match score

Every job gets a score between 0 and 1. Jobs below `MATCH_THRESHOLD` are skipped and get
no draft. See your recent scores:

```bash
grep "score=" logs/pipeline.log | tail -20
```

Set `MATCH_THRESHOLD` in `.env` just below the scores of jobs you'd want, then apply it:

```bash
docker compose up -d --force-recreate app
```

To re-score jobs that were already skipped:

```bash
docker compose exec db psql -U job_agent -d jobs -c "UPDATE jobs SET status = 'new', match_score = NULL WHERE status = 'skipped';"
```

The score is a ranking, not a verdict. A good fit may show 50% or 60%, not 95%.

## Updating and stopping

- **Update:** replace the image tag in `docker-compose.yml` with the newer version (or
  use a newer kit), then run `docker compose pull` and `docker compose up -d`. Your
  settings, resume and data are kept.
- **Stop:** `docker compose down`. Your data is kept. Adding `-v` deletes the database.

## Privacy

- The scoring and drafting steps send text to OpenAI: your resume text and each job
  description with its title and company, and for drafts the detected skills as well.
  Nothing else is sent.
- Your jobs, descriptions and drafts are stored on your computer, in the Docker
  database volume. Your resume copy and logs are in the `data` and `logs` folders.
- `.env` holds your passwords and keys. Don't share it or put it anywhere public.

## Troubleshooting

- **The app keeps restarting, or the log starts with "The app can't start because of
  problems in your configuration":** the message lists exactly what to fix in `.env`.
  Then run `docker compose up -d --force-recreate app`.
- **"Cannot connect to the Docker daemon":** Docker Desktop isn't running. Open it and
  wait.
- **An OpenAI error saying credit is exhausted (HTTP 429):** add credit in the OpenAI
  billing page. No restart is needed.
- **No digest arrived:** check your spam folder, then `grep -i "error\|failed" logs/pipeline.log | tail`.
  Also check whether any job scored above your threshold.
- **The run happens at the wrong time:** set `SCHEDULE_TIMEZONE` in `.env` to your own
  timezone, then recreate the app container as above.
- **To force a run today:** delete `data/last_run.txt` and run
  `docker compose up -d --force-recreate app`.
