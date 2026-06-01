import os
import time
import json
import requests
import anthropic
from dotenv import load_dotenv
import config as cfg

load_dotenv()

PROSPEO_KEY = os.getenv("PROSPEO_API_KEY")

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Timestamp of the last Prospeo search call, used to space out requests so we
# stay under the search endpoint's 1/sec rate limit.
_last_search_ts = 0.0


def _throttle_search():
    """Sleep just enough so consecutive search calls are spaced out."""
    global _last_search_ts
    elapsed = time.time() - _last_search_ts
    wait = cfg.PROSPEO_SEARCH_MIN_INTERVAL - elapsed
    if wait > 0:
        time.sleep(wait)
    _last_search_ts = time.time()


def _is_rate_limit(resp):
    if resp.status_code == 429:
        return True
    try:
        return "rate limit" in resp.json().get("error_code", "").lower()
    except Exception:
        return False


def _clean_domain(raw):
    """Reduce a company website to a bare root domain Prospeo will accept.

    e.g. 'https://www.sabre.com/about' -> 'sabre.com'. Prospeo rejects schemes,
    paths, and subdomains (including 'www.').
    """
    if not raw:
        return ""
    d = raw.strip().split("://", 1)[-1]   # drop scheme
    d = d.split("/", 1)[0]                  # drop path
    d = d.split("?", 1)[0]                  # drop query
    if d.startswith("www."):
        d = d[4:]
    return d.strip().lower()


def _search_people(company_domain=None, company_name=None, titles=None):
    """Search people at a company. If `titles` is given, restrict to those job
    titles; otherwise return anyone at the company.

    Prospeo signals "nobody matched" with HTTP 400 + error_code NO_RESULTS — we
    treat that as an empty list rather than an error so callers can fall back.
    """
    company_filter = {}
    if company_domain:
        company_filter["websites"] = {"include": [company_domain]}
    if company_name:
        company_filter["names"] = {"include": [company_name]}

    filters = {"company": company_filter}
    if titles:
        filters["person_job_title"] = {"include": titles}

    for attempt in range(cfg.PROSPEO_RATE_LIMIT_RETRIES + 1):
        _throttle_search()
        resp = requests.post(
            f"{cfg.PROSPEO_BASE}/search-person",
            headers={"X-KEY": PROSPEO_KEY, "Content-Type": "application/json"},
            json={"page": 1, "filters": filters},
        )
        if resp.ok:
            return resp.json().get("results", [])

        # Rate limited — back off and retry within this call (the limit is
        # per-second/per-minute, so a short wait clears it).
        if _is_rate_limit(resp) and attempt < cfg.PROSPEO_RATE_LIMIT_RETRIES:
            print(f"[email_finder] Prospeo rate limit — waiting {cfg.PROSPEO_RATE_LIMIT_BACKOFF}s "
                  f"(attempt {attempt + 1}/{cfg.PROSPEO_RATE_LIMIT_RETRIES})")
            time.sleep(cfg.PROSPEO_RATE_LIMIT_BACKOFF)
            continue

        try:
            err_code = resp.json().get("error_code", "")
        except Exception:
            err_code = ""
        # "Nobody matched" and "bad filter" (e.g. an unusable company domain) are
        # not fatal — return empty so the caller can fall back / broaden.
        if err_code in ("NO_RESULTS", "INVALID_FILTERS"):
            if err_code == "INVALID_FILTERS":
                print(f"[email_finder] Prospeo rejected filter: {resp.text}")
            return []
        # Other errors propagate so the caller's retry can kick in.
        raise RuntimeError(f"Prospeo search failed {resp.status_code}: {resp.text}")


def _search_company(company_name, domain, titles):
    """Search by company name first, fall back to domain if name yields nothing."""
    results = []
    if company_name:
        kind = f"titles={len(titles)}" if titles else "any title"
        print(f"[email_finder] Searching {company_name} ({kind})...")
        results = _search_people(company_name=company_name, titles=titles)
    if not results and domain:
        print(f"[email_finder] No results by name — trying domain: {domain}...")
        results = _search_people(company_domain=domain, titles=titles)
    return results


def _email_status(result):
    """Email status string from a search result (e.g. VERIFIED / UNAVAILABLE)."""
    person = result.get("person", result)
    return ((person.get("email") or {}).get("status") or "").upper()


