import os
import subprocess
import anthropic
from pathlib import Path
from dotenv import load_dotenv
from modules.drive_uploader import upload_resume

load_dotenv()

RESUME_PATH = Path(__file__).parent.parent / "resume.tex"
PROJECTS_PATH = Path(__file__).parent.parent / "projects.md"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "resumes"

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _strip_keyword_block(latex):
    """Remove the hidden keyword minipage so Claude doesn't have to reproduce it."""
    start = latex.find(r"\begin{minipage}")
    if start == -1:
        return latex, ""
    end = latex.find(r"\end{minipage}", start)
    if end == -1:
        return latex, ""
    end += len(r"\end{minipage}")
    return latex[:start] + latex[end:], latex[start:end]


def _generate_latex(job):
    resume_full = RESUME_PATH.read_text()
    resume, keyword_block = _strip_keyword_block(resume_full)
    projects = PROJECTS_PATH.read_text()

    prompt = f"""You are making minimal targeted edits to a LaTeX resume for a specific job. Return ONLY the complete modified LaTeX source — no explanation, no markdown, no code fences.

YOU MAY ONLY CHANGE THESE TWO THINGS:
1. SKILLS SECTION — reorder the skill categories and keywords to put the most relevant ones first based on the JD. Do not add or remove any skills.
2. PROJECT BULLET POINTS — for each project that is already in the resume, you may rewrite or reorder its bullet points to emphasise aspects relevant to the JD. Do not add or remove entire projects.

CRITICAL LATEX RULES:
- Always close environments with \\end{{envname}} — NEVER use HTML-style closing tags like </envname>
- Every \\begin{{onecolentry}} must be closed with \\end{{onecolentry}}
- Every \\begin{{twocolentry}} must be closed with \\end{{twocolentry}}
- Every \\begin{{highlights}} must be closed with \\end{{highlights}}

DO NOT CHANGE ANYTHING ELSE:
- Do not touch the header, contact info, education, experience section, research section
- Do not add or remove sections
- Do not change dates, company names, job titles
- Do not add blank lines, extra whitespace, or page breaks at the start of the document
- Keep the hidden keyword minipage section at the bottom exactly as-is
- The output must start with the exact same \\documentclass line as the input

BASE RESUME (LaTeX):
{resume}

JOB DETAILS:
Title: {job.get('title')}
Company: {job.get('company')}
Description:
{job.get('description')}

TAILORING NOTES:
{job.get('tailoring_notes', '')}

Return the complete modified LaTeX source now:"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8096,
        messages=[{"role": "user", "content": prompt}],
    )

    latex = message.content[0].text.strip()

    # Reattach the keyword block before \end{document}
    if keyword_block and r"\end{document}" in latex:
        latex = latex.replace(r"\end{document}", keyword_block + "\n\\end{document}")

    return latex


def _compile_pdf(tex_path):
    cmd = [
        "pdflatex",
        "-interaction=nonstopmode",
        f"-output-directory={OUTPUT_DIR}",
        str(tex_path),
    ]
    # Run twice so LastPage and cross-references resolve correctly
    for _ in range(2):
        subprocess.run(cmd, capture_output=True, text=True)

    pdf_path = OUTPUT_DIR / (tex_path.stem + ".pdf")
    if not pdf_path.exists():
        raise RuntimeError(f"pdflatex did not produce a PDF for {tex_path.name}")


def _cleanup(job_id):
    for ext in [".aux", ".log", ".out", ".tex"]:
        f = OUTPUT_DIR / f"resume_{job_id}{ext}"
        if f.exists():
            f.unlink()


def build_resume(job):
    job_id = job.get("job_id")
    tex_path = OUTPUT_DIR / f"resume_{job_id}.tex"
    pdf_path = OUTPUT_DIR / f"resume_{job_id}.pdf"

    print(f"[resume_builder] Generating LaTeX for {job.get('company')} — {job.get('title')}...")
    latex = _generate_latex(job)
    tex_path.write_text(latex)

    print(f"[resume_builder] Compiling PDF...")
    _compile_pdf(tex_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not created: {pdf_path}")

    print(f"[resume_builder] Uploading to Drive...")
    drive_link = upload_resume(str(pdf_path), job_id)

    # _cleanup(job_id)  # disabled for debugging

    job["resume_drive_link"] = drive_link
    return job
