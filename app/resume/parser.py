"""
Parses a resume file (PDF or DOCX) into structured JSON that the job matcher
(step 5) will embed and compare against each posting's description.

This stage intentionally does light extraction only: raw text plus a
line-by-line breakdown. Splitting that text into skills, experience bullets,
etc. is left to the matcher step, where it's done via embeddings rather than
brittle keyword rules.
"""

import json
import os
from pathlib import Path

import pdfplumber
from docx import Document
from dotenv import load_dotenv

load_dotenv()

OUTPUT_PATH = Path("/app/data/resume_data.json")


def parse_pdf(path: Path) -> str:
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


def parse_docx(path: Path) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def parse_resume(path: str) -> dict:
    resume_path = Path(path)
    if not resume_path.exists():
        raise FileNotFoundError(
            f"Resume not found at {resume_path}. "
            f"Check RESUME_PATH in .env and that the file is mounted into /app/data."
        )

    suffix = resume_path.suffix.lower()
    if suffix == ".pdf":
        raw_text = parse_pdf(resume_path)
    elif suffix == ".docx":
        raw_text = parse_docx(resume_path)
    else:
        raise ValueError(f"Unsupported resume format: {suffix} (use .pdf or .docx)")

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    return {
        "source_file": str(resume_path),
        "raw_text": raw_text,
        "lines": lines,
    }


def save_resume_data(data: dict, output_path: Path = OUTPUT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2))
    print(f"Parsed resume saved to {output_path} ({len(data['lines'])} lines).")


if __name__ == "__main__":
    # Run this directly to test parsing:
    #   docker compose run --rm app python resume/parser.py
    resume_path = os.environ.get("RESUME_PATH", "/app/data/resume.pdf")
    data = parse_resume(resume_path)
    save_resume_data(data)
