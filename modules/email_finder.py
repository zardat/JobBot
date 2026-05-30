import os
import json
import requests
import anthropic
from dotenv import load_dotenv

load_dotenv()

PROSPEO_KEY = os.getenv("PROSPEO_API_KEY")
PROSPEO_BASE = "https://api.prospeo.io"

HR_TITLES = ["HR Manager", "Recruiter", "Talent Acquisition", "Hiring Manager",
             "Technical Recruiter", "HR Business Partner", "Recruitment Lead" ,"Human Resource"]

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _search_people(company_domain=None, company_name=None):
    company_filter = {}
    if company_domain:
        company_filter["websites"] = {"include": [company_domain]}
    if company_name:
        company_filter["names"] = {"include": [company_name]}

    resp = requests.post(
        f"{PROSPEO_BASE}/search-person",
        headers={"X-KEY": PROSPEO_KEY, "Content-Type": "application/json"},
        json={
            "page": 1,
            "filters": {
                "company": company_filter,
                "person_job_title": {"include": HR_TITLES},
            },
        },
    )
    if not resp.ok:
        raise RuntimeError(f"Prospeo search failed {resp.status_code}: {resp.text}")
    data = resp.json()
    return data.get("results", [])


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
2. Otherwise pick the most senior HR/TA/Recruiter relevant to tech/engineering hiring
3. Avoid generic HR roles unrelated to tech recruiting if better options exist

Return JSON only:
{{
  "person_id": "...",
  "full_name": "...",
  "title": "..."
}}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
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
        f"{PROSPEO_BASE}/enrich-person",
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


def find_contact(job):
    domain = job.get("company_domain", "").replace("https://", "").replace("http://", "").rstrip("/")
    company_name = job.get("company", "")

    # Try company name first, fall back to domain
    results = []
    if company_name:
        print(f"[email_finder] Searching by company name: {company_name}...")
        results = _search_people(company_name=company_name)

    if not results and domain:
        print(f"[email_finder] No results by name — trying domain: {domain}...")
        results = _search_people(company_domain=domain)

    if not results:
        print(f"[email_finder] No contacts found for {company_name}")
        job["contact_email"] = ""
        job["email_confidence"] = "not_found"
        job["contact_name"] = ""
        job["contact_title"] = ""
        return job

    print(f"[email_finder] {len(results)} contacts found — sample: {results[0].get('person', {})}")
    print(f"[email_finder] Claude picking best match...")
    chosen = _pick_best_contact(results, job)

    print(f"[email_finder] Enriching {chosen.get('full_name')} ({chosen.get('title')})...")
    enriched = _enrich_person(chosen["person_id"])

    job["contact_name"] = chosen.get("full_name", "")
    job["contact_title"] = chosen.get("title", "")
    job["contact_email"] = enriched.get("email", "")
    job["email_confidence"] = enriched.get("status", "").lower()

    print(f"[email_finder] → {job['contact_name']} | {job['contact_email']} ({job['email_confidence']})")
    return job
