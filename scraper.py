"""
scraper.py — Fetch CAND judge calendar pages and save raw HTML.

Saves per-judge HTML to raw_html/{slug}.html
Caches the judge index for 6 days to avoid redundant requests.
Uses 10-second delays between judge pages.
"""

import os
import re
import json
import time
import logging
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

INDEX_URL = "https://www.cand.uscourts.gov/calendars/judges-weekly-calendars/"
BASE_URL = "https://www.cand.uscourts.gov"
RAW_HTML_DIR = "raw_html"
INDEX_CACHE = os.path.join(RAW_HTML_DIR, "index.json")
INDEX_HTML_CACHE = os.path.join(RAW_HTML_DIR, "_index.html")
INDEX_HTML_LEGACY = "judges.html"   # fallback: saved from previous run
INDEX_MAX_AGE_DAYS = 6
DELAY_BETWEEN_JUDGES = 10  # seconds


def fetch_with_playwright(url: str) -> str | None:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context().new_page()
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            # Extra pause for JS-rendered content
            page.wait_for_timeout(3000)
            content = page.content()
            browser.close()
            return content
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None


def load_index_cache() -> list[dict] | None:
    """Return cached judge list if fresh, else None."""
    if not os.path.exists(INDEX_CACHE):
        return None
    with open(INDEX_CACHE) as f:
        data = json.load(f)
    fetched_at = datetime.fromisoformat(data.get("fetched_at", "2000-01-01"))
    if datetime.now() - fetched_at > timedelta(days=INDEX_MAX_AGE_DAYS):
        logger.info("Judge index cache is stale, will re-fetch.")
        return None
    logger.info(f"Using cached judge index ({len(data['judges'])} judges).")
    return data["judges"]


def save_index_cache(judges: list[dict]):
    os.makedirs(RAW_HTML_DIR, exist_ok=True)
    with open(INDEX_CACHE, "w") as f:
        json.dump({"fetched_at": datetime.now().isoformat(), "judges": judges}, f, indent=2)


def parse_judges_from_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    judges = []

    # Current CAND website: responsive grid layout, judges grouped under <h3> city headers
    current_location = ""
    for el in soup.find_all(["h3", "div"]):
        if el.name == "h3":
            current_location = el.get_text(strip=True)
            continue
        if "views-view-responsive-grid__item-inner" not in (el.get("class") or []):
            continue
        link = el.find("a", href=True)
        if not link or not link.get_text(strip=True):
            continue
        name = " ".join(link.get_text(strip=True).split())  # normalize extra whitespace
        href = link["href"]
        url = href if href.startswith("http") else f"{BASE_URL}{href}"
        slug = re.sub(r"[^a-zA-Z0-9]", "_", name)
        judges.append({"name": name, "slug": slug, "url": url, "location": current_location})

    if judges:
        return judges

    # Fallback: old table layout
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 1:
            continue
        link = cells[0].find("a", href=True)
        if not link or not link.get_text(strip=True):
            continue
        name = link.get_text(strip=True)
        href = link["href"]
        url = href if href.startswith("http") else f"{BASE_URL}{href}"
        location = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        slug = re.sub(r"[^a-zA-Z0-9]", "_", name)
        judges.append({"name": name, "slug": slug, "url": url, "location": location})

    return judges


def get_judge_list() -> list[dict]:
    judges = load_index_cache()
    if judges:
        return judges

    os.makedirs(RAW_HTML_DIR, exist_ok=True)

    # Try live fetch first
    logger.info("Fetching judge index from CAND website...")
    html = fetch_with_playwright(INDEX_URL)

    if html:
        with open(INDEX_HTML_CACHE, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("Saved fresh judge index.")
    else:
        # Fall back to saved copies
        for fallback_path in [INDEX_HTML_CACHE, INDEX_HTML_LEGACY]:
            if os.path.exists(fallback_path):
                logger.warning(f"Live fetch failed — using cached index: {fallback_path}")
                with open(fallback_path, encoding="utf-8") as f:
                    html = f.read()
                break
        if not html:
            raise RuntimeError(
                "Could not fetch judge index and no local fallback found.\n"
                "Visit https://www.cand.uscourts.gov/calendars/judges-weekly-calendars/ "
                f"in your browser, save the page as '{INDEX_HTML_LEGACY}', then re-run."
            )

    judges = parse_judges_from_html(html)
    logger.info(f"Found {len(judges)} judges.")
    save_index_cache(judges)
    return judges


def fetch_all_calendars(judges: list[dict]):
    os.makedirs(RAW_HTML_DIR, exist_ok=True)

    # Clear stale html files before fetching fresh ones
    for f in os.listdir(RAW_HTML_DIR):
        if f.endswith(".html") and not f.startswith("_"):
            os.remove(os.path.join(RAW_HTML_DIR, f))

    success, failed = 0, 0

    for i, judge in enumerate(judges):
        out_path = os.path.join(RAW_HTML_DIR, f"{judge['slug']}.html")
        logger.info(f"({i+1}/{len(judges)}) Fetching {judge['name']}...")

        html = fetch_with_playwright(judge["url"])
        if html:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(html)
            logger.info(f"  Saved to {out_path}")
            success += 1
        else:
            logger.warning(f"  Failed for {judge['name']}")
            failed += 1

        if i < len(judges) - 1:
            logger.info(f"  Waiting {DELAY_BETWEEN_JUDGES}s...")
            time.sleep(DELAY_BETWEEN_JUDGES)

    logger.info(f"Done. {success} succeeded, {failed} failed.")


if __name__ == "__main__":
    judges = get_judge_list()
    fetch_all_calendars(judges)
