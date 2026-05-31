import os
import json
from datetime import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dotenv import load_dotenv
import config as cfg

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]
SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_ID")
TOKEN_PATH = cfg.TOKEN_PATH

SHEET_URL_CONFIG = cfg.SHEET_URL_CONFIG
SHEET_SEEN_JOBS = cfg.SHEET_SEEN_JOBS
SHEET_ACTION = cfg.SHEET_ACTION


def get_credentials():
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_config(
                {
                    "installed": {
                        "client_id": os.getenv("google_client_id"),
                        "client_secret": os.getenv("google_client_secret"),
                        "redirect_uris": ["http://localhost"],
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                },
                SCOPES,
            )
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json())

    return creds


def get_service():
    return build("sheets", "v4", credentials=get_credentials())


# --- URL Config ---

def read_url_config():
    """Returns list of dicts from the URL Config sheet."""
    service = get_service()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_URL_CONFIG}!A1:Z1000")
        .execute()
    )
    rows = result.get("values", [])
    if not rows:
        return []
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:]]


# --- Seen Jobs ---

def read_seen_job_ids():
    """Returns a set of already-processed job IDs."""
    service = get_service()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_SEEN_JOBS}!A2:A")
        .execute()
    )
    rows = result.get("values", [])
    return {row[0] for row in rows if row}


def add_seen_job(job):
    """Appends a job to the Seen Jobs sheet."""
    service = get_service()
    row = [
        job.get("job_id", ""),
        job.get("title", ""),
        job.get("company", ""),
        job.get("date_first_seen", ""),
        job.get("status", ""),
    ]
    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_SEEN_JOBS}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()


# --- Action CSV ---

def append_action_row(job):
    """Appends a completed job object as a new row in the Action CSV sheet."""
    service = get_service()

    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # A - Date (when row written)
        job.get("source_url_label", ""),      # B - Source
        job.get("geography", ""),             # C - Geography
        job.get("company", ""),               # D - Company
        job.get("title", ""),                 # E - Role
        job.get("score", ""),                 # F - Score
        job.get("reason", ""),                # G - Score Reason
        ", ".join(job.get("red_flags", [])),  # H - Red Flags
        job.get("geo_flag", ""),              # I - Geo Flag
        job.get("apply_url", ""),             # J - Job URL
        job.get("contact_name", ""),          # K - Contact Name
        job.get("contact_title", ""),         # L - Contact Title
        job.get("contact_email", ""),         # M - Contact Email
        job.get("email_confidence", ""),      # N - Email Confidence
        job.get("resume_drive_link", ""),     # O - Resume PDF Link
        job.get("email_subject", ""),         # P - Email Subject
        job.get("email_body", ""),            # Q - Email Body
        job.get("li_connection_note", ""),    # R - LI Connection Note
        job.get("li_followup_message", ""),   # S - LI Followup
        "Pending",                            # T - Status
        "",                                   # U - Date Applied
        "",                                   # V - Notes
        False,                                # W - Send Email (checkbox)
    ]

    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_ACTION}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()
