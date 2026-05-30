# JobBot — Automated Job Application System
> Scrape → Score → Tailor → Outreach. A fully automated pipeline that finds relevant jobs, generates tailored resumes, finds hiring contacts, and enables one-click email outreach.

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Component Breakdown](#3-component-breakdown)
4. [Directory Structure](#4-directory-structure)
5. [Config Files](#5-config-files)
6. [Data Flow](#6-data-flow)
7. [Tech Stack](#7-tech-stack)
8. [Cost Breakdown](#8-cost-breakdown)
9. [Setup Guide](#9-setup-guide)
10. [Running the Pipeline](#10-running-the-pipeline)
11. [Google Sheets — Action CSV](#11-google-sheets--action-csv)
12. [Apps Script — Email Trigger](#12-apps-script--email-trigger)
13. [Limitations & Known Issues](#13-limitations--known-issues)
14. [Future Improvements](#14-future-improvements)

---

## 1. Project Overview

### Problem
Applying to jobs through portals (LinkedIn Easy Apply, Naukri, etc.) has a very low interview conversion rate. HR receives hundreds of identical applications and has no reason to prioritise any one of them.

### Solution
A bot that:
- Scrapes fresh job listings daily from LinkedIn across India, US Remote, and Global Remote
- Scores each job against your resume using Claude AI
- Generates a **tailored resume in LaTeX** specific to each job description
- Compiles the resume to PDF and uploads it to Google Drive
- Finds the **email of the HR or job poster** via Skrapp.io
- Finds **relevant LinkedIn profiles** at the company for warm outreach
- Populates a **Google Sheets Action CSV** with all information ready
- Lets you send personalised emails with one button click via Apps Script

### Why This Works Better Than Portal Applications
- You email the actual human who posted the job, not a portal ATS
- Resume is tailored per job — keywords and projects aligned to the JD
- LinkedIn profile outreach creates a second parallel touchpoint
- You apply within 24 hours of posting, when HR is most responsive

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  CONFIG LAYER (manually maintained)                         │
│                                                             │
│  url_config.csv     — LinkedIn search URLs + limits + geo   │
│  resume.tex         — Base LaTeX resume template            │
│  projects.md        — All projects with descriptions        │
│  seen_jobs.csv      — Deduplication log (auto-updated)      │
│  .env               — API keys                              │
└────────────────────────┬────────────────────────────────────┘
                         │ read on every run
                         ↓
┌─────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR  (main.py)  — runs daily at 7:00 AM via cron  │
│                                                             │
│  Step 1 → Apify: scrape LinkedIn jobs per URL               │
│  Step 2 → Deduplicate against seen_jobs.csv                 │
│  Step 3 → Claude: score + geo-filter each job               │
│  Step 4 → Claude: generate tailored LaTeX resume            │
│  Step 5 → pdflatex: compile LaTeX → PDF                     │
│  Step 6 → Google Drive: upload PDF, get shareable link      │
│  Step 7 → Apify: find LinkedIn profiles at company          │
│  Step 8 → Skrapp.io: find emails for those profiles         │
│  Step 9 → Claude: write email body + LinkedIn message       │
│  Step 10 → Append row to Google Sheets Action CSV           │
│  Step 11 → Update seen_jobs.csv                             │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│  ACTION CSV  (Google Sheets)                                │
│                                                             │
│  Source | Company | Role | Score | Geo | Contact Email      │
│  Resume PDF Link | Email Body | LinkedIn Profiles           │
│  LinkedIn Messages | [Send Email] | [Copy LI Message]       │
└────────────────────────┬────────────────────────────────────┘
                         │ manual review + button click
                         ↓
┌─────────────────────────────────────────────────────────────┐
│  EXECUTION  (Google Apps Script)                            │
│                                                             │
│  [Send Email] → fetch PDF from Drive → send via Gmail SMTP  │
│  [Copy LI Message] → copy message to clipboard             │
│  [Mark Applied] → timestamp + status update in sheet        │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Component Breakdown

### 3.1 Job Scraping — Apify LinkedIn Jobs Scraper

- Input: LinkedIn search URLs from `url_config.csv`
- Output: Raw job listings (title, company, description, poster name, job ID, URL)
- Limit: `max_jobs` per URL (defined in config)
- Actor: `apify/linkedin-jobs-scraper`
- Triggered via Apify API from Python

**Why Apify over custom scraper:**
LinkedIn actively detects and bans scrapers. Apify rotates IPs and handles detection. For personal use at this scale, it's the safest and most reliable option.

**Account risk mitigation:**
- Use a secondary LinkedIn account (not your main profile)
- Keep daily scrape volume under 200 jobs total
- Spread scraping across URLs with delays between calls

---

### 3.2 Deduplication — seen_jobs.csv

Every processed job has its LinkedIn Job ID stored in `seen_jobs.csv`. On each run, the script checks this file before processing any job.

```
job_id, title, company, date_first_seen, status
3847291, Data Scientist, Razorpay, 2024-01-15, applied
3901823, ML Engineer, Meesho, 2024-01-15, skipped
```

This prevents:
- Re-generating resumes for the same job on subsequent days
- Sending duplicate emails
- Wasting Claude API tokens on already-seen listings

---

### 3.3 Job Scoring — Claude Haiku API

Claude receives:
- The full job description
- Your base resume (LaTeX source)
- Your projects list (projects.md)
- Geography context

Claude returns a structured JSON response:

```json
{
  "score": 8,
  "reason": "Strong match — JD requires recommendation systems and Python, both present in resume. 3 relevant projects.",
  "apply": true,
  "geo_flag": null,
  "tailoring_notes": "Emphasise the RecSys project and highlight Spark experience mentioned in JD",
  "red_flags": []
}
```

**Geo-filtering rules baked into the Claude prompt:**
- If JD contains "must be authorized to work in the US" → `score: 0`, `apply: false`
- If JD contains "US citizens/residents only" → `score: 0`, `apply: false`
- If hard timezone requirement (EST/PST) with no async option → `geo_flag: "Timezone Risk"`
- Otherwise → score normally regardless of company location

**Score threshold:** Only jobs scoring **7 or above** proceed to resume generation. Saves cost and time.

---

### 3.4 Resume Generation — Claude + LaTeX + pdflatex

For each job scoring 7+, Claude:
1. Reads your `resume.tex` base template
2. Reads relevant projects from `projects.md`
3. Reads the job description + tailoring notes from scoring step
4. Outputs a modified `resume_[job_id].tex` with:
   - Skills section reordered to match JD keywords
   - Most relevant 3–4 projects included
   - Summary/objective line tailored to role
   - Consistent LaTeX formatting maintained

Then locally:
```bash
pdflatex -output-directory=output/resumes/ resume_[job_id].tex
```

Output PDF is then uploaded to a dedicated Google Drive folder via Drive API. A shareable link is stored for the Sheets row.

**Resume modification rules given to Claude:**
- Do NOT invent skills or experience not in the base resume
- Do NOT change dates, company names, or job titles
- Only reorder, emphasise, and select — no fabrication
- Keep total resume to 1 page
- Maintain all LaTeX syntax correctly

---

### 3.5 LinkedIn Profile Finding — Apify LinkedIn Profile Search

For each job that passes scoring, find 3–5 relevant people at the company:

**Search targets (in priority order):**
1. HR Manager / Talent Acquisition / Recruiter (most likely to respond)
2. Hiring Manager in the relevant department (data/engineering)
3. Senior employee in the same team (warm intro path)

Input to Apify:
```python
{
  "company": "Razorpay",
  "titles": ["HR", "Talent Acquisition", "Recruiter", "Data Science Manager", "ML Lead"],
  "max_results": 5
}
```

Output: LinkedIn profile URLs, names, titles, headlines

---

### 3.6 Email Finding — Skrapp.io

Skrapp.io accepts:
- LinkedIn profile URL → returns verified email
- Name + Company domain → returns likely email

Priority:
1. Feed poster LinkedIn URL directly (if visible on job post) → highest accuracy
2. Feed HR profile URLs from Step 3.5 → good accuracy
3. Fallback: domain pattern guess (`hr@company.com`, `careers@company.com`) → ~40% accuracy

Skrapp.io plan: **$49/month for 1,000 credits**. Each email lookup = 1 credit.

---

### 3.7 Message Generation — Claude

For each job, Claude generates:

**Email body** (sent via Apps Script):
```
Subject: Data Scientist Application — [Your Name]

Hi [Name],

I came across the Data Scientist role at [Company] and wanted to reach out directly.

[2-3 lines connecting your most relevant experience to the specific JD]

I've attached my resume tailored to this role. Happy to share more context or jump on a quick call.

Best,
[Your Name]
```

**LinkedIn connection note** (300 char limit):
```
Hi [Name], I saw the DS role at [Company] and wanted to connect directly.
I've built [relevant thing from JD context] and would love to chat if you're open to it.
```

**LinkedIn follow-up message** (sent after connection accepted):
```
Thanks for connecting [Name]. I recently applied for the DS role at [Company].
[One relevant line]. Would a quick 15-min chat work this week?
```

Claude receives the job description, the person's title, and your background summary for each message. All three messages are stored in the Sheets row.

---

## 4. Directory Structure

```
jobbot/
│
├── main.py                  # Orchestrator — runs full pipeline
├── scheduler.py             # Cron setup helper
├── requirements.txt
├── .env                     # API keys (never commit)
├── .gitignore
│
├── config/
│   ├── url_config.csv       # LinkedIn URLs to scrape
│   ├── seen_jobs.csv        # Deduplication log (auto-updated)
│   └── settings.py          # Thresholds, limits, paths
│
├── resume/
│   ├── resume.tex           # Your base LaTeX resume
│   ├── projects.md          # All projects with full descriptions
│   └── output/              # Generated tailored resumes
│       ├── resume_3847291.tex
│       └── resume_3847291.pdf
│
├── modules/
│   ├── scraper.py           # Apify LinkedIn jobs scraper
│   ├── deduplicator.py      # seen_jobs.csv logic
│   ├── scorer.py            # Claude job scoring
│   ├── resume_builder.py    # Claude LaTeX tailoring + pdflatex
│   ├── profile_finder.py    # Apify LinkedIn profile search
│   ├── email_finder.py      # Skrapp.io email lookup
│   ├── message_writer.py    # Claude email + LI message generation
│   ├── drive_uploader.py    # Google Drive PDF upload
│   └── sheets_writer.py     # Append row to Google Sheets
│
├── google_apps_script/
│   └── action_buttons.gs    # Apps Script for Send Email + Copy Message
│
└── logs/
    └── run_YYYY-MM-DD.log
```

---

## 5. Config Files

### url_config.csv

```csv
label,url,max_jobs,active,geography
"DS India Onsite","https://www.linkedin.com/jobs/search/?keywords=data+scientist&location=India&f_WT=1&f_TPR=r86400",30,TRUE,India
"DS India Hybrid","https://www.linkedin.com/jobs/search/?keywords=data+scientist&location=India&f_WT=3&f_TPR=r86400",20,TRUE,India
"DS Remote Global","https://www.linkedin.com/jobs/search/?keywords=data+scientist&f_WT=2&f_TPR=r86400",40,TRUE,Global
"DS US Remote","https://www.linkedin.com/jobs/search/?keywords=data+scientist&location=United+States&f_WT=2&f_TPR=r86400",30,TRUE,US
"ML Engineer India","https://www.linkedin.com/jobs/search/?keywords=ml+engineer&location=India&f_TPR=r86400",30,TRUE,India
"AI Engineer Remote","https://www.linkedin.com/jobs/search/?keywords=ai+engineer&f_WT=2&f_TPR=r86400",30,TRUE,Global
"Data Scientist Startup","https://www.linkedin.com/jobs/search/?keywords=data+scientist&f_E=3,4&f_WT=2&f_TPR=r86400",20,TRUE,Global
```

**LinkedIn URL parameter reference:**

| Parameter | Values |
|---|---|
| `f_WT` | 1=Onsite, 2=Remote, 3=Hybrid |
| `f_TPR` | r86400=24h, r604800=1 week |
| `f_E` | 1=Intern, 2=Entry, 3=Assoc, 4=Mid-Senior, 5=Director |
| `f_JT` | F=Full-time, C=Contract, P=Part-time |

**To add a new search:** Add a row to `url_config.csv`. No code changes needed.
**To pause a search:** Set `active` to `FALSE`.

---

### .env

```env
APIFY_API_TOKEN=your_apify_token
ANTHROPIC_API_KEY=your_claude_key
SKRAPP_API_KEY=your_skrapp_key
GOOGLE_DRIVE_FOLDER_ID=your_drive_folder_id
GOOGLE_SHEETS_ID=your_sheets_id
SENDER_EMAIL=your_gmail@gmail.com
```

---

### settings.py

```python
SCORE_THRESHOLD = 7           # Min score to proceed to resume generation
MAX_JOBS_PER_RUN = 200        # Hard cap across all URLs
MAX_EMAILS_PER_DAY = 30       # Cap on outreach emails sent
RESUME_MAX_PAGES = 1
LATEX_COMPILER = "pdflatex"
LOG_LEVEL = "INFO"
```

---

## 6. Data Flow

### Raw Job Object (from Apify)
```json
{
  "job_id": "3847291",
  "title": "Data Scientist",
  "company": "Razorpay",
  "company_domain": "razorpay.com",
  "location": "Bengaluru, India",
  "work_mode": "Hybrid",
  "posted_date": "2024-01-15",
  "poster_name": "Priya Sharma",
  "poster_linkedin": "https://linkedin.com/in/priya-sharma-hr",
  "poster_title": "Talent Acquisition, Razorpay",
  "description": "Full JD text...",
  "apply_url": "https://linkedin.com/jobs/view/3847291",
  "source_url_label": "DS India Hybrid"
}
```

### Scored Job Object (after Claude scoring)
```json
{
  ...raw fields,
  "score": 8,
  "reason": "Strong match on RecSys and Python. 3 relevant projects.",
  "apply": true,
  "geo_flag": null,
  "tailoring_notes": "Emphasise RecSys project. Highlight Spark.",
  "red_flags": []
}
```

### Complete Job Object (after all steps)
```json
{
  ...scored fields,
  "resume_tex_path": "resume/output/resume_3847291.tex",
  "resume_pdf_path": "resume/output/resume_3847291.pdf",
  "resume_drive_link": "https://drive.google.com/file/d/...",
  "contact_email": "priya.sharma@razorpay.com",
  "email_confidence": "high",
  "linkedin_profiles": [
    {"name": "Priya Sharma", "title": "TA Lead", "url": "...", "email": "priya.sharma@razorpay.com"},
    {"name": "Arjun Mehta", "title": "Data Science Manager", "url": "...", "email": "arjun.mehta@razorpay.com"}
  ],
  "email_subject": "Data Scientist Application — [Your Name]",
  "email_body": "Hi Priya, ...",
  "li_connection_note": "Hi Priya, ...",
  "li_followup_message": "Thanks for connecting..."
}
```

---

## 7. Tech Stack

| Layer | Tool | Purpose |
|---|---|---|
| Job Scraping | Apify `linkedin-jobs-scraper` | Scrape LinkedIn job listings |
| Profile Finding | Apify `linkedin-profile-search` | Find HR + team profiles at company |
| Email Finding | Skrapp.io API | Get verified emails from LinkedIn profiles |
| AI Scoring | Claude Haiku API | Score jobs, generate resumes, write messages |
| PDF Compilation | pdflatex (local) | Compile tailored LaTeX resume to PDF |
| File Storage | Google Drive API | Store and share resume PDFs |
| Action Interface | Google Sheets | Review jobs, trigger email send |
| Email Sending | Gmail SMTP via Apps Script | Send outreach email with PDF attached |
| Orchestration | Python 3.11+ | Tie all steps together |
| Scheduling | cron (Linux/Mac) or Task Scheduler (Windows) | Daily 7 AM run |
| Deduplication | CSV flat file (seen_jobs.csv) | Prevent reprocessing |
| Logging | Python logging module | Per-run logs in /logs |

---

## 8. Cost Breakdown

### Monthly (based on ~150 scraped jobs/day → ~20 qualified/day → ~400 applications/month)

| Component | Tool | Cost |
|---|---|---|
| Job scraping | Apify LinkedIn Jobs | ~$10/mo |
| Profile finding | Apify LinkedIn Profiles | ~$5/mo |
| Email finding | Skrapp.io (1000 credits) | $49/mo |
| AI (scoring + resume + messages) | Claude Haiku API | ~$6/mo |
| PDF compilation | pdflatex (local) | $0 |
| File storage | Google Drive (15GB free) | $0 |
| Email sending | Gmail SMTP via Apps Script | $0 |
| Orchestration | Your own device + Python | $0 |
| **Total** | | **~$70/mo** |

### Cost Per Application
~$70 / 400 applications = **$0.175 per application**

### One-Time Setup Cost
$0 — all tools have free tiers for testing before committing to paid plans.

---

## 9. Setup Guide

### Prerequisites
- Python 3.11+
- pdflatex installed (`sudo apt install texlive-full` or MacTeX)
- Google account (for Drive + Sheets)
- Apify account
- Skrapp.io account
- Anthropic API key

### Step 1 — Clone and install dependencies
```bash
git clone https://github.com/you/jobbot.git
cd jobbot
pip install -r requirements.txt
```

### Step 2 — Set up API keys
```bash
cp .env.example .env
# Fill in all keys in .env
```

### Step 3 — Google Cloud Setup
1. Create a Google Cloud project
2. Enable Google Drive API and Google Sheets API
3. Create a service account → download `credentials.json`
4. Place `credentials.json` in project root
5. Share your Google Drive folder and Google Sheet with the service account email

### Step 4 — Add your resume and projects
```bash
# Add your LaTeX resume
cp ~/your-resume.tex resume/resume.tex

# Add your projects list
# Format: ## Project Name \n Description \n Tech stack \n Links
nano resume/projects.md
```

### Step 5 — Configure URLs
```bash
# Edit url_config.csv with your target job titles and locations
nano config/url_config.csv
```

### Step 6 — Set up Google Sheets
1. Create a new Google Sheet
2. Add the sheet ID to `.env`
3. Copy Apps Script code from `google_apps_script/action_buttons.gs` into the sheet's script editor
4. Deploy the Apps Script

### Step 7 — Set up cron (Linux/Mac)
```bash
# Open crontab
crontab -e

# Add this line — runs at 7 AM daily
0 7 * * * /usr/bin/python3 /path/to/jobbot/main.py >> /path/to/jobbot/logs/cron.log 2>&1
```

### Step 8 — Test run
```bash
# Run with limit of 5 jobs to verify everything works
python main.py --test --limit 5
```

---

## 10. Running the Pipeline

### Normal daily run (automated via cron)
```bash
python main.py
```

### Manual run with options
```bash
# Full run
python main.py

# Test run (5 jobs, no emails sent, no Sheets update)
python main.py --test --limit 5

# Run specific URL label only
python main.py --url-label "DS US Remote"

# Skip resume generation (scoring only)
python main.py --score-only

# Force reprocess a specific job ID (bypasses deduplication)
python main.py --force-job 3847291
```

### What happens each run
1. Reads `url_config.csv` — finds all active URLs
2. For each URL, calls Apify up to `max_jobs` limit
3. Filters out job IDs already in `seen_jobs.csv`
4. Sends new jobs to Claude for scoring
5. Jobs scoring 7+ go through resume generation
6. pdflatex compiles each resume, PDF uploaded to Drive
7. Apify finds LinkedIn profiles at each company
8. Skrapp.io finds emails for those profiles
9. Claude writes email body and LinkedIn messages
10. New rows appended to Google Sheets Action CSV
11. `seen_jobs.csv` updated with all processed job IDs
12. Run log saved to `logs/run_YYYY-MM-DD.log`

---

## 11. Google Sheets — Action CSV

### Columns

| Column | Description |
|---|---|
| Date | Date job was found |
| Source | URL label from url_config.csv |
| Geography | India / US Remote / Global |
| Company | Company name |
| Role | Job title |
| Score | Claude relevance score (1–10) |
| Score Reason | One-line explanation |
| Red Flags | Any issues flagged by Claude |
| Geo Flag | e.g. "Timezone Risk" |
| Job URL | LinkedIn job posting URL |
| Contact Name | Primary contact (poster or HR) |
| Contact Title | Their job title |
| Contact Email | Verified email from Skrapp |
| Email Confidence | High / Medium / Guessed |
| Resume PDF | Google Drive link to tailored PDF |
| Email Subject | Pre-written subject line |
| Email Body | Pre-written email body |
| LI Profile 1 | LinkedIn URL |
| LI Message 1 | Connection note for Profile 1 |
| LI Profile 2 | LinkedIn URL |
| LI Message 2 | Connection note for Profile 2 |
| LI Followup | Message to send after connection accepted |
| Status | Pending / Emailed / LI Sent / Replied / Interview |
| Date Applied | Timestamp when email sent |
| Notes | Your manual notes |
| **[Send Email]** | Button — triggers Apps Script |
| **[Copy LI Msg]** | Button — copies LI message to clipboard |
| **[Mark Applied]** | Button — updates status + timestamp |

---

## 12. Apps Script — Email Trigger

Located at `google_apps_script/action_buttons.gs`

### What it does
- **[Send Email]** — reads contact email, fetches PDF from Drive, sends personalised email via Gmail, updates status to "Emailed", stamps date
- **[Copy LI Message]** — copies the LinkedIn message for the row to clipboard
- **[Mark Applied]** — sets status to "Applied" with current timestamp

### Key behaviour
- Does not send automatically — requires manual button click (intentional human gate)
- Checks that email has not already been sent for this row (prevents duplicates)
- Logs every send to a separate "Sent Log" tab in the sheet

---

## 13. Limitations & Known Issues

| Issue | Impact | Mitigation |
|---|---|---|
| LinkedIn scraper detection | Apify account/IP may get flagged | Use secondary LinkedIn account, stay under 200 jobs/day |
| Not all job posters visible | ~40% of jobs show no poster | Fallback to Apollo/Skrapp company search by title |
| US-only remote jobs slipping through | Wasted resume generation | Claude geo-filter prompt catches most; manual review in Sheets catches rest |
| pdflatex compile errors | Resume not generated for that job | Logged to run log; row still added to Sheets with error flag |
| Skrapp.io email accuracy | ~70–80% verified rate | Low-confidence emails flagged in sheet; you decide whether to send |
| LaTeX resume fabrication by Claude | Claude might add non-existent skills | Explicit instruction in prompt; human review recommended before sending |
| Google Sheets row limit | 10M cells max | Not a practical concern at this scale |

---

## 14. Future Improvements

- **ATS-safe resume format** — generate plain text / Word version in addition to PDF for companies using keyword-scanning ATS
- **Naukri / Instahyre scraper** — Playwright-based custom scraper for India-specific portals not on LinkedIn
- **Interview tracker tab** — separate Sheets tab to track responses, interview stages, and offers
- **Telegram/WhatsApp notification** — ping when a new high-score batch is ready to review
- **Reply detection** — Gmail API watches for replies; auto-updates status in Sheets
- **Automatic LinkedIn connection send** — PhantomBuster integration to auto-send connection requests (higher risk, optional)
- **Company research enrichment** — for high-score jobs, Claude fetches company info (funding stage, team size, recent news) to personalise emails further
- **Duplicate email guard** — cross-check against all previously sent emails before allowing send

---

*Last updated: see git log*
*Owner: Zardat*