def _with_reachable_email(results):
    """Keep only people whose search result shows an email is on file."""
    keep = []
    for r in results:
        status = _email_status(r)
        if status and status not in cfg.EMAIL_UNAVAILABLE_STATUSES:
            keep.append(r)
    return keep


def _pick_best_contact(results, job):
    people_list = []
    for r in results:
        p = r.get("person", r)
        people_list.append({
            "person_id": p.get("person_id", "") or r.get("person_id", ""),
            "full_name": p.get("full_name", "") or r.get("full_name", ""),
            "title": p.get("current_job_title", "") or r.get("current_job_title", ""),
            "headline": p.get("headline", "") or r.get("headline", ""),
        })

    prompt = f"""You are selecting the best person to cold email for a job application.
Every person listed below already has a reachable email on file.

JOB DETAILS:
Title: {job.get('title')}
Company: {job.get('company')}
Poster Name (if available): {job.get('poster_name', 'unknown')}
Poster Title (if available): {job.get('poster_title', 'unknown')}

RAW JOB DESCRIPTION SNIPPET (may contain hiring team clues):
{job.get('description', '')[:800]}

PEOPLE FOUND AT COMPANY:
{json.dumps(people_list, indent=2)}

Pick the single best person to email. Priority:
1. If poster_name matches or partially matches anyone in the list — pick them
2. Otherwise prefer an HR / Talent Acquisition / Recruiter relevant to tech hiring
3. If no recruiter is present, pick the most relevant hiring decision-maker
   (hiring manager, engineering lead, or a founder/CEO at a small company)

Return JSON only:
{{
  "person_id": "...",
  "full_name": "...",
  "title": "..."
}}"""

    message = client.messages.create(
        model=cfg.CLAUDE_MODEL,
        max_tokens=cfg.EMAIL_PICKER_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def _enrich_person(person_id):
    resp = requests.post(
        f"{cfg.PROSPEO_BASE}/enrich-person",
        headers={"X-KEY": PROSPEO_KEY, "Content-Type": "application/json"},
        json={"only_verified_email": False, "data": {"person_id": person_id}},
    )
    if not resp.ok:
        raise RuntimeError(f"Prospeo enrich failed {resp.status_code}: {resp.text}")
    data = resp.json()
    email_obj = data.get("person", {}).get("email", {})
    return {
        "email": email_obj.get("email", ""),
        "status": email_obj.get("status", ""),
    }


def _mark_no_contact(job):
    job["contact_email"] = ""
    job["email_confidence"] = "not_found"
    job["contact_name"] = ""
    job["contact_title"] = ""
    return job


def find_contact(job):
    domain = _clean_domain(job.get("company_domain", ""))
    company_name = job.get("company", "")

    # Tier 1 — prioritise HR / recruiters.
    results = _search_company(company_name, domain, cfg.HR_TITLES)
    candidates = _with_reachable_email(results)
    tier = "HR"

    # Tier 2 — no HR (or none with an email): broaden to anyone at the company.
    if not candidates and cfg.BROADEN_SEARCH_WHEN_NO_HR:
        print(f"[email_finder] No HR with email — broadening search at {company_name}...")
        results = _search_company(company_name, domain, None)
        candidates = _with_reachable_email(results)
        tier = "broadened"

    if not candidates:
        print(f"[email_finder] No reachable contact found for {company_name}")
        return _mark_no_contact(job)

    print(f"[email_finder] {len(candidates)} reachable contact(s) [{tier}] — Claude picking best...")
    chosen = _pick_best_contact(candidates, job)

    print(f"[email_finder] Enriching {chosen.get('full_name')} ({chosen.get('title')})...")
    enriched = _enrich_person(chosen["person_id"])

    if not enriched.get("email"):
        print(f"[email_finder] Enrich returned no email for {chosen.get('full_name')}")
        return _mark_no_contact(job)

    job["contact_name"] = chosen.get("full_name", "")
    job["contact_title"] = chosen.get("title", "")
    job["contact_email"] = enriched.get("email", "")
    job["email_confidence"] = enriched.get("status", "").lower()

    print(f"[email_finder] → {job['contact_name']} | {job['contact_email']} ({job['email_confidence']})")
    return job
