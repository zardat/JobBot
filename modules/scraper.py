import os
import json
import time
import requests
from datetime import date
from dotenv import load_dotenv
import config as cfg
from modules.sheets import read_url_config

load_dotenv()

APIFY_TOKEN = os.getenv("APIFY_TOKEN")


def _run_actor(search_url, max_jobs):
    payload = {
        "urls": [search_url],
        "count": max_jobs,
        "scrapeCompany": cfg.SCRAPE_COMPANY,
        "splitByLocation": cfg.SPLIT_BY_LOCATION,
    }
    if cfg.SPLIT_BY_LOCATION and cfg.SPLIT_COUNTRY:
        payload["splitCountry"] = cfg.SPLIT_COUNTRY

    resp = requests.post(
        f"{cfg.APIFY_BASE_URL}/acts/{cfg.APIFY_ACTOR_ID}/runs",
        params={"token": APIFY_TOKEN},
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()["data"]


def _wait_for_run(run_id, poll_interval=None, timeout=None):
    poll_interval = poll_interval or cfg.APIFY_POLL_INTERVAL
    timeout = timeout or cfg.APIFY_RUN_TIMEOUT
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(
            f"{cfg.APIFY_BASE_URL}/actor-runs/{run_id}",
            params={"token": APIFY_TOKEN},
        )
        resp.raise_for_status()
        run = resp.json()["data"]
        status = run["status"]
        if status == "SUCCEEDED":
            return run
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Apify run {run_id} ended with status: {status}")
        time.sleep(poll_interval)
    raise TimeoutError(f"Apify run {run_id} did not finish within {timeout}s")


def _fetch_dataset(dataset_id):
    resp = requests.get(
        f"{cfg.APIFY_BASE_URL}/datasets/{dataset_id}/items",
        params={"token": APIFY_TOKEN, "format": "json", "clean": "true"},
    )
    resp.raise_for_status()
    return resp.json()


def scrape_jobs(max_per_url=None, max_total=None):
    """Scrape jobs from all active URLs in the url_config sheet.

    max_per_url: overrides the sheet's `max_jobs` column for every URL.
                 Defaults to config.MAX_JOBS_PER_URL_OVERRIDE.
    max_total:   caps total jobs scraped across all URLs (stops calling Apify
                 once reached). Defaults to config.MAX_TOTAL_JOBS.
    """
    if max_per_url is None:
        max_per_url = cfg.MAX_JOBS_PER_URL_OVERRIDE
    if max_total is None:
        max_total = cfg.MAX_TOTAL_JOBS

    url_configs = [u for u in read_url_config() if u.get("active", "").upper() == "TRUE"]
    print(f"[scraper] {len(url_configs)} active URLs found")
    if max_per_url:
        print(f"[scraper] max-per-url override: {max_per_url} jobs/URL")
    if max_total:
        print(f"[scraper] max-total cap: {max_total} jobs across all URLs")

    all_jobs = []
    today = str(date.today())

    for config in url_configs:
        label = config.get("label", "")
        url = config.get("url", "")
        geography = config.get("geography", "")

        if max_per_url:
            max_jobs = max_per_url
        else:
            max_jobs = int(config.get("max_jobs", cfg.DEFAULT_MAX_JOBS_PER_URL))

        # Respect the global cap: only request what's still needed, stop early.
        if max_total is not None:
            remaining = max_total - len(all_jobs)
            if remaining <= 0:
                print(f"[scraper] Reached max-total ({max_total}) — skipping remaining URLs")
                break
            max_jobs = min(max_jobs, remaining)

        print(f"[scraper] Running actor for: {label} (max {max_jobs} jobs)...")

        run = _run_actor(url, max_jobs)
        run_id = run["id"]
        dataset_id = run["defaultDatasetId"]

        print(f"[scraper] Run started: {run_id} — waiting for completion...")
        _wait_for_run(run_id)

        items = _fetch_dataset(dataset_id)
        print(f"[scraper] {len(items)} jobs fetched for: {label}")

        for item in items:
            all_jobs.append({
                "job_id": str(item.get("id", "")),
                "title": item.get("title", ""),
                "company": item.get("companyName", ""),
                "company_domain": item.get("companyWebsite", ""),
                "company_linkedin_url": item.get("companyLinkedinUrl", ""),
                "location": item.get("location", ""),
                "country": item.get("country", ""),
                "work_mode": (item.get("workplaceTypes") or [""])[0],
                "employment_type": item.get("employmentType", ""),
                "seniority_level": item.get("seniorityLevel", ""),
                "posted_date": item.get("postedAt", ""),
                "description": item.get("descriptionText", ""),
                "salary": item.get("salary", ""),
                "apply_url": item.get("link", ""),
                "applicants_count": item.get("applicantsCount", ""),
                "poster_name": "",
                "poster_linkedin": "",
                "poster_title": "",
                "source_url_label": label,
                "geography": geography,
                "date_first_seen": today,
            })

        # Safety trim in case the actor returned more than requested.
        if max_total is not None and len(all_jobs) >= max_total:
            all_jobs = all_jobs[:max_total]
            print(f"[scraper] Reached max-total ({max_total}) — stopping")
            break

    with open(cfg.RAW_JOBS_PATH, "w") as f:
        json.dump(all_jobs, f, indent=2)

    print(f"[scraper] Done. {len(all_jobs)} total jobs saved to {cfg.RAW_JOBS_PATH}")
    return all_jobs


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "fetch":
        dataset_id = sys.argv[2]
        items = _fetch_dataset(dataset_id)
        print(f"Fetched {len(items)} items")
        print(json.dumps(items[:2], indent=2))
    else:
        scrape_jobs()
