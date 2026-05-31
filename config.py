"""Central configuration for JobBot.

All tunable parameters live here so you can change behaviour without editing
module code. Secrets (API keys, IDs) stay in `.env` — this file is for
non-secret settings only and is safe to commit.

Edit the values below, then run `python main.py` as usual.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (resolved relative to this file — don't usually need to change these)
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent

RESUME_PATH = BASE_DIR / "resume.tex"
PROJECTS_PATH = BASE_DIR / "projects.md"
RESUMES_OUTPUT_DIR = BASE_DIR / "data" / "resumes"
RAW_JOBS_PATH = str(BASE_DIR / "data" / "raw_jobs.json")
TOKEN_PATH = BASE_DIR / "token.json"
LOG_DIR = BASE_DIR / "logs"

# ---------------------------------------------------------------------------
# Scraper (Apify)
# ---------------------------------------------------------------------------

APIFY_ACTOR_ID = "curious_coder~linkedin-jobs-scraper"
APIFY_BASE_URL = "https://api.apify.com/v2"

# Extra company info per job (slower, richer data)
SCRAPE_COMPANY = True
# Split a search by city — useful only if a single URL yields >1000 results
SPLIT_BY_LOCATION = False
SPLIT_COUNTRY = None              # e.g. "US", "IN" — only used if SPLIT_BY_LOCATION

# How many jobs to scrape per URL when the sheet's `max_jobs` column is blank
DEFAULT_MAX_JOBS_PER_URL = 25
# Set to an int to override the sheet's `max_jobs` for EVERY URL (None = use sheet)
MAX_JOBS_PER_URL_OVERRIDE = None
# Set to an int to cap TOTAL jobs scraped across all URLs (None = no cap).
# Apify stops being called once this many jobs are collected, so it saves cost.
MAX_TOTAL_JOBS = 200

# Apify run polling
APIFY_POLL_INTERVAL = 10          # seconds between status checks
APIFY_RUN_TIMEOUT = 600           # max seconds to wait for one actor run

# ---------------------------------------------------------------------------
# Claude (AI) — used for scoring, contact picking, resume tailoring, messages
# ---------------------------------------------------------------------------

CLAUDE_MODEL = "claude-haiku-4-5-20251001"

SCORER_MAX_TOKENS = 512
EMAIL_PICKER_MAX_TOKENS = 256
RESUME_MAX_TOKENS = 8096
MESSAGE_MAX_TOKENS = 1024

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

SCORE_THRESHOLD = 7               # minimum score to proceed past scoring

# Reject jobs that require more than this many years of experience. The scorer
# forces score=0 / apply=false when the JD's minimum required experience exceeds
# this. Set to None to disable the cap.
MAX_YEARS_EXPERIENCE = 4

# ---------------------------------------------------------------------------
# Resume builder (LaTeX)
# ---------------------------------------------------------------------------

# Generate a fresh tailored resume per job (Claude + pdflatex + Drive upload).
# Set to False to PAUSE per-job generation entirely — every job then reuses the
# single default resume below (no Claude call, no compile, no upload).
MAKE_RESUME = False
# Drive link to the resume used for every job when MAKE_RESUME is False.
DEFAULT_RESUME_LINK = "https://drive.google.com/file/d/1lWkjjseUNtntC72sQXbgcuhxNs9NuDwP/view?usp=sharing"

LATEX_COMPILER = "pdflatex"
LATEX_PASSES = 2                  # compile twice so cross-refs/LastPage resolve

# ---------------------------------------------------------------------------
# Email finder (Prospeo)
# ---------------------------------------------------------------------------

PROSPEO_BASE = "https://api.prospeo.io"
HR_TITLES = [
    "HR Manager", "Recruiter", "Talent Acquisition", "Hiring Manager",
    "Technical Recruiter", "HR Business Partner", "Recruitment Lead",
    "Human Resource",
]
# If no HR/recruiter is found at a company, search the company with no title
# filter and let Claude pick the best contact (hiring manager, founder, etc.).
BROADEN_SEARCH_WHEN_NO_HR = True
# Email statuses from Prospeo search that mean "no email on file" — people with
# these are dropped before we spend an enrich credit.
EMAIL_UNAVAILABLE_STATUSES = {"UNAVAILABLE"}

# ---------------------------------------------------------------------------
# Candidate identity (used in outreach messages)
# ---------------------------------------------------------------------------

CANDIDATE_NAME = "Parth Joshi"
CANDIDATE_EMAIL = "paarthjoshi20@gmail.com"
CANDIDATE_LINKEDIN = "https://www.linkedin.com/in/parth-joshi-6459a2235/"

# ---------------------------------------------------------------------------
# Google Sheets tab names
# ---------------------------------------------------------------------------

SHEET_URL_CONFIG = "url_config"
SHEET_SEEN_JOBS = "seen_job"
SHEET_ACTION = "action_sheet"

# ---------------------------------------------------------------------------
# Pipeline (main.py)
# ---------------------------------------------------------------------------

RETRY_COUNT = 2                   # retries per failed step
RETRY_DELAY = 5                   # seconds between retries
