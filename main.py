import os
import sys
import json
import time
import logging
import argparse
from datetime import date, datetime

import config as cfg
from modules.scraper import scrape_jobs
from modules.deduplicator import filter_new_jobs, mark_jobs_seen
from modules.scorer import score_job
from modules.email_finder import find_contact
from modules.resume_builder import build_resume
from modules.message_writer import write_messages
from modules.sheets import append_action_row
from modules.emailer import send_application_email

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = cfg.LOG_DIR
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

def with_retry(fn, *args, retries=cfg.RETRY_COUNT, delay=cfg.RETRY_DELAY, label=""):
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
        "company_duplicate": 0,
        "qualified": 0,
        "no_contact": 0,
        "processed": 0,
        "emailed": 0,
        "failed": 0,
    }

    # Step 1 — Scrape
    if args.skip_scrape:
        log.info("[main] Skipping scrape — loading existing raw_jobs.json")
        with open(cfg.RAW_JOBS_PATH) as f:
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
        log.info(f"[main] --limit {args.limit}: will stop after {args.limit} jobs are added to the action sheet")

    if not new_jobs:
        log.info("[main] No new jobs to process. Exiting.")
        return

    # Step 3-8 — Score and fully process each job in a single pass
    log.info(f"[main] Processing {len(new_jobs)} jobs one at a time...")

    # Companies already emailed/processed this run — used to avoid sending
    # multiple mails to the same person when a company posts several similar jobs.
    processed_companies = set()

    for job in new_jobs:
        # --limit caps successful jobs (rows added to the action sheet), not
        # jobs scanned — keep scoring/skipping until that many succeed.
        if args.limit and stats["processed"] >= args.limit:
            log.info(f"[main] Reached --limit ({args.limit}) jobs added to sheet — stopping")
            break

        label = f"{job.get('company')} — {job.get('title')}"
        log.info(f"\n[main] ── {label}")

        # One application per company per run — if we already processed another
        # posting from this company, skip this one (mark seen, no second email).
        company_key = (job.get("company") or "").strip().lower()
        if company_key and company_key in processed_companies:
            log.info(f"[main] Already applied to {job.get('company')} this run — skipping duplicate")
            mark_jobs_seen([job], status="company_duplicate")
            stats["company_duplicate"] += 1
            continue

        # Step 3 — Score
        try:
            log.info(f"[main] Step 3 — Scoring...")
            job = score_job(job)
            log.info(f"[main] score={job.get('score')} apply={job.get('apply')}")
        except Exception as e:
            # Real error (not an information outcome) — do NOT mark seen, retry next run
            log.error(f"[main] Scoring failed: {label} — {e}")
            stats["failed"] += 1
            continue

        # Qualify check — skip low-scored jobs and mark them seen
        qualified = job.get("apply") and job.get("score", 0) >= cfg.SCORE_THRESHOLD
        if not qualified:
            log.info(f"[main] Below threshold ({cfg.SCORE_THRESHOLD}) — skipping")
            mark_jobs_seen([job], status="scored_low")
            stats["scored_low"] += 1
            continue

        stats["qualified"] += 1

        # --score-only: stop here for qualified jobs (don't mark seen, so a real
        # run still processes them later)
        if args.score_only:
            log.info(f"[main] --score-only — qualified, not processing")
            continue

        # Step 4-8 — Full processing
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

            # Step 7 — Send email automatically (optional), then append the row
            if cfg.AUTO_EMAIL:
                log.info(f"[main] Step 7 — Auto-emailing {job.get('contact_email')}...")
                with_retry(send_application_email, job, label=f"send_email({label})")
                applied_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with_retry(
                    lambda j: append_action_row(j, status="Emailed", date_applied=applied_at),
                    job, label=f"append_action_row({label})",
                )
                stats["emailed"] += 1
            else:
                log.info(f"[main] Step 7 — Writing to action sheet...")
                with_retry(append_action_row, job, label=f"append_action_row({label})")

            # Step 8 — Mark seen
            mark_jobs_seen([job], status="processed")
            stats["processed"] += 1
            if company_key:
                processed_companies.add(company_key)
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
    log.info(f"  Co. dup:      {stats['company_duplicate']}")
    log.info(f"  Qualified:    {stats['qualified']}")
    log.info(f"  No contact:   {stats['no_contact']}")
    log.info(f"  Processed:    {stats['processed']}")
    log.info(f"  Emailed:      {stats['emailed']}")
    log.info(f"  Failed:       {stats['failed']}")
    log.info("=" * 50)


if __name__ == "__main__":
    args = parse_args()
    run(args)
