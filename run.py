"""
run.py — Orchestrate the full Docket Monster pipeline.

Usage:
  python run.py                        # full run (schedule=14d, relevant=7d)
  python run.py --no-scrape            # skip scraping, use existing raw_html/
  python run.py --days 21              # wider schedule/enriched window
  python run.py --relevant-days 14     # wider relevant window
  python run.py --dry-run              # parse only, no live requests

Steps:
  1. scraper.py — fetch per-judge calendar HTML (skipped with --no-scrape/--dry-run)
  2. parse.py   — extract (judge, date, time, case_number) → schedule.csv
  3. enrich.py  — CourtListener lookup (next N days only) → enriched.csv, relevant.csv
"""

import sys
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    args = sys.argv[1:]
    arg_set = set(args)
    skip_scrape = "--no-scrape" in arg_set or "--dry-run" in arg_set
    dry_run = "--dry-run" in arg_set

    days = 14        # schedule/enriched window
    relevant_days = 7  # relevant.csv window (coming week only)
    for i, arg in enumerate(args):
        if arg == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
        if arg == "--relevant-days" and i + 1 < len(args):
            relevant_days = int(args[i + 1])

    logger.info("=" * 60)
    logger.info(f"Docket Monster — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if dry_run:
        logger.info("Mode: DRY RUN (no live requests)")
    elif skip_scrape:
        logger.info(f"Mode: parse + enrich only (schedule={days}d, relevant={relevant_days}d)")
    else:
        logger.info(f"Mode: full run (schedule={days}d, relevant={relevant_days}d)")
    logger.info("=" * 60)

    # Step 1 — Scrape
    if not skip_scrape:
        logger.info("\n── Step 1: Scraping judge calendars ──")
        import scraper
        judges = scraper.get_judge_list()
        scraper.fetch_all_calendars(judges)
    else:
        logger.info("\n── Step 1: Skipped (using cached raw_html/) ──")

    # Step 2 — Parse (filter to window here)
    logger.info(f"\n── Step 2: Parsing calendar HTML (next {days} days) ──")
    import parse
    parse.run(days=days)

    # Step 3 — Enrich
    if not dry_run:
        logger.info("\n── Step 3: Enriching with CourtListener ──")
        import enrich
        enrich.run(relevant_days=relevant_days)
    else:
        logger.info("\n── Step 3: Skipped (dry run) ──")

    logger.info("\n" + "=" * 60)
    logger.info("Done.")
    if not dry_run:
        logger.info("  schedule.csv  — all hearings (scraper output)")
        logger.info("  enriched.csv  — all hearings with CourtListener data")
        logger.info("  relevant.csv  — filtered to tech/privacy cases")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
