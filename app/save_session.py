"""
Run this LOCALLY on your own machine, not inside Docker -- it opens a real,
visible browser window so you can log into LinkedIn yourself (including
solving any 2FA/security challenge), and saves the resulting session to a
file the job_fetcher component reads later.

One-time setup (on your host machine, not in the container):
    pip install playwright
    playwright install chromium
    python save_session.py

Re-run this whenever the saved session expires (LinkedIn will eventually
log it out; the fetcher's requests will start failing/returning login
pages when that happens).
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

# Matches LINKEDIN_SESSION_PATH in .env.example / the app/data volume mount,
# so the container can read what this script writes on the host.
OUTPUT_PATH = Path("app/data/auth_state.json")


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")

        print("A browser window has opened.")
        print("Log into LinkedIn manually (solve 2FA/captcha if prompted).")
        input("Once you're fully logged in and see your feed, press Enter here...")

        context.storage_state(path=str(OUTPUT_PATH))
        browser.close()

    print(f"Session saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
