import os
import sys
import json
import time
import logging
import argparse
from datetime import date
from pathlib import Path

from modules.scraper import scrape_jobs
from modules.deduplicator import filter_new_jobs, mark_jobs_seen
from modules.scorer import score_jobs, filter_qualified
from modules.email_finder import find_contact
from modules.resume_builder import build_resume
from modules.message_writer import write_messages
from modules.sheets import append_action_row

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"run_{date.today()}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def with_retry(fn, *args, retries=2, delay=5, label=""):
    for attempt in range(1, retries + 2):
        try:
            return fn(*args)
        except Exception as e:
            if attempt <= retries:
                log.warning(f"[retry {attempt}/{retries}] {label} failed: {e} — retrying in {delay}s")
                time.sleep(delay)
            else:
                raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="JobBot pipeline")
    parser.add_argument("--test", action="store_true",
                        help="Dry run — skip Drive upload and Sheets write")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap total jobs processed this run")
    parser.add_argument("--score-only", action="store_true",
                        help="Stop after scoring — useful for threshold tuning")
    parser.add_argument("--skip-scrape", action="store_true",
                        help="Skip scraping and use existing data/raw_jobs.json")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run(args):
    stats = {
        "scraped": 0,
        "new": 0,
        "scored_low": 0,
        "no_contact": 0,
        "processed": 0,
        "failed": 0,
    }

    # Step 1 — Scrape
    if args.skip_scrape:
        log.info("[main] Skipping scrape — loading existing raw_jobs.json")
        with open("data/raw_jobs.json") as f:
            raw_jobs = json.load(f)
    else:
        log.info("[main] Step 1 — Scraping jobs...")
        try:
            raw_jobs = scrape_jobs()
        except Exception as e:
            log.error(f"[main] Scraping failed: {e}")
            return
    stats["scraped"] = len(raw_jobs)
    log.info(f"[main] Scraped {stats['scraped']} jobs")

    # Step 2 — Deduplicate
    log.info("[main] Step 2 — Deduplicating...")
    new_jobs = filter_new_jobs(raw_jobs)
    stats["new"] = len(new_jobs)

    if args.limit:
        new_jobs = new_jobs[: args.limit]
        log.info(f"[main] Capped to {args.limit} jobs via --limit")

    if not new_jobs:
        log.info("[main] No new jobs to process. Exiting.")
        return

    # Step 3 — Score
    log.info(f"[main] Step 3 — Scoring {len(new_jobs)} jobs...")
    scored_jobs = score_jobs(new_jobs)

    qualified = filter_qualified(scored_jobs)
    low_score = [j for j in scored_jobs if j not in qualified]

    # Mark low-score jobs as seen so they're not re-scored next run
    mark_jobs_seen(low_score, status="scored_low")
    stats["scored_low"] = len(low_score)

    if args.score_only:
        log.info("[main] --score-only flag set. Stopping after scoring.")
        _print_summary(stats)
        return

    if not qualified:
        log.info("[main] No qualified jobs. Exiting.")
        return

    # Step 4-8 — Per-job processing
    log.info(f"[main] Processing {len(qualified)} qualified jobs...")

    for job in qualified:
        label = f"{job.get('company')} — {job.get('title')}"
        log.info(f"\n[main] ── Processing: {label}")

        try:
            # Step 4 — Find contact
            log.info(f"[main] Step 4 — Finding contact...")
            job = with_retry(find_contact, job, label=f"find_contact({label})")

            if not job.get("contact_email"):
                log.warning(f"[main] No contact found for {label} — skipping")
                mark_jobs_seen([job], status="no_contact")
                stats["no_contact"] += 1
                continue

            if args.test:
                log.info(f"[main] TEST MODE — skipping resume build, messages, sheet write")
                log.info(f"[main] Contact: {job.get('contact_name')} | {job.get('contact_email')}")
                stats["processed"] += 1
                continue

            # Step 5 — Build resume
            log.info(f"[main] Step 5 — Building resume...")
            job = with_retry(build_resume, job, label=f"build_resume({label})")

            # Step 6 — Write messages
            log.info(f"[main] Step 6 — Writing messages...")
            job = with_retry(write_messages, job, label=f"write_messages({label})")

            # Step 7 — Append to action sheet
            log.info(f"[main] Step 7 — Writing to action sheet...")
            with_retry(append_action_row, job, label=f"append_action_row({label})")

            # Step 8 — Mark seen
            mark_jobs_seen([job], status="processed")
            stats["processed"] += 1
            log.info(f"[main] Done: {label}")

        except Exception as e:
            log.error(f"[main] Failed: {label} — {e}")
            stats["failed"] += 1
            # Do NOT mark as seen — will retry next run

    _print_summary(stats)


def _print_summary(stats):
    log.info("\n" + "=" * 50)
    log.info("RUN SUMMARY")
    log.info("=" * 50)
    log.info(f"  Scraped:      {stats['scraped']}")
    log.info(f"  New:          {stats['new']}")
    log.info(f"  Scored low:   {stats['scored_low']}")
    log.info(f"  No contact:   {stats['no_contact']}")
    log.info(f"  Processed:    {stats['processed']}")
    log.info(f"  Failed:       {stats['failed']}")
    log.info("=" * 50)


if __name__ == "__main__":
    args = parse_args()
    run(args)
