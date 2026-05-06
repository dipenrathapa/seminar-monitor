#!/usr/bin/env python3
"""
DIT Pfarrkirchen Seminar Slot Monitor
GitHub Actions version — runs once per trigger, then exits.
State saved to both repo file AND cache for maximum reliability.
"""

import requests
from bs4 import BeautifulSoup
import time
import re
import json
import os
import sys
import logging
import urllib.parse
from datetime import datetime

# ─── Configuration ────────────────────────────────────────────────────────────

BASE_URL     = "https://pmit-ext.th-deg.de"
START_URL    = f"{BASE_URL}/seminare/ec"
NTFY_URL     = "https://ntfy.sh/dipendra_seminar_alert"
ALERTED_FILE = "alerted_slots.json"

# *** ONLY notify for seminars whose name contains this keyword ***
NOTIFY_KEYWORD = "Presentation Techniques"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SeminarSlotBot/2.0)",
    "Accept-Language": "en-US,en;q=0.9",
}

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("monitor")

# ─── Persistent state ─────────────────────────────────────────────────────────

def load_alerted() -> dict:
    """
    Load alerted slots from file.
    File comes from either:
      - git checkout (most reliable, persists forever)
      - actions/cache restore (fast, but can be evicted)
    Whichever is present, we use it.
    """
    if os.path.exists(ALERTED_FILE):
        try:
            with open(ALERTED_FILE, encoding="utf-8") as f:
                data = json.load(f)
                log.info("Loaded %d alerted slot(s) from %s", len(data), ALERTED_FILE)
                return data
        except (json.JSONDecodeError, IOError) as e:
            log.warning("Could not read %s (%s) — starting fresh.", ALERTED_FILE, e)
    else:
        log.info("No existing state file found — starting fresh.")
    return {}


def save_alerted(alerted: dict) -> None:
    with open(ALERTED_FILE, "w", encoding="utf-8") as f:
        json.dump(alerted, f, ensure_ascii=False, indent=2)
    log.info("State saved to %s (%d entries)", ALERTED_FILE, len(alerted))

# ─── Notification ─────────────────────────────────────────────────────────────

def header_safe(text: str) -> str:
    """Encode header value safely for HTTP (Latin-1 safe or percent-encoded)."""
    try:
        text.encode("latin-1")
        return text
    except UnicodeEncodeError:
        return urllib.parse.quote(text, safe=" ,!?.:/()")


def send_notification(title: str, body: str, url: str = "") -> bool:
    headers = {
        "Title":    header_safe(title),
        "Priority": "urgent",
        "Tags":     "bell,university",
    }
    if url:
        headers["Click"] = url

    try:
        resp = requests.post(
            NTFY_URL,
            data=body.encode("utf-8"),
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        log.info("  Notification sent!")
        return True
    except Exception as e:
        log.error("  Notification failed: %s", e)
        return False

# ─── Scraping ─────────────────────────────────────────────────────────────────

def parse_seats(cell_text: str):
    match = re.search(r"(\d+)\s*/\s*(\d+)", cell_text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def fetch_page(url: str):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log.warning("Failed to fetch %s: %s", url, e)
        return None


def scrape_all_seminars() -> list:
    seminars = []
    page_url = START_URL

    while page_url:
        log.info("Fetching: %s", page_url)
        soup = fetch_page(page_url)
        if soup is None:
            log.error("Skipping page due to fetch failure.")
            break

        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            link_tag = cells[0].find("a", href=True)
            if not link_tag:
                continue

            slot_id  = link_tag["href"]
            name     = link_tag.get_text(strip=True)
            seat_txt = cells[1].get_text(strip=True)
            taken, total = parse_seats(seat_txt)

            seminars.append({
                "slot_id": slot_id,
                "name":    name,
                "taken":   taken,
                "total":   total,
                "url":     urllib.parse.urljoin(BASE_URL, slot_id),
                "seats":   seat_txt,
            })

        # Follow pagination using urljoin (handles all href formats safely)
        next_link = soup.find("a", rel="next")
        if next_link and next_link.get("href"):
            page_url = urllib.parse.urljoin(BASE_URL, next_link["href"])
            time.sleep(1)
        else:
            page_url = None

    return seminars

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 55)
    log.info("DIT Seminar Monitor — GitHub Actions run")
    log.info("Time: %s UTC", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 55)

    alerted = load_alerted()

    seminars = scrape_all_seminars()
    if not seminars:
        log.warning("No seminars found — site may be down.")
        save_alerted(alerted)  # still save so git commit step has a file
        sys.exit(0)

    log.info("Found %d seminar entries total.", len(seminars))

    for s in seminars:
        slot_id = s["slot_id"]
        taken   = s["taken"]
        total   = s["total"]

        if taken is None:
            continue

        # *** Only notify for seminars matching the keyword ***
        if NOTIFY_KEYWORD not in s["name"]:
            continue

        available = total - taken
        log.info("  [%s/%s] %s", taken, total, s["name"][:70])

        if available > 0:
            if slot_id not in alerted:
                log.info("  *** SLOT OPEN — sending alert!")
                title = f"Seminar slot open! ({available} seat free)"
                body  = (
                    f"{s['name']}\n\n"
                    f"Seats available: {available} of {total}\n"
                    f"Register now: {s['url']}"
                )
                sent = send_notification(title, body, url=s["url"])
                if sent:
                    alerted[slot_id] = {
                        "name":       s["name"],
                        "alerted_at": datetime.utcnow().isoformat(timespec="seconds"),
                    }
            else:
                log.info("  (already notified — skipping)")
        else:
            if slot_id in alerted:
                log.info("  (was open, now full again — resetting)")
                del alerted[slot_id]

    save_alerted(alerted)
    log.info("Done. Goodbye!")


if __name__ == "__main__":
    main()