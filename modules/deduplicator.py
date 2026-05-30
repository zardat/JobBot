from modules.sheets import read_seen_job_ids, add_seen_job


def filter_new_jobs(jobs):
    seen_ids = read_seen_job_ids()
    print(f"[deduplicator] {len(seen_ids)} jobs already seen")

    new_jobs = [j for j in jobs if j.get("job_id") not in seen_ids]
    print(f"[deduplicator] {len(new_jobs)} new jobs out of {len(jobs)} scraped")

    return new_jobs


def mark_jobs_seen(jobs, status="pending"):
    for job in jobs:
        add_seen_job({**job, "status": status})
    print(f"[deduplicator] {len(jobs)} jobs marked as seen")
