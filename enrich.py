"""
enrich.py — Enrich schedule.csv with CourtListener data and flag relevant cases.

Reads:  schedule.csv (from parse.py)
Writes: enriched.csv  — all hearings with CourtListener fields added
Writes: relevant.csv  — filtered to cases matching tech/privacy criteria

CourtListener API: https://www.courtlistener.com/api/rest/v4/
Free account token recommended (higher rate limits). Set COURTLISTENER_TOKEN in .env.
Without a token: 100 requests/day. With free account: 5,000 requests/day.
Results cached in courtlistener_cache.json — known cases are never re-queried.
"""

import os
import re
import csv
import json
import time
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import requests

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SCHEDULE_FILE = "schedule.csv"
ENRICHED_FILE = "enriched.csv"
RELEVANT_FILE = "relevant.csv"
CACHE_FILE = "courtlistener_cache.json"

CL_BASE = "https://www.courtlistener.com/api/rest/v4"
CL_TOKEN = os.getenv("COURTLISTENER_TOKEN")  # optional but recommended
CL_DELAY = 1.0  # seconds between API calls

# ── Nature-of-suit codes to flag as relevant ──────────────────────────────────
# Only the most specific tech/privacy-relevant codes. Civil rights and broad
# statutory codes removed — too many false positives.
RELEVANT_NOS_CODES = {
    "480": "Consumer Credit / Data Breach",
    "895": "Freedom of Information Act",
}

# ── Party name keywords to flag as relevant ───────────────────────────────────
# "cisco" removed — matches "San Francisco" constantly.
# Remaining keywords are matched as whole words to avoid substring false positives.
TECH_KEYWORDS = [
    "google", "alphabet", "meta", "facebook", "instagram", "apple", "microsoft",
    "amazon", "openai", "anthropic", "nvidia", "twitter", "x corp", "x.com",
    "tiktok", "bytedance", "uber", "lyft", "airbnb", "salesforce", "oracle",
    "adobe", "netflix", "spotify", "linkedin", "snap", "snapchat", "pinterest",
    "palantir", "cloudflare", "youtube", "zoom", "slack", "dropbox",
    "doordash", "instacart", "stripe", "paypal", "coinbase", "robinhood",
    "tesla", "spacex", "samsung", "intel", "qualcomm", "broadcom",
    "whatsapp", "threads", "roblox", "bytedance",
]

# ── Cause keywords: two tiers ─────────────────────────────────────────────────
# STRONG: inherently digital/privacy — flag regardless of party names.
CAUSE_KEYWORDS_STRONG = [
    "privacy", "data breach", "wiretap", "biometric", "facial recognition",
    "artificial intelligence", "machine learning", "surveillance",
    "computer fraud", "cfaa", "dmca", "section 230",
    "california consumer", "ccpa", "gdpr", "coppa",
]

# WEAK: only flag if a named tech company is already matched.
# (patent, copyright, antitrust etc. are too common without a tech party)
CAUSE_KEYWORDS_WEAK = [
    "antitrust", "monopol", "sherman act", "clayton act",
    "copyright", "patent", "trade secret",
]

ENRICHED_FIELDS = [
    "judge", "location", "courtroom", "date", "time", "case_number",
    "case_name", "nature_of_suit", "nos_code", "cause",
    "date_filed", "is_active", "cl_url",
    "relevant", "relevance_reasons",
]


# ── Cache helpers ─────────────────────────────────────────────────────────────

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


# ── Case number normalization ──────────────────────────────────────────────────

def normalize_case_number(raw: str) -> str:
    """
    Strip judge initials suffix from CAND case numbers.
    '3:25-cv-01780-WHA' → '3:25-cv-01780'
    '3:23-cr-00085-WHA' → '3:23-cr-00085'
    """
    return re.sub(r"-[A-Z]{2,4}(?:-\d+)?$", "", raw)


# ── CourtListener API ──────────────────────────────────────────────────────────

def cl_headers() -> dict:
    h = {"Accept": "application/json"}
    if CL_TOKEN:
        h["Authorization"] = f"Token {CL_TOKEN}"
    return h


