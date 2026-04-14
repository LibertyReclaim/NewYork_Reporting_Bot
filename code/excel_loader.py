from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from path_utils import clean_blank


HOLDER_FILE = "holder_information.xlsx"
PAYMENT_FILE = "payment_file.xlsx"


def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized = normalized.fillna("")
    for column in normalized.columns:
        normalized[column] = normalized[column].map(lambda v: clean_blank(v, default=""))
    return normalized


def _ensure_holder_id(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    if "holder_id" not in df.columns:
        raise ValueError(f"'{source_name}' is missing required column: holder_id")
    df["holder_id"] = df["holder_id"].map(lambda v: clean_blank(v, default=""))
    return df


def load_and_merge_records(project_root: Path) -> list[dict[str, Any]]:
    """
    Load holder_information.xlsx and payment_file.xlsx from project root,
    normalize blanks safely, and merge records on holder_id.
    """
    holder_path = project_root / HOLDER_FILE
    payment_path = project_root / PAYMENT_FILE

    if not holder_path.exists():
        raise FileNotFoundError(f"Missing required file: {holder_path}")
    if not payment_path.exists():
        raise FileNotFoundError(f"Missing required file: {payment_path}")

    holder_df = pd.read_excel(holder_path, dtype=str)
    payment_df = pd.read_excel(payment_path, dtype=str)

    holder_df = _ensure_holder_id(_normalize_dataframe(holder_df), HOLDER_FILE)
    payment_df = _ensure_holder_id(_normalize_dataframe(payment_df), PAYMENT_FILE)

    merged_df = holder_df.merge(
        payment_df,
        on="holder_id",
        how="left",
        suffixes=("", "_payment"),
    )

    records = merged_df.to_dict(orient="records")
    return [{k: clean_blank(v, default="") for k, v in row.items()} for row in records]
