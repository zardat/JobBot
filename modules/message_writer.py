import os
import json
import anthropic
from dotenv import load_dotenv
import config as cfg

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

CANDIDATE_NAME = cfg.CANDIDATE_NAME
CANDIDATE_EMAIL = cfg.CANDIDATE_EMAIL
CANDIDATE_LINKEDIN = cfg.CANDIDATE_LINKEDIN


def _signature():
    """Deterministic sign-off built from config — never a Claude placeholder."""
    lines = ["Best,", CANDIDATE_NAME]
    if CANDIDATE_LINKEDIN:
        lines.append(CANDIDATE_LINKEDIN)
    return "\n".join(lines)


def write_messages(job):
    # Use only the recipient's first name in greetings, never the full name.
    full_contact = (job.get("contact_name") or "").strip()
    contact_name = full_contact.split()[0] if full_contact else "there"
    skills = cfg.SKILLS_PATH.read_text()
    projects = cfg.PROJECTS_PATH.read_text()

    prompt = f"""Write outreach messages for a job application. Return JSON only — no explanation outside the JSON.

CANDIDATE: {CANDIDATE_NAME}
CONTACT (recipient first name): {contact_name}
ROLE APPLYING FOR: {job.get('title')} at {job.get('company')}
SCORE REASON: {job.get('reason')}
TAILORING NOTES: {job.get('tailoring_notes', '')}

CANDIDATE SKILLS (ground truth — the ONLY skills the candidate actually knows):
{skills}

CANDIDATE PROJECTS (the ONLY projects/experience the candidate has done):
{projects}

JOB DESCRIPTION (first 1500 chars):
{job.get('description', '')[:1500]}

TRUTHFULNESS RULES (critical):
- ONLY mention skills, tools, and experience that appear in CANDIDATE SKILLS or CANDIDATE PROJECTS above.
- NEVER claim a skill just because the JD asks for it. If the JD wants something the candidate does not have, do not mention it and do not imply familiarity.
- Connect the role to the candidate's REAL strengths (from the skills/projects), even if that means addressing only part of what the JD asks for.
- Do not exaggerate proficiency or invent metrics, years, or accomplishments not present above.

Write these 4 messages:

1. email_subject: Short subject line (under 60 chars), e.g. "Data Scientist Application — {CANDIDATE_NAME}"
2. email_body: A professional cold email. Reference the specific role. Connect 1-2 of the candidate's REAL strengths (from CANDIDATE SKILLS / CANDIDATE PROJECTS) to the JD. State that the resume is attached to this email.
3. li_connection_note: LinkedIn connection request note (max 300 chars). Mention the role and one relevant REAL thing the candidate has done. No fluff.
4. li_followup_message: Follow-up message to send after connection is accepted (2-3 lines). Reference the role and ask for a 15-min chat.

FORMATTING RULES for email_body (important — the email is sent as plain text):
- Start with a greeting on its own line, e.g. "Hi {contact_name}," then a blank line.
- Write 2-3 short paragraphs. Separate every paragraph with a blank line.
- Use real newline characters for the line breaks (in JSON these are \\n). Do NOT return the whole email as one run-on paragraph.
- Do NOT write a sign-off, signature, name, or LinkedIn line — it is added automatically afterwards. End with the last sentence of the body (no "Best," / "Regards,").
- Do NOT include any placeholders or square brackets (no "[Your Name]", "[LinkedIn]", "[resume link]", "[YOUR resume here]", etc.).
- The resume PDF is attached automatically — refer to it as attached, never insert a link or placeholder for it.

Return this exact JSON:
{{
  "email_subject": "...",
  "email_body": "...",
  "li_connection_note": "...",
  "li_followup_message": "..."
}}"""

    message = client.messages.create(
        model=cfg.CLAUDE_MODEL,
        max_tokens=cfg.MESSAGE_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())

    # Append a real signature (name + LinkedIn from config) so the email never
    # ships with a Claude placeholder, with a blank line before it.
    body = (result.get("email_body") or "").rstrip()
    result["email_body"] = f"{body}\n\n{_signature()}"

    job.update(result)
    return job