def fetch_from_courtlistener(case_number_raw: str) -> dict | None:
    """Query CourtListener for a case and return a normalized result dict."""
    docket_number = normalize_case_number(case_number_raw)
    url = f"{CL_BASE}/dockets/"
    params = {"docket_number": docket_number, "court": "cand"}

    for attempt in range(1, 4):
        try:
            resp = requests.get(url, headers=cl_headers(), params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.RequestException as e:
            if attempt < 3:
                logger.warning(f"CourtListener request failed for {docket_number} (attempt {attempt}/3): {e} — retrying in 5s")
                time.sleep(5)
            else:
                logger.warning(f"CourtListener request failed for {docket_number} after 3 attempts: {e}")
                return None

    results = data.get("results", [])
    if not results:
        logger.debug(f"No CourtListener results for {docket_number}")
        return {"_not_found": True}

    # Use the first result (most relevant match)
    r = results[0]
    return {
        "case_name": r.get("case_name", ""),
        "nature_of_suit": r.get("nature_of_suit", ""),
        "nos_code": str(r.get("nature_of_suit_number") or ""),
        "cause": r.get("cause", ""),
        "date_filed": r.get("date_filed", ""),
        "date_terminated": r.get("date_terminated"),
        "is_active": r.get("date_terminated") is None,
        "cl_url": f"https://www.courtlistener.com{r['absolute_url']}" if r.get("absolute_url") else "",
        "_not_found": False,
    }


# ── Relevance scoring ──────────────────────────────────────────────────────────

def _word_match(keyword: str, text: str) -> bool:
    """Match keyword as a whole word (not a substring of another word)."""
    return bool(re.search(r"\b" + re.escape(keyword) + r"\b", text))


def score_relevance(row: dict, cl_data: dict) -> tuple[bool, list[str]]:
    """Return (is_relevant, [reasons]) based on CourtListener data."""
    reasons = []

    if not cl_data or cl_data.get("_not_found"):
        return False, []

    # 1. Nature-of-suit code (narrow list — only specific tech/privacy codes)
    nos = cl_data.get("nos_code", "")
    if nos in RELEVANT_NOS_CODES:
        reasons.append(f"NOS {nos}: {RELEVANT_NOS_CODES[nos]}")

    # 2. Named tech company in case name (whole-word match to avoid substrings)
    case_name_lower = cl_data.get("case_name", "").lower()
    tech_party_matched = False
    for kw in TECH_KEYWORDS:
        if _word_match(kw, case_name_lower):
            reasons.append(f"Party: '{kw}'")
            tech_party_matched = True
            break

    # 3. Cause keywords — strong triggers fire regardless; weak only if tech party matched
    cause_lower = cl_data.get("cause", "").lower()
    nature_lower = cl_data.get("nature_of_suit", "").lower()
    combined = f"{cause_lower} {nature_lower}"

    for kw in CAUSE_KEYWORDS_STRONG:
        if kw in combined:
            reasons.append(f"Cause: '{kw}'")
            break

    if tech_party_matched:
        for kw in CAUSE_KEYWORDS_WEAK:
            if kw in combined:
                reasons.append(f"Cause: '{kw}'")
                break

    return len(reasons) > 0, reasons


# ── Main ──────────────────────────────────────────────────────────────────────

def _within_days(date_str: str, days: int) -> bool:
    """Return True if the hearing date falls within the next `days` days from today."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = today + timedelta(days=days)
    normalized = " ".join(date_str.split())
    for fmt in ("%A, %b %d %Y", "%A, %B %d %Y"):
        try:
            dt = datetime.strptime(normalized, fmt)
            return today <= dt < cutoff
        except ValueError:
            continue
    return False


def run(relevant_days: int = 7):
    if not os.path.exists(SCHEDULE_FILE):
        raise FileNotFoundError(f"'{SCHEDULE_FILE}' not found. Run parse.py first.")

    with open(SCHEDULE_FILE, newline="", encoding="utf-8") as f:
        schedule = list(csv.DictReader(f))

    logger.info(f"Loaded {len(schedule)} hearings from {SCHEDULE_FILE}")

    if not schedule:
        logger.info("No hearings to enrich.")
        return

    if not CL_TOKEN:
        logger.warning(
            "No COURTLISTENER_TOKEN in .env — using unauthenticated API (100 req/day limit). "
            "Register free at courtlistener.com to get a token and raise limit to 5,000/day."
        )

    cache = load_cache()
    unique_cases = list({row["case_number"] for row in schedule})
    new_lookups = [c for c in unique_cases if c not in cache]
    logger.info(f"{len(unique_cases)} unique cases ({len(cache)} cached, {len(new_lookups)} to fetch)")

    # Fetch missing cases from CourtListener
    failed_lookups = []
    for i, case_num in enumerate(new_lookups):
        logger.info(f"  [{i+1}/{len(new_lookups)}] Looking up {case_num}...")
        result = fetch_from_courtlistener(case_num)
        if result is None:
            failed_lookups.append(case_num)
        cache[case_num] = result or {"_not_found": True}
        if i < len(new_lookups) - 1:
            time.sleep(CL_DELAY)

    save_cache(cache)
    logger.info(f"Cache saved ({len(cache)} entries).")

    if failed_lookups:
        with open("failed_lookups.txt", "w") as f:
            f.write("\n".join(failed_lookups))
        logger.warning(f"{len(failed_lookups)} case(s) failed CourtListener lookup — saved to failed_lookups.txt")
    elif os.path.exists("failed_lookups.txt"):
        os.remove("failed_lookups.txt")

    # Build enriched rows
    enriched_rows = []
    relevant_rows = []

    for row in schedule:
        cn = row["case_number"]
        cl = cache.get(cn, {})

        is_relevant, reasons = score_relevance(row, cl)

        enriched = {
            "judge": row["judge"],
            "location": row["location"],
            "courtroom": row["courtroom"],
            "date": row["date"],
            "time": row["time"],
            "case_number": cn,
            "case_name": cl.get("case_name", "") if not cl.get("_not_found") else "",
            "nature_of_suit": cl.get("nature_of_suit", ""),
            "nos_code": cl.get("nos_code", ""),
            "cause": cl.get("cause", ""),
            "date_filed": cl.get("date_filed", ""),
            "is_active": cl.get("is_active", ""),
            "cl_url": cl.get("cl_url", ""),
            "relevant": "yes" if is_relevant else "no",
            "relevance_reasons": "; ".join(reasons),
        }
        enriched_rows.append(enriched)
        if is_relevant and _within_days(row["date"], relevant_days):
            relevant_rows.append(enriched)

    with open(ENRICHED_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ENRICHED_FIELDS)
        writer.writeheader()
        writer.writerows(enriched_rows)

    with open(RELEVANT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ENRICHED_FIELDS)
        writer.writeheader()
        writer.writerows(relevant_rows)

    logger.info(f"Wrote {len(enriched_rows)} rows to {ENRICHED_FILE}")
    logger.info(f"Wrote {len(relevant_rows)} relevant cases to {RELEVANT_FILE}")
    logger.info("─" * 60)
    for r in relevant_rows:
        logger.info(f"  {r['date']} | {r['judge']} | {r['case_number']} | {r['case_name']} | {r['relevance_reasons']}")


if __name__ == "__main__":
    run()
