import os
import json
import anthropic
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

SCORE_THRESHOLD = 7
RESUME_PATH = Path(__file__).parent.parent / "resume.tex"

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def score_job(job):
    resume = RESUME_PATH.read_text()

    prompt = f"""You are evaluating a job posting for a candidate. Analyze the fit and return a JSON response only — no explanation outside the JSON.

CANDIDATE RESUME (LaTeX):
{resume}

JOB DETAILS:
Title: {job.get('title')}
Company: {job.get('company')}
Location: {job.get('location')}
Geography context: {job.get('geography')}
Description:
{job.get('description')}

SCORING RULES:
- Score 1-10 based on skills match, experience level, and role alignment
- score 0 and apply false if JD contains: "must be authorized to work in the US", "US citizens only", "active security clearance required"
- geo_flag = "Timezone Risk" if hard EST/PST requirement with no async option mentioned
- tailoring_notes: specific instructions on what to emphasize in the resume for this JD

Return this exact JSON:
{{
  "score": <int 1-10>,
  "reason": "<one line explanation>",
  "apply": <true|false>,
  "geo_flag": <null or "Timezone Risk" or "US Only">,
  "tailoring_notes": "<what to emphasize or reorder in resume>",
  "red_flags": ["<flag1>", "<flag2>"]
}}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())

    job.update(result)
    return job


def score_jobs(jobs):
    scored = []
    for job in jobs:
        try:
            scored_job = score_job(job)
            status = f"score={scored_job['score']} apply={scored_job['apply']}"
            print(f"[scorer] {job['company']} — {job['title']} → {status}")
            scored.append(scored_job)
        except Exception as e:
            print(f"[scorer] Failed for {job.get('company')} — {job.get('title')}: {e}")
    return scored


def filter_qualified(scored_jobs):
    qualified = [j for j in scored_jobs if j.get("apply") and j.get("score", 0) >= SCORE_THRESHOLD]
    print(f"[scorer] {len(qualified)}/{len(scored_jobs)} jobs passed threshold ({SCORE_THRESHOLD}+)")
    return qualified
