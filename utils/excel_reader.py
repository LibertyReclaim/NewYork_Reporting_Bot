from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd


def _normalize_cell(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _rows_from_sheet(workbook_path: str, sheet_name: str) -> List[Dict[str, str]]:
    df = pd.read_excel(workbook_path, sheet_name=sheet_name, dtype=object, engine="openpyxl")
    df = df.fillna("")

    rows: List[Dict[str, str]] = []
    for _, row in df.iterrows():
        clean = {str(col).strip(): _normalize_cell(val) for col, val in row.items()}
        if any(v != "" for v in clean.values()):
            rows.append(clean)
    return rows


def load_workbook_data(workbook_path: str) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]]]:
    """Load Companies, Filings, and State_Requirements sheets into row dictionaries."""
    if not os.path.exists(workbook_path):
        raise FileNotFoundError(f"Workbook not found: {workbook_path}")

    companies_rows = _rows_from_sheet(workbook_path, "Companies")
    filings_rows = _rows_from_sheet(workbook_path, "Filings")
    try:
        state_requirements_rows = _rows_from_sheet(workbook_path, "State_Requirements")
    except ValueError as exc:
        # Optional sheet: if missing, return an empty list instead of crashing.
        if "Worksheet named 'State_Requirements' not found" in str(exc):
            state_requirements_rows = []
        else:
            raise

    return companies_rows, filings_rows, state_requirements_rows


def get_company_by_name(companies_rows: Sequence[Dict[str, str]], company_name: str) -> Optional[Dict[str, str]]:
    target = _normalize_cell(company_name).lower()
    for row in companies_rows:
        if _normalize_cell(row.get("company_name", "")).lower() == target:
            return row
    return None


def get_filings_for_company_and_states(
    filings_rows: Sequence[Dict[str, str]], company_id: str, state_codes: Sequence[str]
) -> List[Dict[str, str]]:
    target_company_id = _normalize_cell(company_id)
    target_states = {s.strip().upper() for s in state_codes if s and str(s).strip()}

    out: List[Dict[str, str]] = []
    for row in filings_rows:
        row_company_id = _normalize_cell(row.get("company_id", ""))
        row_state = _normalize_cell(row.get("state_code", "")).upper()
        if row_company_id == target_company_id and row_state in target_states:
            out.append(row)
    return out
