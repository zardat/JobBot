import os
import json
import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

CANDIDATE_NAME = "Parth Joshi"
CANDIDATE_EMAIL = "paarthjoshi20@gmail.com"
CANDIDATE_LINKEDIN = "https://www.linkedin.com/in/parth-joshi-6459a2235/"


def write_messages(job):
    prompt = f"""Write outreach messages for a job application. Return JSON only — no explanation outside the JSON.

CANDIDATE: {CANDIDATE_NAME}
ROLE APPLYING FOR: {job.get('title')} at {job.get('company')}
SCORE REASON: {job.get('reason')}
TAILORING NOTES: {job.get('tailoring_notes', '')}

JOB DESCRIPTION (first 1500 chars):
{job.get('description', '')[:1500]}

Write these 4 messages:

1. email_subject: Short subject line (under 60 chars), e.g. "Data Scientist Application — Parth Joshi"
2. email_body: 4-6 line professional cold email. Reference the specific role. Connect 1-2 candidate strengths to the JD. Mention the tailored resume is attached. Sign off with name and LinkedIn.
3. li_connection_note: LinkedIn connection request note (max 300 chars). Mention the role and one relevant thing. No fluff.
4. li_followup_message: Follow-up message to send after connection is accepted (2-3 lines). Reference the role and ask for a 15-min chat.

Return this exact JSON:
{{
  "email_subject": "...",
  "email_body": "...",
  "li_connection_note": "...",
  "li_followup_message": "..."
}}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
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
