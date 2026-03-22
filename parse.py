"""
parse.py — Parse raw judge HTML files into a minimal schedule CSV.

Reads: raw_html/{slug}.html (one file per judge)
Reads: raw_html/index.json (for judge name/location metadata)
Writes: schedule.csv with columns: judge, location, date, time, case_number

Party names and case descriptions are intentionally NOT extracted here.
CourtListener is the authoritative source for that data (see enrich.py).
"""

import os
import re
import csv
import json
import logging
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RAW_HTML_DIR = "raw_html"
INDEX_CACHE = os.path.join(RAW_HTML_DIR, "index.json")
OUTPUT_FILE = "schedule.csv"

CASE_RE = re.compile(r"(\d+:\d{2}-[a-z]{2}-\d{5}-[A-Z]+(?:-\d+)?)", re.IGNORECASE)
# Matches both full and abbreviated month names: "Thursday, Apr 23 2026" or "Thursday, April 23 2026"
DATE_RE = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
    r",?\s+\w+\s+\d{1,2},?\s+\d{4}",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"^\d{1,2}:\d{2}[AP]M$")


def parse_calendar_html(html: str, judge_name: str, location: str) -> list[dict]:
    """
    Extract (judge, location, date, time, case_number) rows from a judge calendar page.

    The HTML structure has three row types that we track across <td> elements:
      - Date row:     <td class="Date">Wednesday, Apr 9 2025</td>
      - Time row:     <td>08:00AM</td>  (standalone time, no case number)
      - Case row:     <td>3:25-cv-01780-WHA - Party v. Party\nHearing type</td>

    We track current_date and current_time as state while iterating all <td> cells.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Extract judge name and courtroom from the <strong> header block
    # Structure: "Calendar for: Judge Name<br>Courtroom X, Nth Floor<br>Courtroom Deputy: ..."
    courtroom = ""
    strong = soup.find("strong")
    if strong and "Calendar for:" in strong.get_text():
        parts = [s.strip() for s in strong.get_text("\n").split("\n") if s.strip()]
        if not judge_name and parts:
            judge_name = parts[0].replace("Calendar for:", "").strip()
        # Second part is courtroom (skip lines that are "Courtroom Deputy: ...")
        for part in parts[1:]:
            if not part.lower().startswith("courtroom deputy"):
                courtroom = part
                break

    rows = []
    current_date = ""
    current_time = ""

    for td in soup.find_all("td"):
        # Check for date cell (has class="Date" — case-insensitive)
        if any(c.lower() == "date" for c in (td.get("class") or [])):
            text = td.get_text(strip=True)
            if DATE_RE.search(text):
                current_date = text
                current_time = ""  # reset time when date changes
            continue

        # Get all non-empty lines from this cell
        lines = [ln.strip() for ln in td.get_text("\n").split("\n") if ln.strip()]
        if not lines:
            continue

        for line in lines:
            # Standalone date (fallback for pages that don't use class="Date")
            if DATE_RE.match(line):
                current_date = line
                current_time = ""
                break

            # Standalone time
            if TIME_RE.match(line):
                current_time = line
                break

            # Case number — always associate with current date + time
            case_match = CASE_RE.search(line)
            if case_match and current_date and current_time:
                rows.append({
                    "judge": judge_name,
                    "location": location,
                    "courtroom": courtroom,
                    "date": current_date,
                    "time": current_time,
                    "case_number": case_match.group(1),
                })
                break  # one case number per <td>

    return rows


def load_judge_index() -> dict[str, dict]:
    """Return {slug: {name, location}} from the cached index."""
    if not os.path.exists(INDEX_CACHE):
        logger.warning("No index.json found — judge metadata will be inferred from filenames.")
        return {}
    with open(INDEX_CACHE) as f:
        data = json.load(f)
    return {j["slug"]: j for j in data.get("judges", [])}


def parse_hearing_date(date_str: str) -> datetime | None:
    """Parse a hearing date string like 'Friday, Mar 13 2026' into a datetime."""
    normalized = " ".join(date_str.split())
    for fmt in ("%A, %b %d %Y", "%A, %B %d %Y"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    return None


def run(days: int = 7):
    if not os.path.isdir(RAW_HTML_DIR):
        raise FileNotFoundError(f"'{RAW_HTML_DIR}' directory not found. Run scraper.py first.")

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = today + timedelta(days=days)
    logger.info(f"Window: {today.strftime('%Y-%m-%d')} to {cutoff.strftime('%Y-%m-%d')} ({days} days)")

    judge_index = load_judge_index()
    all_rows = []
    seen_cases = set()

    html_files = sorted(f for f in os.listdir(RAW_HTML_DIR) if f.endswith(".html") and not f.startswith("_"))
    if not html_files:
        raise FileNotFoundError(f"No judge HTML files found in '{RAW_HTML_DIR}'. Run scraper.py first.")

    logger.info(f"Parsing {len(html_files)} judge calendar files...")

    for filename in html_files:
        slug = filename[:-5]  # strip .html
        meta = judge_index.get(slug, {})
        judge_name = meta.get("name", slug.replace("_", " "))
        location = meta.get("location", "")

        filepath = os.path.join(RAW_HTML_DIR, filename)
        with open(filepath, encoding="utf-8") as f:
            html = f.read()

        rows = parse_calendar_html(html, judge_name, location)

        # Filter to window and deduplicate
        for row in rows:
            dt = parse_hearing_date(row["date"])
            if not dt or not (today <= dt < cutoff):
                continue
            key = (row["date"], row["time"], row["case_number"])
            if key not in seen_cases:
                seen_cases.add(key)
                all_rows.append(row)

        logger.info(f"  {judge_name}: {len(rows)} total, {sum(1 for r in all_rows if judge_name in r['judge'])} in window")

    all_rows.sort(key=lambda r: (r["date"], r["time"], r["judge"]))

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["judge", "location", "courtroom", "date", "time", "case_number"])
        writer.writeheader()
        writer.writerows(all_rows)

    logger.info(f"Wrote {len(all_rows)} hearings in window to {OUTPUT_FILE}")


if __name__ == "__main__":
    import sys
    days = 7
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
    run(days=days)
