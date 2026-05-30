import os
import json
import time
import requests
from datetime import date
from dotenv import load_dotenv
from modules.sheets import read_url_config

load_dotenv()

APIFY_TOKEN = os.getenv("APIFY_TOKEN")
ACTOR_ID = "curious_coder~linkedin-jobs-scraper"
RAW_JOBS_PATH = "data/raw_jobs.json"

BASE_URL = "https://api.apify.com/v2"

# --- Actor parameters ---
SCRAPE_COMPANY = True      # fetch extra company info (slower but richer data)
SPLIT_BY_LOCATION = False  # split search by city (useful if >1000 results expected)
SPLIT_COUNTRY = None       # e.g. "US", "IN" — only used if SPLIT_BY_LOCATION=True


def _run_actor(search_url, max_jobs):
    payload = {
        "urls": [search_url],
        "count": max_jobs,
        "scrapeCompany": SCRAPE_COMPANY,
        "splitByLocation": SPLIT_BY_LOCATION,
    }
    if SPLIT_BY_LOCATION and SPLIT_COUNTRY:
        payload["splitCountry"] = SPLIT_COUNTRY

    resp = requests.post(
        f"{BASE_URL}/acts/{ACTOR_ID}/runs",
        params={"token": APIFY_TOKEN},
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()["data"]


def _wait_for_run(run_id, poll_interval=10, timeout=600):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(
            f"{BASE_URL}/actor-runs/{run_id}",
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
        f"{BASE_URL}/datasets/{dataset_id}/items",
        params={"token": APIFY_TOKEN, "format": "json", "clean": "true"},
    )
    resp.raise_for_status()
    return resp.json()


def scrape_jobs():
    url_configs = [u for u in read_url_config() if u.get("active", "").upper() == "TRUE"]
    print(f"[scraper] {len(url_configs)} active URLs found")

    all_jobs = []
    today = str(date.today())

    for config in url_configs:
        label = config.get("label", "")
        url = config.get("url", "")
        max_jobs = int(config.get("max_jobs", 25))
        geography = config.get("geography", "")

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

    with open(RAW_JOBS_PATH, "w") as f:
        json.dump(all_jobs, f, indent=2)

    print(f"[scraper] Done. {len(all_jobs)} total jobs saved to {RAW_JOBS_PATH}")
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
