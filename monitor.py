# import requests
# from bs4 import BeautifulSoup
# import time, re, json, os

# URL          = "https://pmit-ext.th-deg.de/seminare/ec"
# BASE_URL     = "https://pmit-ext.th-deg.de"
# KEYWORD      = "Presentation Techniques"
# NTFY_URL     = "https://ntfy.sh/dipendra_seminar_alert"
# ALERTED_FILE = "alerted.json"

# # ── persist alerted set to disk ───────────────────────────────
# def load_alerted():
#     if os.path.exists(ALERTED_FILE):
#         with open(ALERTED_FILE) as f:
#             return set(json.load(f))
#     return set()

# def save_alerted(alerted):
#     with open(ALERTED_FILE, "w") as f:
#         json.dump(list(alerted), f)

# # ── send ntfy notification ────────────────────────────────────
# def send_alert(message):
#     try:
#         requests.post(NTFY_URL, data=message.encode("utf-8"), timeout=10)
#         print("  Notification sent!")
#     except Exception as e:
#         print("  Notification failed:", e)

# # ── parse "35 / 35" into (taken, total) ──────────────────────
# def parse_status(status_text):
#     match = re.search(r"(\d+)\s*/\s*(\d+)", status_text)
#     if match:
#         return int(match.group(1)), int(match.group(2))
#     return None, None

# # ── fetch all pages ───────────────────────────────────────────
# def get_all_rows():
#     all_rows = []
#     page = 1
#     headers = {"User-Agent": "Mozilla/5.0 (compatible; SeminarBot/1.0)"}
#     while True:
#         page_url = f"{URL}/page:{page}" if page > 1 else URL
    
#         try:
#             r = requests.get(page_url, headers=headers, timeout=10)
#             r.raise_for_status()
#         except Exception as e:
#             print(f"  Failed to fetch page {page}: {e}")
#             break
#         soup = BeautifulSoup(r.text, "html.parser")
#         rows = soup.find_all("tr")
#         all_rows.extend(rows)
#         if not soup.find("a", rel="next"):
#             break
#         page += 1
#         time.sleep(1)
#     return all_rows

# # ── main check ────────────────────────────────────────────────
# def check_slots(alerted):
#     print(f"\nChecking... [{time.strftime('%H:%M:%S')}]")
#     found_any = False

#     for row in get_all_rows():
#         cells = row.find_all("td")
#         if len(cells) < 2:
#             continue

#         link_tag = cells[0].find("a")
#         if not link_tag:
#             continue

#         name    = link_tag.get_text(strip=True)
#         if KEYWORD not in name:
#             continue

#         # ✅ FIX: use the href as slot_id — stable, never contains seat count
#         #    e.g. "/seminare/dates/view/3243"  — unique per seminar date
#         slot_id  = link_tag["href"]
#         full_url = BASE_URL + slot_id
#         status   = cells[1].get_text(strip=True)
#         taken, total = parse_status(status)
#         found_any = True

#         print(f"  Seminar : {name[:65]}")
#         print(f"  Status  : {status}  |  id={slot_id}")

#         if taken is not None and taken < total:
#             if slot_id not in alerted:
#                 print("  >> SLOT AVAILABLE — sending alert!")
#                 send_alert(
#                     f"SLOT OPEN!\n\n"
#                     f"{name}\n"
#                     f"Seats: {status}\n\n"
#                     f"Register: {full_url}"
#                 )
#                 alerted.add(slot_id)
#                 save_alerted(alerted)
#             else:
#                 print("  (already alerted — skipping)")
#         else:
#             # full again → clear from alerted so we re-notify if it reopens
#             if slot_id in alerted:
#                 alerted.discard(slot_id)
#                 save_alerted(alerted)
#                 print("  (slot closed again — reset for future alerts)")

#     if not found_any:
#         print("  No matching seminar found on any page")

# # ── test ─────────────────────────────────────────────────────
# def test_system():
#     print("TEST MODE — sending test notification...")
#     send_alert("TEST: ntfy is working! Monitor is alive.")
#     print("If your phone buzzed, everything is connected.\n")

# # ── entrypoint ────────────────────────────────────────────────
# if __name__ == "__main__":
#     test_system()
#     alerted = load_alerted()
#     print("Monitoring started. Checking every 60 seconds...")
#     while True:
#         try:
#             check_slots(alerted)
#         except Exception as e:
#             print("Unexpected error:", e)
#         print("  Sleeping 60s...\n")
#         time.sleep(60)



#!/usr/bin/env python3
"""
DIT Pfarrkirchen Seminar Slot Monitor
GitHub Actions version — runs once per trigger, then exits.
State (alerted slots) is persisted via alerted_slots.json cached by GitHub Actions.
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
    if os.path.exists(ALERTED_FILE):
        try:
            with open(ALERTED_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            log.warning("Could not read %s — starting fresh.", ALERTED_FILE)
    return {}


def save_alerted(alerted: dict) -> None:
    with open(ALERTED_FILE, "w", encoding="utf-8") as f:
        json.dump(alerted, f, ensure_ascii=False, indent=2)
    log.info("State saved to %s", ALERTED_FILE)

# ─── Notification ─────────────────────────────────────────────────────────────

def header_safe(text: str) -> str:
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
                "url":     BASE_URL + slot_id,
                "seats":   seat_txt,
            })

        next_link = soup.find("a", rel="next")
        if next_link and next_link.get("href"):
            href = next_link["href"]
            page_url = BASE_URL + href if href.startswith("/") else href
            time.sleep(1)
        else:
            page_url = None

    return seminars

# ─── Main (runs once) ─────────────────────────────────────────────────────────

def main():
    log.info("=" * 55)
    log.info("DIT Seminar Monitor — GitHub Actions run")
    log.info("Time: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"))
    log.info("=" * 55)

    alerted = load_alerted()
    log.info("Loaded %d previously alerted slot(s).", len(alerted))

    seminars = scrape_all_seminars()
    if not seminars:
        log.warning("No seminars found — site may be down.")
        sys.exit(0)

    log.info("Found %d seminar entries total.", len(seminars))
    newly_alerted = False

    for s in seminars:
        slot_id = s["slot_id"]
        taken   = s["taken"]
        total   = s["total"]

        if taken is None:
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
                        "alerted_at": datetime.now().isoformat(timespec="seconds"),
                    }
                    newly_alerted = True
            else:
                log.info("  (already notified — skipping)")
        else:
            if slot_id in alerted:
                log.info("  (was open, now full again — resetting)")
                del alerted[slot_id]
                newly_alerted = True

    # Always save state so the cache is updated
    save_alerted(alerted)
    log.info("Done. Goodbye!")


if __name__ == "__main__":
    main()