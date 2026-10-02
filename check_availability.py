"""
Checks ticket availability for a specific Sagrada Familia date by loading the
booking page headlessly and reading the same `/availability` JSON API call
the page itself makes (see diagnose notes) -- not DOM scraping, so it isn't
sensitive to the site's frontend markup/classes changing.

Sends an email (via SMTP, credentials from .env) only on the transition from
"no-availability" to "availability" for TARGET_DATE, not on every check that
finds it available (state is tracked in state.json next to this script).

Run manually to test: `python check_availability.py`
Intended to run on a schedule (launchd/cron) -- see run_check.sh.
"""
import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# ---- config ----
TARGET_DATE = "2026-10-10"          # the date we care about
TARGET_YEAR, TARGET_MONTH = 2026, 10
PAGE_URL = "https://tickets.sagradafamilia.org/en/1-individual/4375-sagrada-familia"

HERE = Path(__file__).parent
STATE_FILE = HERE / "state.json"
LOG_FILE = HERE / "check.log"

load_dotenv(HERE / ".env")


def log(msg):
    line = f"{datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def get_availability_for_target():
    """Loads the page, captures the /availability JSON response for
    TARGET_YEAR/TARGET_MONTH, and returns the status string for TARGET_DATE
    (e.g. "availability" / "no-availability"), or None if not found/failed."""
    captured = {}

    def on_response(resp):
        if (
            "/availability" in resp.url
            and "minTickets" not in resp.url
            and f"month={TARGET_MONTH}" in resp.url
            and f"year={TARGET_YEAR}" in resp.url
        ):
            try:
                captured["data"] = resp.json()
            except Exception as e:
                log(f"Failed to parse availability response as JSON: {e}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            page.on("response", on_response)
            page.goto(PAGE_URL, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)  # let async calendar data settle
        finally:
            browser.close()

    if "data" not in captured:
        log(f"Did not capture an availability response for {TARGET_YEAR}-{TARGET_MONTH:02d}")
        return None

    return captured["data"].get(TARGET_DATE)


def send_email(status):
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    to_addr = os.environ.get("NOTIFY_TO", "sabrina.wang@cern.ch")

    body = (
        f"Sagrada Familia tickets for {TARGET_DATE} just became available "
        f"(status: {status}).\n\n{PAGE_URL}"
    )
    msg = MIMEText(body)
    msg["Subject"] = f"Sagrada Familia tickets available for {TARGET_DATE}!"
    msg["From"] = smtp_user
    msg["To"] = to_addr

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [to_addr], msg.as_string())

    log(f"Email sent to {to_addr}")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_status": None}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state))


def main():
    state = load_state()
    status = get_availability_for_target()

    if status is None:
        log(f"Check FAILED (no data captured) -- leaving state unchanged ({state['last_status']})")
        sys.exit(1)

    log(f"{TARGET_DATE} status = {status!r} (previous = {state['last_status']!r})")

    if status == "availability" and state["last_status"] != "availability":
        try:
            send_email(status)
        except Exception as e:
            log(f"FAILED to send email: {e}")
            sys.exit(1)

    state["last_status"] = status
    save_state(state)


if __name__ == "__main__":
    main()
