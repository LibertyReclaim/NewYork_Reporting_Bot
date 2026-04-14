from __future__ import annotations

from pathlib import Path
import re


def clean_blank(value: object, default: str = "") -> str:
    """Convert None/NaN-like values to a safe string."""
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return default
    return text


def clean_filename_part(value: object, fallback: str = "UNKNOWN") -> str:
    """Return a filesystem-safe token for filenames/folders."""
    text = clean_blank(value, default=fallback)
    sanitized = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    sanitized = re.sub(r"\s+", " ", sanitized).strip(" .")
    return sanitized or fallback


def build_naupa_path(project_root: Path, company_name: object, state_code: object, report_year: object) -> Path:
    """
    Build path:
      project_root / company_name / "[Company Name]_[STATE] [YEAR] NAUPA.txt"
    """
    company = clean_filename_part(company_name)
    state = clean_filename_part(state_code).upper()
    year = clean_filename_part(report_year)
    filename = f"{company}_{state} {year} NAUPA.txt"
    return project_root / company / filename
