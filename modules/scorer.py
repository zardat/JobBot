import os
import json
import anthropic
from dotenv import load_dotenv
import config as cfg

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def score_job(job):
    skills = cfg.SKILLS_PATH.read_text()
    projects = cfg.PROJECTS_PATH.read_text()

    exp_rule = ""
    if cfg.MAX_YEARS_EXPERIENCE is not None:
        exp_rule = (
            f'- score 0 and apply false if the JD requires MORE than '
            f'{cfg.MAX_YEARS_EXPERIENCE} years of experience. Read the minimum '
            f'required years from the JD (e.g. "5+ years", "6-8 years", '
            f'"minimum 5 years"). If the minimum exceeds '
            f'{cfg.MAX_YEARS_EXPERIENCE}, reject. If no specific experience '
            f'requirement is stated, do not reject on this rule.\n'
        )

    prompt = f"""You are evaluating a job posting for a candidate. Analyze the fit and return a JSON response only — no explanation outside the JSON.

CANDIDATE SKILLS (ground truth — the ONLY skills the candidate actually knows):
{skills}

CANDIDATE EXPERIENCE & PROJECTS (work history, research, and personal projects):
{projects}

JOB DETAILS:
Title: {job.get('title')}
Company: {job.get('company')}
Location: {job.get('location')}
Geography context: {job.get('geography')}
Description:
{job.get('description')}

SCORING RULES:
- Score 1-10 based on skills match, experience level, and role alignment. Judge skill match ONLY against the CANDIDATE SKILLS list above — skills mentioned in the JD but absent from that list count as gaps, not strengths.
- score 0 and apply false if JD contains: "must be authorized to work in the US", "US citizens only", "active security clearance required"
{exp_rule}- geo_flag = "Timezone Risk" if hard EST/PST requirement with no async option mentioned
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
        model=cfg.CLAUDE_MODEL,
        max_tokens=cfg.SCORER_MAX_TOKENS,
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
    qualified = [j for j in scored_jobs if j.get("apply") and j.get("score", 0) >= cfg.SCORE_THRESHOLD]
    print(f"[scorer] {len(qualified)}/{len(scored_jobs)} jobs passed threshold ({cfg.SCORE_THRESHOLD}+)")
    return qualified
