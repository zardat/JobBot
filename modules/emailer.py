import re
import html
import base64
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from googleapiclient.discovery import build
import config as cfg
from modules.sheets import get_credentials


def _body_to_html(body):
    """Convert a plain-text body into simple HTML so line breaks and paragraphs
    survive in the recipient's client (plain-text single newlines get collapsed
    by Gmail's format=flowed)."""
    escaped = html.escape(body.strip())
    # Blank line => paragraph break; single newline => <br>.
    paragraphs = re.split(r"\n\s*\n", escaped)
    html_paras = ["<p>{}</p>".format(p.replace("\n", "<br>")) for p in paragraphs if p.strip()]
    return '<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5;">{}</div>'.format(
        "".join(html_paras)
    )


def _file_id(link):
    """Extract a Drive file ID from a share link (…/d/<id>/… or …?id=<id>)."""
    if not link:
        return ""
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", link) or re.search(r"[?&]id=([a-zA-Z0-9_-]+)", link)
    return m.group(1) if m else ""


def _download_pdf(link):
    """Download a publicly-shared Drive PDF. Returns bytes or None.

    Works for both per-job uploads (shared anyone/reader by drive_uploader) and
    the DEFAULT_RESUME_LINK (shared 'anyone with link').
    """
    fid = _file_id(link)
    if not fid:
        print(f"[emailer] No Drive file id in link: {link!r}")
        return None
    url = f"https://drive.google.com/uc?export=download&id={fid}"
    try:
        r = requests.get(url, timeout=30)
    except Exception as e:
        print(f"[emailer] PDF download failed: {e}")
        return None
    if r.ok and r.content[:4] == b"%PDF":
        return r.content
    print(f"[emailer] Drive link did not return a PDF (status {r.status_code})")
    return None


def _gmail_service():
    return build("gmail", "v1", credentials=get_credentials())


def send_application_email(job):
    """Send the application email for a job via the Gmail API, attaching the
    resume PDF downloaded from its Drive link. Raises on failure."""
    to = job.get("contact_email")
    if not to:
        raise RuntimeError("send_application_email called with no contact_email")

    subject = job.get("email_subject", "")
    body = job.get("email_body", "")

    # multipart/mixed (attachment) wrapping a multipart/alternative (text + html)
    # so the formatted HTML renders while a plain-text fallback still exists.
    msg = MIMEMultipart("mixed")
    msg["To"] = to
    msg["From"] = f"{cfg.CANDIDATE_NAME} <{cfg.CANDIDATE_EMAIL}>"
    msg["Subject"] = subject

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(body, "plain"))
    alt.attach(MIMEText(_body_to_html(body), "html"))
    msg.attach(alt)

    pdf = _download_pdf(job.get("resume_drive_link", ""))
    if pdf:
        part = MIMEApplication(pdf, _subtype="pdf")
        part.add_header("Content-Disposition", "attachment",
                        filename=cfg.RESUME_ATTACHMENT_NAME)
        msg.attach(part)
    else:
        print("[emailer] WARNING: sending without a resume attachment")

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    _gmail_service().users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"[emailer] Sent application to {to}")
